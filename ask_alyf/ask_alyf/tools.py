from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import frappe
from frappe import _, client
from frappe.utils import get_bench_path
from frappe.utils.data import cint

CODE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".json", ".yml", ".yaml", ".toml"}
READ_ONLY_SQL_RE = re.compile(r"^\s*(with|select|show|explain|describe|desc)\b", re.IGNORECASE)
FORBIDDEN_SQL_RE = re.compile(
	r"\b(insert|update|delete|drop|truncate|alter|create|grant|revoke|replace)\b", re.IGNORECASE
)
ENGLISH_LANGUAGE_CODES = {"en", "en-us", "en-gb"}


def coerce_int(value: Any, default: int, *, minimum: int | None = None) -> int:
	coerced = cint(value)
	if value not in {0, "0"} and not coerced:
		coerced = default

	if minimum is not None:
		coerced = max(minimum, coerced)

	return coerced


def get_settings():
	return frappe.get_single("Ask ALYF Settings")


def get_excluded_doctypes() -> set[str]:
	settings = get_settings()

	parsed_doctypes: set[str] = set()
	for row in settings.excluded_doctypes or []:
		doctype = (row.excluded_doctype or "").strip()

		if doctype:
			parsed_doctypes.add(doctype)

	return parsed_doctypes


def ensure_editable_doctype(doctype: str):
	if doctype in get_excluded_doctypes():
		frappe.throw(_("DocType '{0}' is excluded from Agent mode.").format(doctype))


def get_list(
	doctype: str,
	fields: list[str] | None = None,
	filters: dict[str, Any] | list | None = None,
	order_by: str | None = None,
	limit: int = 20,
	group_by: str | None = None,
) -> list[dict[str, Any]]:
	limit = coerce_int(limit, 20, minimum=1)
	return client.get_list(
		doctype=doctype,
		fields=fields,
		filters=filters,
		order_by=order_by,
		limit_page_length=limit,
		group_by=group_by,
	)


def get_count(doctype: str, filters: dict[str, Any] | list | None = None) -> int:
	return client.get_count(doctype=doctype, filters=filters)


def get_document(
	doctype: str, name: str | None = None, filters: dict[str, Any] | None = None
) -> dict[str, Any]:
	return client.get(doctype=doctype, name=name, filters=filters)


def get_value(
	doctype: str,
	fieldname: str | list[str],
	filters: dict[str, Any] | list | str | None = None,
) -> Any:
	return client.get_value(doctype=doctype, fieldname=fieldname, filters=filters)


def get_single_value(doctype: str, field: str) -> Any:
	return client.get_single_value(doctype=doctype, field=field)


def get_meta(doctype: str) -> dict[str, Any]:
	meta = frappe.get_meta(doctype)
	fields = []
	for df in meta.fields:
		fields.append(
			{
				"fieldname": df.fieldname,
				"label": df.label,
				"fieldtype": df.fieldtype,
				"options": df.options,
				"reqd": df.reqd,
				"read_only": df.read_only,
			}
		)

	return {
		"name": meta.name,
		"module": meta.module,
		"issingle": meta.issingle,
		"istable": meta.istable,
		"is_submittable": meta.is_submittable,
		"title_field": meta.title_field,
		"fields": fields,
		"permissions": [perm.as_dict() for perm in meta.permissions],
	}


def has_permission(doctype: str, docname: str, perm_type: str = "read") -> dict[str, bool]:
	return client.has_permission(doctype=doctype, docname=docname, perm_type=perm_type)


def get_doc_permissions(doctype: str, docname: str) -> dict[str, Any]:
	return client.get_doc_permissions(doctype=doctype, docname=docname)


def list_accessible_doctypes(permission_type: str = "read") -> list[str]:
	doctypes = frappe.get_all("DocType", filters={"istable": 0}, pluck="name")
	return [
		doctype
		for doctype in doctypes
		if frappe.has_permission(doctype, ptype=permission_type, user=frappe.session.user)
	]


def list_accessible_reports() -> list[dict[str, Any]]:
	reports = frappe.get_all(
		"Report",
		fields=["name", "ref_doctype", "report_type", "module"],
		filters={"disabled": 0},
		order_by="modified desc",
	)
	allowed = []
	for report in reports:
		if report.ref_doctype and frappe.has_permission(report.ref_doctype, ptype="report"):
			allowed.append(report)
	return allowed


