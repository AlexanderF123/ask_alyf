"""Build and query a site-scoped LlamaIndex over installed app code.

This module maintains an incremental index for `.py` and `.js` files across
installed Frappe apps, stores it in each site's private directory, and exposes
retrieval helpers for prompt-context injection.
"""

import json
import os
import shutil
from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import uuid4

import frappe
from any_llm import AnyLLM
from frappe import _
from frappe.utils import get_bench_path
from frappe.utils.caching import site_cache
from frappe.utils.data import cint
from frappe.utils.file_lock import LockTimeoutError
from frappe.utils.synchronization import filelock
from llama_index.core import (
	SimpleDirectoryReader,
	StorageContext,
	VectorStoreIndex,
	load_index_from_storage,
)
from llama_index.core.base.embeddings.base import BaseEmbedding

from ask_alyf.ask_alyf.doctype.ask_alyf_settings.ask_alyf_settings import get_any_llm_provider

INDEX_DIRECTORY_NAME = "llamaindex_code_index"
STAGING_DIRECTORY_NAME = f"{INDEX_DIRECTORY_NAME}_rebuild"
SYNC_STATE_FILE_NAME = f"{INDEX_DIRECTORY_NAME}_sync_state.json"
MANIFEST_FILE_NAME = "file_manifest.json"
SUPPORTED_EXTENSIONS = (
	".py",
	".js",
	".ts",
	".jsx",
	".html",
	".css",
	".scss",
	".json",
	".vue",
	".tsx",
	".txt",
	".toml",
	".md",
	".yml",
	".yaml",
	".sql",
)
EXTENSION_LANGUAGE_MAP = {
	".py": "python",
	".js": "javascript",
	".ts": "typescript",
	".jsx": "jsx",
	".tsx": "tsx",
	".html": "html",
	".css": "css",
	".scss": "scss",
	".json": "json",
	".vue": "vue",
	".sql": "sql",
	".yml": "yaml",
	".yaml": "yaml",
	".md": "markdown",
	".toml": "toml",
	".txt": "text",
}
INDEX_SENTINEL_FILES = ("docstore.json", "index_store.json", "graph_store.json")
MAX_FILE_SIZE = 1_000_000  # 1 MB - skip minified bundles, large fixtures, etc.
MAX_NODE_CONTENT_CHARS = 2500
DEFAULT_TOP_K = 5
SYNC_BATCH_SIZE = 25
SYNC_LOCK_NAME = "ask_alyf_code_index_sync"
SYNC_LOCK_TIMEOUT = 10
FALLBACK_IGNORED_DIRECTORY_NAMES = {
	".git",
	".hg",
	".svn",
	".tox",
	".venv",
	"__pycache__",
	"env",
	"node_modules",
	"venv",
}


class AnyLLMEmbedding(BaseEmbedding):
	"""LlamaIndex embedding adapter backed by AnyLLM providers."""

	provider: str
	api_key: str
	api_base: str | None = None

	def _create_client(self) -> AnyLLM:
		return AnyLLM.create(self.provider, api_key=self.api_key, api_base=self.api_base)

	def _extract_embeddings(self, response: Any) -> list[list[float]]:
		return [list(item.embedding) for item in response.data]

	def _get_query_embedding(self, query: str) -> list[float]:
		return self._get_text_embedding(query)

	async def _aget_query_embedding(self, query: str) -> list[float]:
		return await self._aget_text_embedding(query)

	def _get_text_embedding(self, text: str) -> list[float]:
		return self._get_text_embeddings([text])[0]

	async def _aget_text_embedding(self, text: str) -> list[float]:
		return (await self._aget_text_embeddings([text]))[0]

	def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
		frappe.logger("ask_alyf").info(
			"Code index embedding batch started: model=%s size=%s",
			self.model_name,
			len(texts),
		)
		response = self._create_client()._embedding(self.model_name, texts)
		frappe.logger("ask_alyf").info(
			"Code index embedding batch finished: model=%s size=%s",
			self.model_name,
			len(texts),
		)
		return self._extract_embeddings(response)

	async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
		frappe.logger("ask_alyf").info(
			"Code index embedding batch started: model=%s size=%s",
			self.model_name,
			len(texts),
		)
		response = await self._create_client().aembedding(self.model_name, texts)
		frappe.logger("ask_alyf").info(
			"Code index embedding batch finished: model=%s size=%s",
			self.model_name,
			len(texts),
		)
		return self._extract_embeddings(response)


