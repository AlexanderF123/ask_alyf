from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import frappe
from any_agent import AgentConfig, AgentFramework, AnyAgent
from any_llm import AnyLLM
from frappe import _

from ask_alyf.ask_alyf import tools


@dataclass
class ask_alyfRuntime:
	conversation_name: str
	user: str
	mode: str
	request_context: dict[str, Any]
	pending_operation: dict[str, Any] | None = None

	def emit_status(self, text: str):
		frappe.publish_realtime(
			"ask_alyf_status",
			{"conversation": self.conversation_name, "text": text},
			user=self.user,
		)


class ask_alyfToolset:
	def __init__(self, runtime: ask_alyfRuntime):
		self.runtime = runtime

	def _proposal(
		self,
		kind: str,
		tool: str,
		summary: str,
		reason: str = "",
		*,
		validation_error_status: str,
		prepared_status: str,
		requires_confirmation: bool = True,
		**payload: Any,
	) -> dict[str, Any]:
		"""Create a pending operation proposal."""
		validation_error = tools.validate_pending_operation_payload(kind, tool, payload)
		if validation_error:
			self.runtime.emit_status(validation_error_status)
			return {
				"success": False,
				"requires_confirmation": False,
				"error": validation_error,
			}

		proposal = {
			"kind": kind,
			"tool": tool,
			"summary": summary,
			"reason": reason,
			"requires_confirmation": bool(requires_confirmation),
			"payload": payload,
			"call_id": uuid4().hex,
		}
		self.runtime.pending_operation = proposal
		self.runtime.emit_status(prepared_status)
		return {
			"success": True,
			"requires_confirmation": bool(requires_confirmation),
			"proposal": proposal,
		}

	def _backend_proposal(
		self,
		tool: str,
		summary: str,
		reason: str = "",
		*,
		validation_error_status: str,
		prepared_status: str,
		**payload: Any,
	) -> dict[str, Any]:
		return self._proposal(
			tools.OPERATION_KIND_BACKEND,
			tool,
			summary,
			reason,
			validation_error_status=validation_error_status,
			prepared_status=prepared_status,
			requires_confirmation=True,
			**payload,
		)

	def _frontend_proposal(
		self,
		tool: str,
		summary: str,
		reason: str = "",
		*,
		validation_error_status: str,
		prepared_status: str,
		requires_confirmation: bool | None = None,
		**payload: Any,
	) -> dict[str, Any]:
		if requires_confirmation is None:
			requires_confirmation = tools.get_frontend_action_requires_confirmation(tool)
		return self._proposal(
			tools.OPERATION_KIND_FRONTEND,
			tool,
			summary,
			reason,
			validation_error_status=validation_error_status,
			prepared_status=prepared_status,
			requires_confirmation=requires_confirmation,
			**payload,
		)

	def get_list(
		self,
		doctype: str,
		fields: list[str] | None = None,
		filters: dict[str, Any] | list[Any] | None = None,
		order_by: str | None = None,
		limit: int = 20,
		group_by: str | None = None,
	) -> list[dict[str, Any]]:
		"""List documents with filters, fields, ordering, and optional grouping.

		Args:
			doctype: The DocType to query.
			fields: Optional fields to return.
			filters: Optional Frappe filters.
			order_by: Optional ordering expression.
			limit: Maximum number of rows to return.
			group_by: Optional SQL group by expression.

		Returns:
			A list of matching documents.
		"""
		self.runtime.emit_status(_("Fetching list..."))
		return tools.get_list(
			doctype=doctype,
			fields=fields,
			filters=filters,
			order_by=order_by,
			limit=limit,
			group_by=group_by,
		)

	def get_count(
		self,
		doctype: str,
		filters: dict[str, Any] | list[Any] | None = None,
	) -> int:
		"""Count documents that match the given filters.

		Args:
			doctype: The DocType to query.
			filters: Optional Frappe filters.

		Returns:
			The number of matching documents.
		"""
		self.runtime.emit_status(_("Counting documents..."))
		return tools.get_count(doctype=doctype, filters=filters)

	def get(
		self,
		doctype: str,
		name: str | None = None,
		filters: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		"""Read a single document by name or filters.

		Args:
			doctype: The DocType to query.
			name: Optional document name.
			filters: Optional filters when name is not known.

		Returns:
			The matching document.
		"""
		self.runtime.emit_status(_("Fetching document..."))
		return tools.get_document(doctype=doctype, name=name, filters=filters)

	def get_value(
		self,
		doctype: str,
		fieldname: str | list[str],
		filters: dict[str, Any] | list[Any] | str | None = None,
	) -> Any:
		"""Read one or more field values from a document.

		Args:
			doctype: The DocType to query.
			fieldname: One field name or a list of field names.
			filters: Name or filters to identify the record.

		Returns:
			The requested value or values.
		"""
		self.runtime.emit_status(_("Fetching value..."))
		return tools.get_value(doctype=doctype, fieldname=fieldname, filters=filters)

	def get_single_value(self, doctype: str, field: str) -> Any:
		"""Read a field value from a Single DocType.

		Args:
			doctype: The Single DocType to query.
			field: The field name to read.

		Returns:
			The field value.
		"""
		self.runtime.emit_status(_("Fetching single value..."))
		return tools.get_single_value(doctype=doctype, field=field)

	def get_meta(self, doctype: str) -> dict[str, Any]:
		"""Inspect metadata, fields, and permissions for a DocType.

		Args:
			doctype: The DocType to inspect.

		Returns:
			A metadata dictionary for the DocType.
		"""
		self.runtime.emit_status(_("Loading metadata..."))
		return tools.get_meta(doctype=doctype)

	def has_permission(self, doctype: str, docname: str, perm_type: str = "read") -> dict[str, bool]:
		"""Check whether the current user has a specific permission on a document.

		Args:
			doctype: The DocType to check.
			docname: The document name.
			perm_type: The permission type to evaluate.

		Returns:
			A dictionary containing the boolean permission result.
		"""
		self.runtime.emit_status(_("Checking permissions..."))
		return tools.has_permission(doctype=doctype, docname=docname, perm_type=perm_type)

	def get_doc_permissions(self, doctype: str, docname: str) -> dict[str, Any]:
		"""Get the evaluated permission map for a document.

		Args:
			doctype: The DocType to check.
			docname: The document name.

		Returns:
			The evaluated permission dictionary.
		"""
		self.runtime.emit_status(_("Evaluating permissions..."))
		return tools.get_doc_permissions(doctype=doctype, docname=docname)

	def list_accessible_doctypes(self, permission_type: str = "read") -> list[str]:
		"""List DocTypes that the current user can access.

		Args:
			permission_type: The permission type to test.

		Returns:
			A list of DocType names.
		"""
		self.runtime.emit_status(_("Listing accessible DocTypes..."))
		return tools.list_accessible_doctypes(permission_type=permission_type)

	def list_accessible_reports(self) -> list[dict[str, Any]]:
		"""List reports that the current user can access.

		Returns:
			A list of report metadata dictionaries.
		"""
		self.runtime.emit_status(_("Listing accessible reports..."))
		return tools.list_accessible_reports()

	def get_current_user_roles(self) -> list[str]:
		"""List the current user's roles.

		Returns:
			A list of role names.
		"""
		return tools.get_current_user_roles()

	def translate_ui_labels(
		self,
		labels: list[str],
		language: str | None = None,
	) -> dict[str, Any]:
		"""Translate UI labels so responses match what the user sees on screen.

		Use this whenever request context language is not English before mentioning
		button names, tab names, DocType labels, field labels, menu items, or status labels.

		Args:
			labels: English UI labels to translate.
			language: Optional target language code (defaults to request context language).

		Returns:
			A dictionary with the resolved language and translated labels.
		"""
		self.runtime.emit_status(_("Translating UI labels..."))
		request_language = self.runtime.request_context.get("lang") or self.runtime.request_context.get(
			"locale"
		)
		return tools.translate_ui_labels(labels=labels, language=language or request_language)

	def search_code(self, query: str, relative_path: str = "", limit: int = 20) -> list[dict[str, Any]]:
		"""Search installed app code for matching text.

		Args:
			query: The text to search for.
			relative_path: Optional installed-app-relative path. Providing at least the app name will make it much faster.
			limit: Maximum number of matches to return.

		Returns:
			A list of code search matches.
		"""
		self.runtime.emit_status(_("Searching code..."))
		return tools.search_code(query=query, relative_path=relative_path, limit=limit)

	def read_code_file(self, path: str, start_line: int = 1, end_line: int = 200) -> dict[str, Any]:
		"""Read a file from installed app code.

		Args:
			path: Bench-relative path inside an installed app, such as apps/my_app/my_app/module.py.
			start_line: First line to include.
			end_line: Last line to include.

		Returns:
			The selected file content and line range.
		"""
		self.runtime.emit_status(_("Reading code file..."))
		return tools.read_code_file(path=path, start_line=start_line, end_line=end_line)

	def ls(
		self,
		app_name: str,
		relative_path: str = "",
		recursive: bool = False,
		include_hidden: bool = False,
		limit: int = 200,
	) -> dict[str, Any]:
		"""List files or directories in an installed app, similar to Debian ls.

		Args:
			app_name: The installed app name.
			relative_path: Optional path inside the app.
			recursive: Whether to include nested descendants.
			include_hidden: Whether to include hidden files and folders.
			limit: Maximum number of entries to return.

		Returns:
			A directory listing payload.
		"""
		self.runtime.emit_status(_("Listing code files..."))
		return tools.ls(
			app_name=app_name,
			relative_path=relative_path,
			recursive=recursive,
			include_hidden=include_hidden,
			limit=limit,
		)

	def find(
		self,
		app_name: str,
		name_pattern: str = "*",
		relative_path: str = "",
		entry_type: str = "any",
		include_hidden: bool = False,
		limit: int = 200,
	) -> dict[str, Any]:
		"""Find files or directories in an installed app, similar to Debian find.

		Args:
			app_name: The installed app name.
			name_pattern: Shell-style filename pattern, such as *.py.
			relative_path: Optional path inside the app to search from.
			entry_type: One of any, file, or directory.
			include_hidden: Whether to include hidden files and folders.
			limit: Maximum number of matches to return.

		Returns:
			A find-style search payload.
		"""
		self.runtime.emit_status(_("Finding code paths..."))
		return tools.find(
			app_name=app_name,
			name_pattern=name_pattern,
			relative_path=relative_path,
			entry_type=entry_type,
			include_hidden=include_hidden,
			limit=limit,
		)

	def grep(
		self,
		app_name: str,
		query: str,
		relative_path: str = "",
		file_pattern: str = "*",
		case_sensitive: bool = False,
		include_hidden: bool = False,
		limit: int = 50,
	) -> dict[str, Any]:
		"""Search file contents in an installed app, similar to Debian grep.

		Args:
			app_name: The installed app name.
			query: The text to search for.
			relative_path: Optional path inside the app to search from.
			file_pattern: Optional shell-style filename filter, such as *.py.
			case_sensitive: Whether matching should be case-sensitive.
			include_hidden: Whether to include hidden files and folders.
			limit: Maximum number of matches to return.

		Returns:
			A grep-style search payload.
		"""
		self.runtime.emit_status(_("Searching file contents..."))
		return tools.grep(
			app_name=app_name,
			query=query,
			relative_path=relative_path,
			file_pattern=file_pattern,
			case_sensitive=case_sensitive,
			include_hidden=include_hidden,
			limit=limit,
		)

	def read_file_record(self, file_url: str | None = None, file_name: str | None = None) -> dict[str, Any]:
		"""Read the content of a File record the user can access.

		Args:
			file_url: Optional file URL.
			file_name: Optional file name.

		Returns:
			The file metadata and content.
		"""
		self.runtime.emit_status(_("Reading file..."))
		return tools.read_file_record(file_url=file_url, file_name=file_name)

	def run_read_only_sql(self, query: str) -> list[dict[str, Any]]:
		"""Run a read-only SQL query when the current user is allowed to do so.

		Args:
			query: A single read-only SQL query.

		Returns:
			The SQL result rows.
		"""
		self.runtime.emit_status(_("Running SQL query..."))
		return tools.run_read_only_sql(query=query)

	def get_app_version(self, app_name: str) -> str:
		"""Read the installed version for an app.

		Args:
			app_name: The installed app name.

		Returns:
			The app version string.
		"""
		self.runtime.emit_status(_("Reading app version..."))
		return tools.get_app_version(app_name=app_name)

	def read_github_releases(self, app_name: str, limit: int = 5) -> list[dict[str, Any]]:
		"""Read recent GitHub releases for an installed app.

		Args:
			app_name: The installed app name.
			limit: Maximum number of releases to return.

		Returns:
			A list of release dictionaries.
		"""
		self.runtime.emit_status(_("Reading GitHub releases..."))
		return tools.read_github_releases(app_name=app_name, limit=limit)

	def read_documentation_page(self, app_name: str, relative_path: str = "") -> dict[str, Any]:
		"""Fetch a documentation page for an installed app.

		Args:
			app_name: The installed app name.
			relative_path: Optional path relative to the configured docs URL.

		Returns:
			A documentation payload containing the page content.
		"""
		self.runtime.emit_status(_("Reading documentation..."))
		return tools.read_documentation_page(app_name=app_name, relative_path=relative_path)

	def insert(self, doctype: str, values: dict[str, Any], reason: str = "") -> dict[str, Any]:
		"""Propose creating a new document. Use get_meta first to know the schema.
		For child tables, values must be a list of row objects.

		Args:
			doctype: The DocType to create.
			values: The field values for the new document.
			reason: Optional explanation of why this change is needed.

		Returns:
			A pending action proposal that requires confirmation.
		"""
		return self._backend_proposal(
			"insert",
			_("Create {0}").format(doctype),
			reason,
			validation_error_status=_("Create proposal needs correction."),
			prepared_status=_("Prepared create proposal."),
			doctype=doctype,
			values=values,
		)

	def save(
		self,
		doctype: str,
		name: str,
		values: dict[str, Any],
		reason: str = "",
	) -> dict[str, Any]:
		"""Propose updating an existing document.
		For child tables, values must be a list of row objects.

		Args:
			doctype: The DocType to update.
			name: The document name.
			values: The fields to update.
			reason: Optional explanation of why this change is needed.

		Returns:
			A pending action proposal that requires confirmation.
		"""
		return self._backend_proposal(
			"save",
			_("Update {0} {1}").format(doctype, name),
			reason,
			validation_error_status=_("Update proposal needs correction."),
			prepared_status=_("Prepared update proposal."),
			doctype=doctype,
			name=name,
			values=values,
		)

	def set_value(
		self,
		doctype: str,
		name: str,
		fieldname: str,
		value: Any,
		reason: str = "",
	) -> dict[str, Any]:
		"""Propose setting a single field on a document.

		Args:
			doctype: The DocType to update.
			name: The document name.
			fieldname: The field to set.
			value: The new value.
			reason: Optional explanation of why this change is needed.

		Returns:
			A pending action proposal that requires confirmation.
		"""
		return self._backend_proposal(
			"set_value",
			_("Set {0} on {1} {2}").format(fieldname, doctype, name),
			reason,
			validation_error_status=_("Set value proposal needs correction."),
			prepared_status=_("Prepared set value proposal."),
			doctype=doctype,
			name=name,
			fieldname=fieldname,
			value=value,
		)

	def submit(self, doctype: str, name: str, reason: str = "") -> dict[str, Any]:
		"""Propose submitting a document.

		Args:
			doctype: The DocType to submit.
			name: The document name.
			reason: Optional explanation of why this change is needed.

		Returns:
			A pending action proposal that requires confirmation.
		"""
		return self._backend_proposal(
			"submit",
			_("Submit {0} {1}").format(doctype, name),
			reason,
			validation_error_status=_("Submit proposal needs correction."),
			prepared_status=_("Prepared submit proposal."),
			doctype=doctype,
			name=name,
		)

	def cancel(self, doctype: str, name: str, reason: str = "") -> dict[str, Any]:
		"""Propose cancelling a document.

		Args:
			doctype: The DocType to cancel.
			name: The document name.
			reason: Optional explanation of why this change is needed.

		Returns:
			A pending action proposal that requires confirmation.
		"""
		return self._backend_proposal(
			"cancel",
			_("Cancel {0} {1}").format(doctype, name),
			reason,
			validation_error_status=_("Cancel proposal needs correction."),
			prepared_status=_("Prepared cancel proposal."),
			doctype=doctype,
			name=name,
		)

	def amend(self, doctype: str, name: str, reason: str = "") -> dict[str, Any]:
		"""Propose amending a cancelled document.

		Args:
			doctype: The DocType to amend.
			name: The document name.
			reason: Optional explanation of why this change is needed.

		Returns:
			A pending action proposal that requires confirmation.
		"""
		return self._backend_proposal(
			"amend",
			_("Amend {0} {1}").format(doctype, name),
			reason,
			validation_error_status=_("Amend proposal needs correction."),
			prepared_status=_("Prepared amend proposal."),
			doctype=doctype,
			name=name,
		)

	def delete(self, doctype: str, name: str, reason: str = "") -> dict[str, Any]:
		"""Propose deleting a document.

		Args:
			doctype: The DocType to delete.
			name: The document name.
			reason: Optional explanation of why this change is needed.

		Returns:
			A pending action proposal that requires confirmation.
		"""
		return self._backend_proposal(
			"delete",
			_("Delete {0} {1}").format(doctype, name),
			reason,
			validation_error_status=_("Delete proposal needs correction."),
			prepared_status=_("Prepared delete proposal."),
			doctype=doctype,
			name=name,
		)

	def rename_doc(
		self,
		doctype: str,
		name: str,
		new_name: str,
		merge: bool = False,
		reason: str = "",
	) -> dict[str, Any]:
		"""Propose renaming a document.

		Args:
			doctype: The DocType to rename.
			name: The current document name.
			new_name: The target document name.
			merge: Whether to merge into an existing target.
			reason: Optional explanation of why this change is needed.

		Returns:
			A pending action proposal that requires confirmation.
		"""
		return self._backend_proposal(
			"rename_doc",
			_("Rename {0} {1} to {2}").format(doctype, name, new_name),
			reason,
			validation_error_status=_("Rename proposal needs correction."),
			prepared_status=_("Prepared rename proposal."),
			doctype=doctype,
			name=name,
			new_name=new_name,
			merge=merge,
		)

	def attach_file(
		self,
		doctype: str,
		name: str,
		file_url: str,
		reason: str = "",
	) -> dict[str, Any]:
		"""Propose attaching an existing file to a document.

		Args:
			doctype: The DocType to update.
			name: The document name.
			file_url: The file URL to attach.
			reason: Optional explanation of why this change is needed.

		Returns:
			A pending action proposal that requires confirmation.
		"""
		return self._backend_proposal(
			"attach_file",
			_("Attach {0} to {1} {2}").format(file_url, doctype, name),
			reason,
			validation_error_status=_("Attach file proposal needs correction."),
			prepared_status=_("Prepared attach file proposal."),
			doctype=doctype,
			name=name,
			file_url=file_url,
		)

	def run_whitelisted_method(
		self,
		method: str,
		args: dict[str, Any] | None = None,
		reason: str = "",
	) -> dict[str, Any]:
		"""Propose calling a whitelisted method.

		Args:
			method: The dotted Python path of the whitelisted method.
			args: Optional keyword arguments for the method.
			reason: Optional explanation of why this change is needed.

		Returns:
			A pending action proposal that requires confirmation.
		"""
		return self._backend_proposal(
			"run_method",
			_("Call {0}").format(method),
			reason,
			validation_error_status=_("Method call proposal needs correction."),
			prepared_status=_("Prepared method call proposal."),
			method=method,
			args=args or {},
		)

	def set_route(self, route: list[str], reason: str = "") -> dict[str, Any]:
		"""Propose navigating to a Desk route on the frontend.

		Args:
			route: Route parts used by frappe.set_route.
			reason: Optional explanation of why this navigation helps the user.

		Returns:
			A pending frontend operation proposal.
		"""
		route_label = "/".join(part for part in (route or []) if isinstance(part, str))
		return self._frontend_proposal(
			"set_route",
			_("Navigate to {0}").format(route_label or _("target route")),
			reason,
			validation_error_status=_("Route action needs correction."),
			prepared_status=_("Prepared route action."),
			route=route,
		)

	def new_doc(
		self,
		doctype: str,
		route_options: dict[str, Any] | None = None,
		reason: str = "",
	) -> dict[str, Any]:
		"""Propose opening a new document form in the frontend.

		Args:
			doctype: The target DocType for frappe.new_doc.
			route_options: Optional route options to prefill form values.
			reason: Optional explanation of why this action helps the user.

		Returns:
			A pending frontend operation proposal.
		"""
		return self._frontend_proposal(
			"new_doc",
			_("Open new {0}").format(doctype),
			reason,
			validation_error_status=_("New document action needs correction."),
			prepared_status=_("Prepared new document action."),
			doctype=doctype,
			route_options=route_options or {},
		)

	def scroll_to_field(self, fieldname: str, reason: str = "") -> dict[str, Any]:
		"""Propose scrolling to a field on the active form.

		Args:
			fieldname: The fieldname to scroll to.
			reason: Optional explanation of why this action helps the user.

		Returns:
			A pending frontend operation proposal.
		"""
		return self._frontend_proposal(
			"scroll_to_field",
			_("Scroll to field {0}").format(fieldname),
			reason,
			validation_error_status=_("Scroll action needs correction."),
			prepared_status=_("Prepared scroll action."),
			fieldname=fieldname,
		)

	def frm_set_value(
		self,
		fieldname: str,
		value: Any,
		doctype: str | None = None,
		docname: str | None = None,
		reason: str = "",
	) -> dict[str, Any]:
		"""Propose setting a field value on the active frontend form.

		Args:
			fieldname: The target fieldname.
			value: The value to apply.
			doctype: Optional expected active form DocType.
			docname: Optional expected active form document name.
			reason: Optional explanation of why this action helps the user.

		Returns:
			A pending frontend operation proposal.
		"""
		payload: dict[str, Any] = {"fieldname": fieldname, "value": value}
		if doctype:
			payload["doctype"] = doctype
		if docname:
			payload["docname"] = docname

		return self._frontend_proposal(
			"frm_set_value",
			_("Set field {0} on current form").format(fieldname),
			reason,
			validation_error_status=_("Set field action needs correction."),
			prepared_status=_("Prepared set field action."),
			**payload,
		)

	def frm_add_child(
		self,
		fieldname: str,
		values: dict[str, Any] | None = None,
		doctype: str | None = None,
		docname: str | None = None,
		reason: str = "",
	) -> dict[str, Any]:
		"""Propose adding a child table row on the active frontend form.

		Args:
			fieldname: The child table fieldname.
			values: Optional row values for the new child row.
			doctype: Optional expected active form DocType.
			docname: Optional expected active form document name.
			reason: Optional explanation of why this action helps the user.

		Returns:
			A pending frontend operation proposal.
		"""
		payload: dict[str, Any] = {"fieldname": fieldname, "values": values or {}}
		if doctype:
			payload["doctype"] = doctype
		if docname:
			payload["docname"] = docname

		return self._frontend_proposal(
			"frm_add_child",
			_("Add a row to {0} on current form").format(fieldname),
			reason,
			validation_error_status=_("Add child row action needs correction."),
			prepared_status=_("Prepared add child row action."),
			**payload,
		)

	def show_chart(
		self,
		frappe_charts: list[dict[str, Any]],
		reason: str = "",
	) -> dict[str, Any]:
		"""Show one or more Frappe Charts under this assistant message.

		The desk creates the DOM element; each item in `frappe_charts` is the `options`
		argument to `new frappe.Chart(container, options)` (Frappe Charts on the client).

		Shape (one object per chart):
		- `type`: bar, line, scatter, pie, percentage, donut, or axis-mixed
		- `data`: `{ "labels": [...], "datasets": [ { "values": [...], "name"?: str, "type"?: "bar"|"line" } ] }`
		  — every `values` list must be the same length as `labels`
		- Optional: `title`, `height` (0 for default; if set, at least 240 — Frappe Charts reserves ~130px chrome),
		  `colors` (array; empty for defaults),
		  `barOptions`, `lineOptions`, `axisOptions` (see Frappe Charts docs)

		Args:
			frappe_charts: One or more chart option objects.
			reason: Optional short note for the user.

		Returns:
			A pending frontend operation proposal (auto-executed in the browser).
		"""
		count = len(frappe_charts) if isinstance(frappe_charts, list) else 0
		summary = _("Show chart") if count == 1 else _("Show {0} charts").format(count)
		return self._frontend_proposal(
			"show_chart",
			summary,
			reason,
			validation_error_status=_("Chart action needs correction."),
			prepared_status=_("Prepared chart display."),
			requires_confirmation=False,
			frappe_charts=frappe_charts,
		)


class ask_alyfAgentRunner:
	def __init__(self, runtime: ask_alyfRuntime):
		self.runtime = runtime
		self.settings = tools.get_settings()
		self.toolset = ask_alyfToolset(runtime)
		self.agent = AnyAgent.create(
			AgentFramework.TINYAGENT,
			AgentConfig(
				name="Ask ALYF",
				model_id=self._get_model_id(),
				api_base=(self.settings.base_url or "").strip() or None,
				api_key=self._get_api_key(),
				instructions=self._build_instructions(),
				tools=self._build_tools(),
				model_args={"temperature": 0.2},
			),
		)

	def _get_api_key(self) -> str:
		api_key = (self.settings.get_password("api_key", raise_exception=False) or "").strip()
		if not api_key:
			frappe.throw(_("Configure an API key in Ask ALYF Settings before sending messages."))
		return api_key

	def _get_model_id(self) -> str:
		model_id = (self.settings.model or "").strip()
		if not model_id:
			frappe.throw(_("Configure a model in Ask ALYF Settings before sending messages."))

		try:
			AnyLLM.split_model_provider(model_id)
			return model_id
		except ValueError:
			pass

		if self.settings.llm_provider in {"OpenAI", "OpenAI Compatible"}:
			return f"openai:{model_id}"

		return model_id

	def _build_instructions(self) -> str:
		context = frappe.as_json(self.runtime.request_context, indent=2)
		excluded_doctypes = ", ".join(sorted(tools.get_excluded_doctypes())) or "None"
		system_prompt = (self.settings.system_prompt or "").strip()

		base_instructions = f"""
You are Ask ALYF, an ERPNext and Frappe assistant embedded inside the user's desk.

Always follow these rules:
- Use the available read tools whenever the user asks about instance data, permissions, metadata, code, files, or reports.
- Be concise, accurate, and explicit about uncertainty.
- Respect the current user's permissions. If a tool says something is not allowed, explain that plainly.
- If request context `lang` is not English, always call `translate_ui_labels` before using user-facing UI terms (DocType names, field labels, button labels, tabs, menus, and status labels) in your response.
- Render responses as Markdown when that helps.
- Current request context:
{context}

Mode awareness and behavior:
- The current mode is `{self.runtime.mode}` and is authoritative for this turn.
- `Ask` mode is strictly read-only: write tools are unavailable, so if intent is mutation (create, update, submit, cancel, amend, rename, delete, attach, or a write method), immediately recommend switching to `Agent` mode and do not claim anything was done or queued.
- `Agent` mode supports mutation workflows with write tools while still handling read-only questions with read tools, and every write action becomes a pending proposal that requires explicit user confirmation before execution.
- Frontend action tools can navigate or adjust the current form in the browser, or display Frappe Charts under the assistant message via `show_chart` (pass `frappe_charts` as a list of chart option objects; validated server-side). See the `show_chart` tool docstring for the options shape.
- Frontend actions with `requires_confirmation` must be confirmed before the browser executes them.
- Before insert or save, call get_meta for the target DocType and follow field types exactly.
- Child table fields (fieldtype Table) must be arrays of row objects, never plain strings.
- After a write tool succeeds, explain what will happen when the user confirms it.
- When code search is enabled, `search_code`, `read_code_file`, `ls`, `find`, and `grep` are read-only and restricted to installed app directories.
- Excluded DocTypes for Agent mode: {excluded_doctypes}
""".strip()

		if system_prompt:
			return f"{system_prompt}\n\n{base_instructions}"

		return base_instructions

	def _build_tools(self) -> list[Callable[..., Any]]:
		tool_defs: list[Callable[..., Any]] = [
			self.toolset.get_list,
			self.toolset.get_count,
			self.toolset.get,
			self.toolset.get_value,
			self.toolset.get_single_value,
			self.toolset.get_meta,
			self.toolset.has_permission,
			self.toolset.get_doc_permissions,
			self.toolset.list_accessible_doctypes,
			self.toolset.list_accessible_reports,
			self.toolset.get_current_user_roles,
			self.toolset.translate_ui_labels,
			self.toolset.set_route,
			self.toolset.new_doc,
			self.toolset.scroll_to_field,
			self.toolset.show_chart,
			self.toolset.read_file_record,
			self.toolset.run_read_only_sql,
			self.toolset.get_app_version,
			self.toolset.read_github_releases,
			self.toolset.read_documentation_page,
		]

		if self.settings.is_code_search_enabled():
			tool_defs.extend(
				[
					self.toolset.search_code,
					self.toolset.read_code_file,
					self.toolset.ls,
					self.toolset.find,
					self.toolset.grep,
				]
			)

		if self.runtime.mode == "Agent":
			tool_defs.extend(
				[
					self.toolset.insert,
					self.toolset.save,
					self.toolset.set_value,
					self.toolset.submit,
					self.toolset.cancel,
					self.toolset.amend,
					self.toolset.delete,
					self.toolset.rename_doc,
					self.toolset.attach_file,
					self.toolset.run_whitelisted_method,
					self.toolset.frm_set_value,
					self.toolset.frm_add_child,
				]
			)

		return tool_defs

	def run(self, message: str, conversation_history: list[dict[str, Any]]) -> dict[str, Any]:
		trace = self.agent.run(build_prompt(message, conversation_history))
		return {
			"response": str(trace.final_output or "").strip(),
			"pending_operation": self.runtime.pending_operation,
		}


def build_prompt(message: str, conversation_history: list[dict[str, Any]]) -> str:
	if not conversation_history:
		return message

	lines = [
		"Use the prior conversation as context when answering the final user message.",
		"",
		"Conversation history:",
	]
	for item in conversation_history:
		role = (item.get("role") or "user").capitalize()
		content = item.get("content") or ""
		lines.append(f"{role}: {content}")

	lines.extend(["", f"User: {message}"])
	return "\n".join(lines)


def run_message(
	conversation_name: str,
	message: str,
	mode: str,
	request_context: dict[str, Any],
	conversation_history: list[dict[str, Any]],
) -> dict[str, Any]:
	runtime = ask_alyfRuntime(
		conversation_name=conversation_name,
		user=frappe.session.user,
		mode=mode,
		request_context=request_context,
	)
	runner = ask_alyfAgentRunner(runtime)
	return runner.run(message, conversation_history)