def get_current_user_roles() -> list[str]:
	return frappe.get_roles()


def get_language_candidates(language: str | None) -> list[str]:
	lang_value = (language or "").strip()
	if not lang_value:
		lang_value = (getattr(frappe.local, "lang", "") or "").strip() or "en"

	normalized = lang_value.replace("_", "-")
	candidates: list[str] = []
	for candidate in (normalized, normalized.lower()):
		if candidate and candidate not in candidates:
			candidates.append(candidate)

	if "-" in normalized:
		base_lang = normalized.split("-", 1)[0].lower()
		if base_lang and base_lang not in candidates:
			candidates.append(base_lang)

	return candidates or ["en"]


def translate_ui_labels(labels: list[str] | str, language: str | None = None) -> dict[str, Any]:
	if isinstance(labels, str):
		labels = [labels]
	elif not isinstance(labels, list):
		frappe.throw(_("Labels must be provided as a list of strings."))

	cleaned_labels: list[str] = []
	for label in labels:
		if not isinstance(label, str):
			frappe.throw(_("Each label must be a string."))
		label = label.strip()
		if label:
			cleaned_labels.append(label)

	if not cleaned_labels:
		frappe.throw(_("Provide at least one label to translate."))

	candidates = get_language_candidates(language)
	resolved_language = candidates[0]
	translations: dict[str, str] = {}

	for label in dict.fromkeys(cleaned_labels):
		translated_label = frappe._(label, lang=resolved_language)
		if translated_label == label:
			for candidate in candidates[1:]:
				candidate_translation = frappe._(label, lang=candidate)
				if candidate_translation != label:
					translated_label = candidate_translation
					break

		translations[label] = translated_label

	return {
		"language": resolved_language,
		"is_english": resolved_language.lower() in ENGLISH_LANGUAGE_CODES,
		"translations": translations,
	}


def search_code(query: str, relative_path: str = "", limit: int = 20) -> list[dict[str, Any]]:
	limit = coerce_int(limit, 20, minimum=1)
	apps_path = Path(get_bench_path()) / "apps"
	search_root = (apps_path / relative_path).resolve() if relative_path else apps_path.resolve()

	if apps_path.resolve() not in [search_root, *search_root.parents]:
		frappe.throw(_("Code search is restricted to the apps directory."))

	query_lower = query.lower()
	results = []

	for file_path in search_root.rglob("*"):
		if not file_path.is_file() or file_path.suffix.lower() not in CODE_EXTENSIONS:
			continue

		try:
			lines = file_path.read_text(encoding="utf-8").splitlines()
		except Exception:
			continue

		for index, line in enumerate(lines, start=1):
			if query_lower in line.lower():
				results.append(
					{
						"path": str(file_path.relative_to(apps_path.parent)),
						"line": index,
						"snippet": line.strip(),
					}
				)
				if len(results) >= limit:
					return results

	return results


def read_code_file(path: str, start_line: int = 1, end_line: int = 200) -> dict[str, Any]:
	start_line = coerce_int(start_line, 1, minimum=1)
	end_line = coerce_int(end_line, 200, minimum=1)
	bench_path = Path(get_bench_path()).resolve()
	target = (bench_path / path).resolve()

	if bench_path not in [target, *target.parents]:
		frappe.throw(_("Code reads are restricted to the bench directory."))

	lines = target.read_text(encoding="utf-8").splitlines()
	start = max(1, start_line)
	stop = min(len(lines), end_line)
	content = []
	for line_number in range(start, stop + 1):
		content.append(f"{line_number}: {lines[line_number - 1]}")

	return {"path": path, "content": "\n".join(content), "start_line": start, "end_line": stop}


def read_file_record(file_url: str | None = None, file_name: str | None = None) -> dict[str, Any]:
	filters = {"file_url": file_url} if file_url else {"file_name": file_name}
	file_doc = frappe.get_doc("File", filters)
	file_doc.check_permission("read")
	content = file_doc.get_content()
	if isinstance(content, bytes):
		content = content.decode("utf-8", errors="replace")
	return {"file_name": file_doc.file_name, "file_url": file_doc.file_url, "content": content}