def get_code_index_storage_path() -> Path:
	"""Return the site-private directory used for index persistence."""
	return Path(frappe.get_site_path("private", INDEX_DIRECTORY_NAME))


def get_code_index_staging_path() -> Path:
	"""Return the site-private directory used for staged rebuilds."""
	return Path(frappe.get_site_path("private", STAGING_DIRECTORY_NAME))


def get_code_index_sync_state_path() -> Path:
	"""Return the persisted state path used for chunked syncs."""
	return Path(frappe.get_site_path("private", SYNC_STATE_FILE_NAME))


def enqueue_codebase_index_sync(
	force_full: bool = False,
	*,
	deduplicate: bool = True,
	job_id: str | None = None,
):
	"""Enqueue the background sync job for the current site's code index."""
	if not _is_code_search_enabled():
		frappe.logger("ask_alyf").info("Code index sync skipped: code search disabled")
		return

	job_id = job_id or f"{frappe.local.site}:ask_alyf:code-index-sync"
	frappe.enqueue(
		"ask_alyf.ask_alyf.code_index.sync_codebase_index",
		queue="long",
		timeout=3600,
		job_id=job_id,
		deduplicate=deduplicate,
		force_full=force_full,
	)


def clear_codebase_index() -> dict[str, Any]:
	"""Remove any persisted code index for the current site."""
	index_dir = get_code_index_storage_path()
	staging_dir = get_code_index_staging_path()
	_clear_sync_state()
	_clear_index_directory(index_dir)
	_clear_index_directory(staging_dir)
	_load_index.clear_cache()
	return {"status": "cleared", "site": frappe.local.site, "index_path": str(index_dir)}


def sync_codebase_index(force_full: bool = False) -> dict[str, Any]:
	"""Incrementally sync the persisted code index with installed app files.

	Acquires a site-scoped file lock so that only one sync runs at a time.
	If another sync already holds the lock, this invocation is skipped.
	"""
	if not _is_code_search_enabled():
		return {"status": "skipped_disabled", "site": frappe.local.site}

	try:
		with filelock(SYNC_LOCK_NAME, timeout=SYNC_LOCK_TIMEOUT):
			return _sync_codebase_index(force_full=force_full)
	except LockTimeoutError:
		frappe.logger("ask_alyf").info("Code index sync skipped: lock held by another process")
		return {"status": "skipped_locked", "site": frappe.local.site}


def _sync_codebase_index(force_full: bool = False) -> dict[str, Any]:
	"""Core sync logic, expected to run under the ``SYNC_LOCK_NAME`` lock."""
	try:
		logger = frappe.logger("ask_alyf")
		index_dir = get_code_index_storage_path()
		state = _read_sync_state()

		if state:
			logger.info(
				"Code index sync resuming: site=%s run_id=%s rebuild_index=%s remaining_changed=%s remaining_removed=%s",
				frappe.local.site,
				state.get("run_id"),
				state.get("rebuild_index"),
				len(state.get("pending_changed_paths") or []),
				len(state.get("pending_removed_paths") or []),
			)
			if force_full and not state.get("rebuild_index"):
				logger.info(
					"Code index sync resume ignored new force_full request: site=%s run_id=%s",
					frappe.local.site,
					state.get("run_id"),
				)
			return _process_sync_state(state)

		logger.info(
			"Code index sync started: site=%s force_full=%s index_path=%s",
			frappe.local.site,
			force_full,
			index_dir,
		)

		current_files = _scan_installed_code_files()
		previous_manifest = _read_manifest(index_dir)
		rebuild_index = force_full or not _has_persisted_index(index_dir)
		logger.info(
			"Code index scan finished: site=%s scanned_files=%s previous_manifest_files=%s rebuild_index=%s",
			frappe.local.site,
			len(current_files),
			len(previous_manifest),
			rebuild_index,
		)

		if rebuild_index:
			changed_paths = sorted(current_files.keys())
			removed_paths: list[str] = []
		else:
			changed_paths, removed_paths = _calculate_deltas(current_files, previous_manifest)
		logger.info(
			"Code index delta computed: site=%s changed_files=%s removed_files=%s",
			frappe.local.site,
			len(changed_paths),
			len(removed_paths),
		)

		if not changed_paths and not removed_paths:
			summary = {
				"status": "no_changes",
				"indexed_files": len(current_files),
				"changed_files": 0,
				"removed_files": 0,
				"failed_files": 0,
				"site": frappe.local.site,
				"index_path": str(index_dir),
			}
			frappe.logger("ask_alyf").info("Code index sync skipped: %(summary)s", {"summary": summary})
			return summary

		state = _create_sync_state(
			current_files=current_files,
			changed_paths=changed_paths,
			removed_paths=removed_paths,
			rebuild_index=rebuild_index,
			force_full=force_full,
		)
		logger.info(
			"Code index sync queued chunked run: site=%s run_id=%s rebuild_index=%s changed_files=%s removed_files=%s working_index_path=%s",
			frappe.local.site,
			state.get("run_id"),
			rebuild_index,
			len(changed_paths),
			len(removed_paths),
			state.get("working_index_path"),
		)
		_write_sync_state(state)
		return _process_sync_state(state)
	except Exception:
		frappe.log_error(title="Ask ALYF Code Index Sync Error")
		raise


def _create_sync_state(
	*,
	current_files: dict[str, dict[str, Any]],
	changed_paths: list[str],
	removed_paths: list[str],
	rebuild_index: bool,
	force_full: bool,
) -> dict[str, Any]:
	"""Build the persisted state for a chunked code index sync run."""
	index_dir = get_code_index_storage_path()
	working_index_dir = _get_working_index_path(rebuild_index=rebuild_index, live_index_dir=index_dir)
	if rebuild_index:
		_clear_index_directory(working_index_dir)
		working_index_dir.mkdir(parents=True, exist_ok=True)

	return {
		"version": 1,
		"site": frappe.local.site,
		"run_id": uuid4().hex,
		"force_full": bool(force_full),
		"rebuild_index": bool(rebuild_index),
		"current_files": current_files,
		"pending_changed_paths": list(changed_paths),
		"pending_removed_paths": [] if rebuild_index else list(removed_paths),
		"total_changed_files": len(changed_paths),
		"total_removed_files": 0 if rebuild_index else len(removed_paths),
		"processed_changed_files": 0,
		"processed_removed_files": 0,
		"loaded_documents": 0,
		"failed_files": [],
		"live_index_path": str(index_dir),
		"working_index_path": str(working_index_dir),
	}


def _process_sync_state(state: dict[str, Any]) -> dict[str, Any]:
	"""Process a single sync chunk and persist progress for the next worker run."""
	logger = frappe.logger("ask_alyf")
	rebuild_index = bool(state.get("rebuild_index"))
	current_files = state.get("current_files") or {}
	pending_removed_paths = list(state.get("pending_removed_paths") or [])
	pending_changed_paths = list(state.get("pending_changed_paths") or [])
	removed_batch = pending_removed_paths[:SYNC_BATCH_SIZE]
	changed_batch = [] if removed_batch else pending_changed_paths[:SYNC_BATCH_SIZE]
	working_index_dir = Path(state.get("working_index_path") or get_code_index_storage_path())

	logger.info(
		"Code index chunk started: site=%s run_id=%s rebuild_index=%s removed_batch=%s changed_batch=%s remaining_removed=%s remaining_changed=%s",
		frappe.local.site,
		state.get("run_id"),
		rebuild_index,
		len(removed_batch),
		len(changed_batch),
		len(pending_removed_paths),
		len(pending_changed_paths),
	)

	documents, load_failures = _load_documents(changed_paths=changed_batch, current_files=current_files)
	if load_failures:
		frappe.log_error(
			title="Ask ALYF Code Index Read Error",
			message=_format_document_load_failures(load_failures),
		)
	logger.info(
		"Code index chunk document load finished: site=%s run_id=%s loaded_documents=%s failed_files=%s",
		frappe.local.site,
		state.get("run_id"),
		len(documents),
		len(load_failures),
	)

	try:
		if rebuild_index:
			_process_rebuild_chunk(working_index_dir=working_index_dir, documents=documents)
		else:
			_process_incremental_chunk(
				working_index_dir=working_index_dir,
				removed_paths=removed_batch,
				documents=documents,
			)
	except Exception:
		if not rebuild_index:
			logger.warning(
				"Code index incremental chunk failed to load persisted index, restarting as staged rebuild: site=%s run_id=%s",
				frappe.local.site,
				state.get("run_id"),
				exc_info=True,
			)
			restarted_state = _restart_sync_state_as_rebuild(state)
			return _process_sync_state(restarted_state)
		raise

	state["pending_removed_paths"] = pending_removed_paths[len(removed_batch) :]
	state["pending_changed_paths"] = pending_changed_paths[len(changed_batch) :]
	state["processed_removed_files"] = int(state.get("processed_removed_files") or 0) + len(removed_batch)
	state["processed_changed_files"] = int(state.get("processed_changed_files") or 0) + len(changed_batch)
	state["loaded_documents"] = int(state.get("loaded_documents") or 0) + len(documents)
	state["failed_files"] = [*(state.get("failed_files") or []), *load_failures]

	if state["pending_removed_paths"] or state["pending_changed_paths"]:
		_write_sync_state(state)
		_enqueue_followup_sync(state)
		summary = _build_sync_summary(state, status="in_progress")
		logger.info("Code index chunk finished and requeued: %(summary)s", {"summary": summary})
		return summary

	return _finalize_sync_state(state)