def run_read_only_sql(query: str) -> list[dict[str, Any]]:
	roles = set(frappe.get_roles())
	if frappe.session.user != "Administrator" and "System Manager" not in roles:
		frappe.throw(_("Only Administrator and System Manager can run SQL queries."))

	if ";" in query.strip().rstrip(";"):
		frappe.throw(_("Only a single read-only SQL statement is allowed."))

	if not READ_ONLY_SQL_RE.match(query) or FORBIDDEN_SQL_RE.search(query):
		frappe.throw(_("Only read-only SQL statements are allowed."))

	return frappe.db.sql(query, as_dict=True)


def get_app_version(app_name: str) -> str:
	app_name = (app_name or "").strip()
	if not app_name:
		frappe.throw(_("App name is required."))

	if app_name not in frappe.get_installed_apps():
		frappe.throw(_("App '{0}' is not installed.").format(app_name))

	version = ""
	try:
		module_version = frappe.get_attr(f"{app_name}.__version__")
		if isinstance(module_version, str):
			version = module_version.strip()
	except Exception:
		version = ""

	if not version:
		project_data = get_app_pyproject_data(app_name)
		project_version = project_data.get("project", {}).get("version")
		if isinstance(project_version, str):
			version = project_version.strip()

	if not version:
		frappe.throw(_("No version was found for app '{0}'.").format(app_name))

	return version


def read_github_releases(app_name: str, limit: int = 5) -> list[dict[str, Any]]:
	limit = coerce_int(limit, 5, minimum=1)
	urls = get_project_urls(app_name)
	repository_url = urls.get("repository")
	if not repository_url:
		frappe.throw(_("No repository URL was found for app '{0}'.").format(app_name))

	parsed = urlparse(repository_url)
	parts = [part for part in parsed.path.split("/") if part]
	if parsed.netloc not in {"github.com", "www.github.com"} or len(parts) < 2:
		frappe.throw(_("Only GitHub repositories are supported for release lookup."))

	owner, repo = parts[0], parts[1].removesuffix(".git")
	api_url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page={limit}"
	request = Request(api_url, headers={"Accept": "application/vnd.github+json", "User-Agent": "ask_alyf"})
	with urlopen(request, timeout=10) as response:
		payload = json.loads(response.read().decode("utf-8"))

	return [
		{
			"name": item.get("name") or item.get("tag_name"),
			"tag_name": item.get("tag_name"),
			"published_at": item.get("published_at"),
			"url": item.get("html_url"),
			"body": item.get("body", "")[:4000],
		}
		for item in payload
	]


def read_documentation_page(app_name: str, relative_path: str = "") -> dict[str, Any]:
	urls = get_project_urls(app_name)
	base_url = urls.get("documentation")
	if not base_url:
		frappe.throw(_("No documentation URL was found for app '{0}'.").format(app_name))

	if relative_path:
		target_url = base_url.rstrip("/") + "/" + relative_path.lstrip("/")
	else:
		target_url = base_url

	request = Request(target_url, headers={"User-Agent": "ask_alyf"})
	with urlopen(request, timeout=10) as response:
		content = response.read().decode("utf-8", errors="replace")

	return {"url": target_url, "content": content[:20000]}


def get_app_pyproject_data(app_name: str) -> dict[str, Any]:
	pyproject_path = Path(get_bench_path()) / "apps" / app_name / "pyproject.toml"
	if not pyproject_path.exists():
		frappe.throw(_("No pyproject.toml was found for app '{0}'.").format(app_name))

	return tomllib.loads(pyproject_path.read_text(encoding="utf-8"))


def get_project_urls(app_name: str) -> dict[str, str]:
	data = get_app_pyproject_data(app_name)
	urls = data.get("project", {}).get("urls", {})
	return {key.lower(): value for key, value in urls.items()}