def _process_rebuild_chunk(*, working_index_dir: Path, documents: list[Any]):
	"""Apply one rebuild chunk to the staged index directory."""
	logger = frappe.logger("ask_alyf")
	if not documents:
		return

	if _has_persisted_index(working_index_dir):
		logger.info("Code index rebuild chunk loading staged index: site=%s", frappe.local.site)
		index = _load_persisted_index(working_index_dir)
		_refresh_index(index, documents)
	else:
		logger.info(
			"Code index rebuild chunk creating staged index: site=%s documents=%s",
			frappe.local.site,
			len(documents),
		)
		storage_context = StorageContext.from_defaults()
		index = VectorStoreIndex.from_documents(
			documents,
			storage_context=storage_context,
			embed_model=_get_embed_model(),
		)

	logger.info("Code index rebuild chunk persistence started: site=%s", frappe.local.site)
	index.storage_context.persist(persist_dir=str(working_index_dir))
	logger.info("Code index rebuild chunk persistence finished: site=%s", frappe.local.site)


def _process_incremental_chunk(
	*,
	working_index_dir: Path,
	removed_paths: list[str],
	documents: list[Any],
):
	"""Apply one incremental chunk directly to the live persisted index."""
	if not removed_paths and not documents:
		return

	logger = frappe.logger("ask_alyf")
	logger.info("Code index incremental chunk loading persisted index: site=%s", frappe.local.site)
	index = _load_persisted_index(working_index_dir)
	for relative_path in removed_paths:
		_delete_ref_doc(index, relative_path)

	_refresh_index(index, documents)
	logger.info("Code index incremental chunk persistence started: site=%s", frappe.local.site)
	index.storage_context.persist(persist_dir=str(working_index_dir))
	logger.info("Code index incremental chunk persistence finished: site=%s", frappe.local.site)


def _restart_sync_state_as_rebuild(state: dict[str, Any]) -> dict[str, Any]:
	"""Restart the current sync as a staged rebuild without dropping the live index."""
	restarted_state = _create_sync_state(
		current_files=state.get("current_files") or {},
		changed_paths=sorted((state.get("current_files") or {}).keys()),
		removed_paths=[],
		rebuild_index=True,
		force_full=True,
	)
	restarted_state["failed_files"] = list(state.get("failed_files") or [])
	restarted_state["loaded_documents"] = int(state.get("loaded_documents") or 0)
	_write_sync_state(restarted_state)
	return restarted_state


def _finalize_sync_state(state: dict[str, Any]) -> dict[str, Any]:
	"""Finalize a completed sync run and clean up persisted state."""
	logger = frappe.logger("ask_alyf")
	live_index_dir = Path(state.get("live_index_path") or get_code_index_storage_path())
	working_index_dir = Path(state.get("working_index_path") or live_index_dir)
	current_files = state.get("current_files") or {}
	rebuild_index = bool(state.get("rebuild_index"))

	if rebuild_index and not _has_persisted_index(working_index_dir) and current_files:
		summary = _build_sync_summary(state, status="failed_rebuild_empty")
		logger.error(
			"Code index rebuild completed without a usable rebuilt index; preserving live index: %(summary)s",
			{"summary": summary},
		)
		if working_index_dir != live_index_dir:
			_clear_index_directory(working_index_dir)
		_clear_sync_state()
		return summary

	if rebuild_index and working_index_dir != live_index_dir:
		_promote_rebuilt_index(working_index_dir=working_index_dir, live_index_dir=live_index_dir)

	_load_index.clear_cache()
	_write_manifest(live_index_dir, current_files)
	_clear_sync_state()
	summary = _build_sync_summary(state, status="rebuilt" if rebuild_index else "updated")
	logger.info("Code index sync finished: %(summary)s", {"summary": summary})
	return summary


def _build_sync_summary(state: dict[str, Any], *, status: str) -> dict[str, Any]:
	"""Build a user-facing sync summary from the persisted state."""
	live_index_dir = Path(state.get("live_index_path") or get_code_index_storage_path())
	failed_files = list(state.get("failed_files") or [])
	return {
		"status": status,
		"indexed_files": len(state.get("current_files") or {}),
		"changed_files": int(state.get("total_changed_files") or 0),
		"removed_files": int(state.get("total_removed_files") or 0),
		"processed_changed_files": int(state.get("processed_changed_files") or 0),
		"processed_removed_files": int(state.get("processed_removed_files") or 0),
		"remaining_changed_files": len(state.get("pending_changed_paths") or []),
		"remaining_removed_files": len(state.get("pending_removed_paths") or []),
		"loaded_documents": int(state.get("loaded_documents") or 0),
		"failed_files": len(failed_files),
		"site": frappe.local.site,
		"index_path": str(live_index_dir),
	}


def _get_working_index_path(*, rebuild_index: bool, live_index_dir: Path) -> Path:
	"""Return the directory that should receive writes for this sync run."""
	if rebuild_index and _has_persisted_index(live_index_dir):
		return get_code_index_staging_path()
	return live_index_dir


def _load_persisted_index(index_dir: Path):
	"""Load a persisted index from disk using the configured embedding model."""
	storage_context = StorageContext.from_defaults(persist_dir=str(index_dir))
	return load_index_from_storage(storage_context, embed_model=_get_embed_model())


def _enqueue_followup_sync(state: dict[str, Any]):
	"""Queue the next chunk in the current sync run."""
	run_id = state.get("run_id") or "unknown"
	sequence = int(state.get("processed_changed_files") or 0) + int(state.get("processed_removed_files") or 0)
	enqueue_codebase_index_sync(
		force_full=bool(state.get("force_full")),
		deduplicate=False,
		job_id=f"{frappe.local.site}:ask_alyf:code-index-sync:{run_id}:{sequence}",
	)


def _read_sync_state() -> dict[str, Any] | None:
	"""Read the chunked sync state from disk, if any."""
	state_path = get_code_index_sync_state_path()
	if not state_path.exists():
		return None

	try:
		payload = json.loads(state_path.read_text(encoding="utf-8"))
	except Exception:
		return None

	if not isinstance(payload, dict):
		return None

	current_files = payload.get("current_files")
	if not isinstance(current_files, dict):
		return None

	payload["current_files"] = {
		path: metadata
		for path, metadata in current_files.items()
		if isinstance(path, str) and isinstance(metadata, dict)
	}
	payload["pending_changed_paths"] = [
		path for path in payload.get("pending_changed_paths") or [] if isinstance(path, str)
	]
	payload["pending_removed_paths"] = [
		path for path in payload.get("pending_removed_paths") or [] if isinstance(path, str)
	]
	payload["failed_files"] = [item for item in payload.get("failed_files") or [] if isinstance(item, dict)]
	return payload


def _write_sync_state(state: dict[str, Any]):
	"""Persist the chunked sync state to disk."""
	state_path = get_code_index_sync_state_path()
	state_path.parent.mkdir(parents=True, exist_ok=True)
	state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _clear_sync_state():
	"""Remove any persisted chunked sync state."""
	state_path = get_code_index_sync_state_path()
	try:
		state_path.unlink()
	except FileNotFoundError:
		pass


def _promote_rebuilt_index(*, working_index_dir: Path, live_index_dir: Path):
	"""Atomically replace the live index with a completed staged rebuild."""
	backup_dir = live_index_dir.with_name(f"{live_index_dir.name}_backup")
	_clear_index_directory(backup_dir)
	if live_index_dir.exists():
		live_index_dir.rename(backup_dir)

	try:
		working_index_dir.rename(live_index_dir)
	except Exception:
		if backup_dir.exists() and not live_index_dir.exists():
			backup_dir.rename(live_index_dir)
		raise
	else:
		_clear_index_directory(backup_dir)


def search_codebase(query: str, top_k: int = DEFAULT_TOP_K) -> str:
	"""Retrieve top-k semantically relevant code snippets from the index."""
	query = (query or "").strip()
	if not query:
		frappe.throw(_("Search query is required."))
	if not _is_code_search_enabled():
		return _("Code search is disabled in Ask ALYF Settings.")

	top_k_value = max(1, cint(top_k) or DEFAULT_TOP_K)
	index_dir = get_code_index_storage_path()
	if not _has_persisted_index(index_dir):
		if _read_sync_state():
			return _("Code index build is still in progress. Try again once the background sync completes.")
		return _("Code index is not available yet. The background sync has not completed.")

	try:
		retrieved = _retrieve_code_nodes(query=query, top_k=top_k_value, index_dir=index_dir)
	except Exception:
		frappe.log_error(title="Ask ALYF Code Search Error")
		return _("Code search failed while querying the index.")

	if not retrieved:
		return _("No matching code snippets were found.")

	return _format_retrieved_nodes(retrieved)