def execute_action(action: dict[str, Any]) -> dict[str, Any]:
	if not isinstance(action, dict):
		frappe.throw(_("Invalid action payload."))

	action_type = action.get("action")

	if action_type == "insert":
		doctype = action["doctype"]
		ensure_editable_doctype(doctype)
		values = coerce_object_payload(action.get("values"), "values")
		validation_error = validate_pending_action_payload("insert", {"doctype": doctype, "values": values})
		if validation_error:
			frappe.throw(validation_error)
		doc = {"doctype": doctype, **values}
		return client.insert(doc=doc)

	if action_type == "save":
		doctype = action["doctype"]
		ensure_editable_doctype(doctype)
		values = coerce_object_payload(action.get("values"), "values")
		validation_error = validate_pending_action_payload("save", {"doctype": doctype, "values": values})
		if validation_error:
			frappe.throw(validation_error)
		doc = client.get(doctype=doctype, name=action["name"])
		doc.update(values)
		return client.save(doc=doc)

	if action_type == "set_value":
		doctype = action["doctype"]
		ensure_editable_doctype(doctype)
		return client.set_value(
			doctype=doctype,
			name=action["name"],
			fieldname=action["fieldname"],
			value=action.get("value"),
		)

	if action_type == "submit":
		doctype = action["doctype"]
		ensure_editable_doctype(doctype)
		doc = client.get(doctype=doctype, name=action["name"])
		return client.submit(doc=doc)

	if action_type == "cancel":
		doctype = action["doctype"]
		ensure_editable_doctype(doctype)
		return client.cancel(doctype=doctype, name=action["name"])

	if action_type == "amend":
		doctype = action["doctype"]
		ensure_editable_doctype(doctype)
		doc = frappe.get_doc(doctype, action["name"])
		new_doc = frappe.copy_doc(doc)
		new_doc.amended_from = doc.name
		new_doc.insert()
		return new_doc.as_dict()

	if action_type == "delete":
		doctype = action["doctype"]
		ensure_editable_doctype(doctype)
		client.delete(doctype=doctype, name=action["name"])
		return {"message": _("Deleted {0} {1}").format(doctype, action["name"])}

	if action_type == "rename_doc":
		doctype = action["doctype"]
		ensure_editable_doctype(doctype)
		new_name = client.rename_doc(
			doctype=doctype,
			old_name=action["name"],
			new_name=action["new_name"],
			merge=bool(action.get("merge")),
		)
		return {"new_name": new_name}

	if action_type == "attach_file":
		doctype = action["doctype"]
		ensure_editable_doctype(doctype)
		file_doc = frappe.get_doc("File", {"file_url": action["file_url"]})
		file_doc.check_permission("read")
		attached = frappe.get_doc(
			{
				"doctype": "File",
				"file_url": file_doc.file_url,
				"file_name": file_doc.file_name,
				"is_private": file_doc.is_private,
				"attached_to_doctype": doctype,
				"attached_to_name": action["name"],
			}
		)
		attached.insert()
		return attached.as_dict()

	if action_type == "run_method":
		method_path = action["method"]
		method = frappe.get_attr(method_path)
		frappe.is_whitelisted(method)
		return frappe.call(method, **coerce_object_payload(action.get("args"), "args"))

	frappe.throw(_("Unsupported action '{0}'.").format(action_type))


def coerce_object_payload(value: Any, fieldname: str) -> dict[str, Any]:
	if value in (None, ""):
		return {}

	if isinstance(value, dict):
		return value

	if isinstance(value, str):
		try:
			parsed = json.loads(value)
		except Exception:
			parsed = None
		if isinstance(parsed, dict):
			return parsed

	frappe.throw(_("Action field '{0}' must be an object.").format(fieldname))


def validate_pending_action_payload(action_type: str, payload: dict[str, Any]) -> str | None:
	if action_type in {"insert", "save"}:
		doctype = payload.get("doctype")
		if not isinstance(doctype, str) or not doctype.strip():
			return _("Action field 'doctype' is required.")

		values = payload.get("values")
		if not isinstance(values, dict):
			return _("Action field 'values' must be an object.")

		return validate_table_field_shapes(doctype, values)

	if action_type == "run_method":
		args = payload.get("args")
		if args is not None and not isinstance(args, dict):
			return _("Action field 'args' must be an object.")

	return None


def validate_table_field_shapes(doctype: str, values: dict[str, Any]) -> str | None:
	meta = frappe.get_meta(doctype)
	table_fields = {
		df.fieldname: df.options
		for df in meta.fields
		if df.fieldtype == "Table" and df.fieldname and df.options
	}
	if not table_fields:
		return None

	for fieldname, child_doctype in table_fields.items():
		if fieldname not in values:
			continue

		field_value = values.get(fieldname)
		if field_value in (None, ""):
			continue

		if not isinstance(field_value, list):
			return _("Field '{0}' in {1} is a child table ({2}) and must be a list of row objects.").format(
				fieldname, doctype, child_doctype
			)

		for index, row in enumerate(field_value, start=1):
			if not isinstance(row, dict):
				return _("Field '{0}' row #{1} in {2} must be an object.").format(fieldname, index, doctype)

	return None