def _scan_installed_code_files() -> dict[str, dict[str, Any]]:
	"""Collect metadata for indexable files across installed Frappe apps."""
	bench_path = Path(get_bench_path()).resolve()
	apps_root = bench_path / "apps"
	files: dict[str, dict[str, Any]] = {}

	for app_name in frappe.get_installed_apps():
		app_root = (apps_root / app_name).resolve()
		if not app_root.exists():
			try:
				app_root = Path(frappe.get_app_path(app_name)).resolve().parent
			except Exception:
				continue

		if not app_root.exists():
			continue

		find_gitignored = _get_gitignored_path_checker(app_name)
		for dirpath, dirnames, filenames in os.walk(app_root):
			current_dir = Path(dirpath)

			candidates = [d for d in dirnames if not d.startswith((".", "_"))]
			if candidates:
				candidate_paths = [str(current_dir / d) for d in candidates]
				ignored = find_gitignored(candidate_paths)
				candidates = [d for d, p in zip(candidates, candidate_paths, strict=True) if p not in ignored]
			dirnames[:] = candidates

			for filename in filenames:
				if filename.startswith("."):
					continue

				file_path = current_dir / filename
				if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS or not file_path.is_file():
					continue

				try:
					stat = file_path.stat()
				except OSError:
					continue

				if stat.st_size > MAX_FILE_SIZE:
					continue

				relative_path = _to_relative_path(file_path, bench_path)
				files[relative_path] = {
					"absolute_path": str(file_path),
					"app_name": app_name,
					"mtime_ns": int(stat.st_mtime_ns),
					"size": int(stat.st_size),
				}

	return files


def _get_embed_model() -> AnyLLMEmbedding:
	"""Build the embedding model from Ask ALYF Settings."""
	settings = frappe.get_single("Ask ALYF Settings")
	if not settings.allow_code_search:
		frappe.throw(_("Enable code search in Ask ALYF Settings before using code search."))

	api_key = (settings.get_password("api_key", raise_exception=False) or "").strip()
	if not api_key:
		frappe.throw(_("Configure an API key in Ask ALYF Settings before using code search."))

	base_url = (settings.base_url or "").strip() or None
	if settings.llm_provider == "OpenAI Compatible" and not base_url:
		frappe.throw(_("Configure a Base URL in Ask ALYF Settings before using code search."))

	provider = get_any_llm_provider(settings.llm_provider)
	provider_metadata = AnyLLM.get_provider_class(provider).get_provider_metadata()
	if not provider_metadata.embedding:
		frappe.throw(_("The configured provider does not support embeddings for code search."))

	model_name = _strip_provider_prefix(settings.embedding_model or "")
	if not model_name:
		frappe.throw(_("Configure an embedding model in Ask ALYF Settings before using code search."))

	return AnyLLMEmbedding(model_name=model_name, provider=provider, api_key=api_key, api_base=base_url)


def _is_code_search_enabled() -> bool:
	"""Return whether semantic code search is enabled in settings."""
	try:
		return bool(frappe.get_single("Ask ALYF Settings").allow_code_search)
	except Exception:
		return False


def _strip_provider_prefix(model_name: str) -> str:
	"""Normalize provider-prefixed model IDs to their raw model name."""
	model_name = (model_name or "").strip()
	if not model_name:
		return ""

	try:
		_, parsed_model_name = AnyLLM.split_model_provider(model_name)
	except ValueError:
		return model_name

	return parsed_model_name.strip()


def _to_relative_path(file_path: Path, bench_path: Path) -> str:
	"""Return a bench-relative path string, falling back to absolute path."""
	try:
		return str(file_path.resolve().relative_to(bench_path))
	except ValueError:
		return str(file_path.resolve())


def _get_gitignored_path_checker(app_name: str):
	"""Return a callable that identifies gitignored paths from a batch.

	The returned function accepts a list of directory paths and returns the
	subset that is gitignored, using a single ``git check-ignore`` subprocess
	call instead of one per path.
	"""
	try:
		import git
	except ImportError:
		return _find_fallback_ignored_paths

	try:
		repo = git.Repo(frappe.get_app_source_path(app_name), search_parent_directories=True)
	except Exception:
		return lambda paths: set()

	def _find_ignored(paths: list[str]) -> set[str]:
		if not paths:
			return set()
		try:
			return set(repo.ignored(*paths))
		except Exception:
			return set()

	return _find_ignored


def _find_fallback_ignored_paths(paths: list[str]) -> set[str]:
	"""Match a small set of commonly ignored directories without GitPython."""
	ignored_paths: set[str] = set()
	for path in paths:
		path_parts = Path(path).parts
		if any(part in FALLBACK_IGNORED_DIRECTORY_NAMES for part in path_parts):
			ignored_paths.add(path)
			continue

		for parent, child in pairwise(path_parts):
			if parent == "public" and child == "dist":
				ignored_paths.add(path)
				break

	return ignored_paths


def _read_manifest(index_dir: Path) -> dict[str, dict[str, Any]]:
	"""Read the incremental index manifest from disk."""
	manifest_path = index_dir / MANIFEST_FILE_NAME
	if not manifest_path.exists():
		return {}

	try:
		payload = json.loads(manifest_path.read_text(encoding="utf-8"))
	except Exception:
		return {}

	files = payload.get("files")
	if not isinstance(files, dict):
		return {}

	parsed: dict[str, dict[str, Any]] = {}
	for path, metadata in files.items():
		if not isinstance(path, str) or not isinstance(metadata, dict):
			continue

		parsed[path] = {
			"app_name": metadata.get("app_name") or "",
			"mtime_ns": int(metadata.get("mtime_ns") or 0),
			"size": int(metadata.get("size") or 0),
		}

	return parsed


def _write_manifest(index_dir: Path, current_files: dict[str, dict[str, Any]]):
	"""Write the incremental index manifest to disk."""
	manifest_path = index_dir / MANIFEST_FILE_NAME
	files = {
		path: {
			"app_name": metadata.get("app_name") or "",
			"mtime_ns": int(metadata.get("mtime_ns") or 0),
			"size": int(metadata.get("size") or 0),
		}
		for path, metadata in sorted(current_files.items())
	}
	payload = {
		"version": 1,
		"site": frappe.local.site,
		"files": files,
	}
	manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _calculate_deltas(
	current_files: dict[str, dict[str, Any]],
	previous_manifest: dict[str, dict[str, Any]],
) -> tuple[list[str], list[str]]:
	"""Return changed and removed paths by comparing manifest metadata."""
	changed_paths: list[str] = []
	for relative_path, metadata in current_files.items():
		previous = previous_manifest.get(relative_path)
		if not previous:
			changed_paths.append(relative_path)
			continue

		if int(previous.get("mtime_ns") or 0) != int(metadata.get("mtime_ns") or 0) or int(
			previous.get("size") or 0
		) != int(metadata.get("size") or 0):
			changed_paths.append(relative_path)

	removed_paths = [
		relative_path for relative_path in previous_manifest if relative_path not in current_files
	]
	return sorted(changed_paths), sorted(removed_paths)


def _load_documents(
	changed_paths: list[str],
	current_files: dict[str, dict[str, Any]],
) -> tuple[list[Any], list[dict[str, str]]]:
	"""Load changed files into documents and collect per-file read failures."""
	documents: list[Any] = []
	failures: list[dict[str, str]] = []
	for relative_path in changed_paths:
		metadata = current_files.get(relative_path)
		if not metadata:
			continue

		absolute_path = metadata.get("absolute_path")
		if not isinstance(absolute_path, str) or not absolute_path:
			continue

		reader = SimpleDirectoryReader(input_files=[absolute_path])
		try:
			loaded_documents = reader.load_data()
		except Exception as error:
			failures.append({"path": relative_path, "error": str(error).strip() or "unknown error"})
			continue

		for document in loaded_documents:
			try:
				document.doc_id = relative_path
			except Exception:
				pass
			try:
				document.id_ = relative_path
			except Exception:
				pass
			document_metadata = document.metadata if isinstance(document.metadata, dict) else {}
			document_metadata["app_name"] = metadata.get("app_name") or _infer_app_name(relative_path)
			document_metadata["file_path"] = relative_path
			document.metadata = document_metadata
			documents.append(document)

	return documents, failures


def _refresh_index(index: Any, documents: list[Any]):
	"""Refresh indexed documents, with insert fallback for older APIs."""
	if not documents:
		return

	if hasattr(index, "refresh_ref_docs"):
		try:
			index.refresh_ref_docs(documents)
			return
		except Exception:
			frappe.logger("ask_alyf").warning(
				"refresh_ref_docs failed, falling back to manual insert", exc_info=True
			)

	for document in documents:
		doc_id = getattr(document, "doc_id", "")
		if isinstance(doc_id, str) and doc_id:
			_delete_ref_doc(index, doc_id)
		index.insert(document)


def _delete_ref_doc(index: Any, ref_doc_id: str):
	"""Delete a reference document from the index when supported."""
	if not ref_doc_id or not hasattr(index, "delete_ref_doc"):
		return

	try:
		index.delete_ref_doc(ref_doc_id, delete_from_docstore=True)
	except TypeError:
		index.delete_ref_doc(ref_doc_id)


def _get_index_sentinel_paths(index_dir: Path) -> list[Path]:
	"""Return the persisted files that indicate a usable on-disk index."""
	return [
		*(index_dir / file_name for file_name in INDEX_SENTINEL_FILES),
		*sorted(index_dir.glob("*vector_store.json")),
	]


def _has_persisted_index(index_dir: Path) -> bool:
	"""Return whether persisted index sentinel files are present."""
	return any(path.exists() for path in _get_index_sentinel_paths(index_dir))


def _clear_index_directory(index_dir: Path):
	"""Remove all persisted index files for a clean rebuild."""
	if index_dir.exists():
		shutil.rmtree(index_dir, ignore_errors=True)


def _format_retrieved_nodes(retrieved_nodes: list[Any]) -> str:
	"""Format retrieved nodes into a prompt-ready string with metadata."""
	formatted_results: list[str] = []
	for position, result in enumerate(retrieved_nodes, start=1):
		node = getattr(result, "node", result)
		metadata = getattr(node, "metadata", {}) or {}
		file_path = str(metadata.get("file_path") or metadata.get("file_name") or "unknown")
		app_name = str(metadata.get("app_name") or _infer_app_name(file_path))
		content = _extract_node_content(node)
		if not content:
			content = "# snippet content unavailable"
		if len(content) > MAX_NODE_CONTENT_CHARS:
			content = content[:MAX_NODE_CONTENT_CHARS].rstrip() + "\n... [truncated]"

		language = _detect_language(file_path)
		formatted_results.append(
			f"Result {position}\nApp: {app_name}\nPath: {file_path}\nCode:\n```{language}\n{content}\n```"
		)

	return "\n\n".join(formatted_results)


def _extract_node_content(node: Any) -> str:
	"""Extract normalized text content from a retrieved node object."""
	text = getattr(node, "text", None)
	if isinstance(text, str) and text.strip():
		return text.strip()

	if hasattr(node, "get_content"):
		try:
			return str(node.get_content()).strip()
		except Exception:
			return ""

	return ""


def _infer_app_name(file_path: str) -> str:
	"""Infer an app name from a bench-style path."""
	parts = Path(file_path).parts
	if "apps" in parts:
		app_index = parts.index("apps") + 1
		if app_index < len(parts):
			return parts[app_index]

	return "unknown"


def _detect_language(file_path: str) -> str:
	"""Map file extension to markdown code-fence language."""
	return EXTENSION_LANGUAGE_MAP.get(Path(file_path).suffix.lower(), "text")


def _get_index_mtime(index_dir: Path) -> float:
	"""Return the newest mtime across sentinel files for cache invalidation."""
	max_mtime = 0.0
	for sentinel in _get_index_sentinel_paths(index_dir):
		try:
			max_mtime = max(max_mtime, sentinel.stat().st_mtime)
		except OSError:
			pass
	return max_mtime


@site_cache(maxsize=5)
def _load_index(index_dir: str, _mtime: float):
	"""Deserialize the persisted index; cached per site until mtime changes."""
	storage_context = StorageContext.from_defaults(persist_dir=index_dir)
	return load_index_from_storage(storage_context, embed_model=_get_embed_model())


def _retrieve_code_nodes(query: str, top_k: int, index_dir: Path) -> list[Any]:
	"""Return top-k retrieved nodes, using the cached deserialized index."""
	mtime = _get_index_mtime(index_dir)
	index = _load_index(str(index_dir), mtime)
	retriever = index.as_retriever(similarity_top_k=top_k)
	return retriever.retrieve(query)


def _format_document_load_failures(load_failures: list[dict[str, str]]) -> str:
	"""Render a capped, human-readable summary of document load failures."""
	max_items = 50
	lines = ["Some files could not be indexed."]
	for item in load_failures[:max_items]:
		path = item.get("path") or "unknown"
		error = item.get("error") or "unknown error"
		lines.append(f"- {path}: {error}")

	remaining = len(load_failures) - max_items
	if remaining > 0:
		lines.append(f"... and {remaining} more")

	return "\n".join(lines)
