from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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
	pending_action: dict[str, Any] | None = None

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
		action: str,
		summary: str,
		reason: str = "",
		**payload: Any,
	) -> dict[str, Any]:
		"""Create a pending action proposal for edit-mode confirmation."""
		validation_error = tools.validate_pending_action_payload(action, payload)
		if validation_error:
			self.runtime.emit_status(f"{action} proposal needs correction.")
			return {
				"success": False,
				"requires_confirmation": False,
				"error": validation_error,
			}

		proposal = {
			"action": action,
			"summary": summary,
			"reason": reason,
			**payload,
		}
		self.runtime.pending_action = proposal
		self.runtime.emit_status(f"Prepared {action} proposal.")
		return {
			"success": True,
			"requires_confirmation": True,
			"proposal": proposal,
		}

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
		self.runtime.emit_status("Fetching list...")
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
		self.runtime.emit_status("Counting documents...")
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
		self.runtime.emit_status("Fetching document...")
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
		self.runtime.emit_status("Fetching value...")
		return tools.get_value(doctype=doctype, fieldname=fieldname, filters=filters)

	def get_single_value(self, doctype: str, field: str) -> Any:
		"""Read a field value from a Single DocType.

		Args:
			doctype: The Single DocType to query.
			field: The field name to read.

		Returns:
			The field value.
		"""
		self.runtime.emit_status("Fetching single value...")
		return tools.get_single_value(doctype=doctype, field=field)

	def get_meta(self, doctype: str) -> dict[str, Any]:
		"""Inspect metadata, fields, and permissions for a DocType.

		Args:
			doctype: The DocType to inspect.

		Returns:
			A metadata dictionary for the DocType.
		"""
		self.runtime.emit_status("Loading metadata...")
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
		self.runtime.emit_status("Checking permissions...")
		return tools.has_permission(doctype=doctype, docname=docname, perm_type=perm_type)

	def get_doc_permissions(self, doctype: str, docname: str) -> dict[str, Any]:
		"""Get the evaluated permission map for a document.

		Args:
			doctype: The DocType to check.
			docname: The document name.

		Returns:
			The evaluated permission dictionary.
		"""
		self.runtime.emit_status("Evaluating permissions...")
		return tools.get_doc_permissions(doctype=doctype, docname=docname)

	def list_accessible_doctypes(self, permission_type: str = "read") -> list[str]:
		"""List DocTypes that the current user can access.

		Args:
			permission_type: The permission type to test.

		Returns:
			A list of DocType names.
		"""
		self.runtime.emit_status("Listing accessible DocTypes...")
		return tools.list_accessible_doctypes(permission_type=permission_type)

	def list_accessible_reports(self) -> list[dict[str, Any]]:
		"""List reports that the current user can access.

		Returns:
			A list of report metadata dictionaries.
		"""
		self.runtime.emit_status("Listing accessible reports...")
		return tools.list_accessible_reports()

	def get_current_user_roles(self) -> list[str]:
		"""List the current user's roles.

		Returns:
			A list of role names.
		"""
		return tools.get_current_user_roles()

	def search_code(self, query: str, relative_path: str = "", limit: int = 20) -> list[dict[str, Any]]:
		"""Search the bench apps codebase for matching text.

		Args:
			query: The text to search for.
			relative_path: Optional path inside the apps directory. Providing at least the app name will make it much faster.
			limit: Maximum number of matches to return.

		Returns:
			A list of code search matches.
		"""
		self.runtime.emit_status("Searching code...")
		return tools.search_code(query=query, relative_path=relative_path, limit=limit)

	def read_code_file(self, path: str, start_line: int = 1, end_line: int = 200) -> dict[str, Any]:
		"""Read a file from the bench codebase.

		Args:
			path: Bench-relative path to read.
			start_line: First line to include.
			end_line: Last line to include.

		Returns:
			The selected file content and line range.
		"""
		self.runtime.emit_status("Reading code file...")
		return tools.read_code_file(path=path, start_line=start_line, end_line=end_line)

	def read_file_record(self, file_url: str | None = None, file_name: str | None = None) -> dict[str, Any]:
		"""Read the content of a File record the user can access.

		Args:
			file_url: Optional file URL.
			file_name: Optional file name.

		Returns:
			The file metadata and content.
		"""
		self.runtime.emit_status("Reading file...")
		return tools.read_file_record(file_url=file_url, file_name=file_name)

	def run_read_only_sql(self, query: str) -> list[dict[str, Any]]:
		"""Run a read-only SQL query when the current user is allowed to do so.

		Args:
			query: A single read-only SQL query.

		Returns:
			The SQL result rows.
		"""
		self.runtime.emit_status("Running SQL query...")
		return tools.run_read_only_sql(query=query)

	def get_app_version(self, app_name: str) -> str:
		"""Read the installed version for an app.

		Args:
			app_name: The installed app name.

		Returns:
			The app version string.
		"""
		self.runtime.emit_status("Reading app version...")
		return tools.get_app_version(app_name=app_name)

	def read_github_releases(self, app_name: str, limit: int = 5) -> list[dict[str, Any]]:
		"""Read recent GitHub releases for an installed app.

		Args:
			app_name: The installed app name.
			limit: Maximum number of releases to return.

		Returns:
			A list of release dictionaries.
		"""
		self.runtime.emit_status("Reading GitHub releases...")
		return tools.read_github_releases(app_name=app_name, limit=limit)

	def read_documentation_page(self, app_name: str, relative_path: str = "") -> dict[str, Any]:
		"""Fetch a documentation page for an installed app.

		Args:
			app_name: The installed app name.
			relative_path: Optional path relative to the configured docs URL.

		Returns:
			A documentation payload containing the page content.
		"""
		self.runtime.emit_status("Reading documentation...")
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
		return self._proposal("insert", f"Create {doctype}", reason, doctype=doctype, values=values)

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
		return self._proposal(
			"save",
			f"Update {doctype} {name}",
			reason,
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
		return self._proposal(
			"set_value",
			f"Set {fieldname} on {doctype} {name}",
			reason,
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
		return self._proposal("submit", f"Submit {doctype} {name}", reason, doctype=doctype, name=name)

	def cancel(self, doctype: str, name: str, reason: str = "") -> dict[str, Any]:
		"""Propose cancelling a document.

		Args:
			doctype: The DocType to cancel.
			name: The document name.
			reason: Optional explanation of why this change is needed.

		Returns:
			A pending action proposal that requires confirmation.
		"""
		return self._proposal("cancel", f"Cancel {doctype} {name}", reason, doctype=doctype, name=name)

	def amend(self, doctype: str, name: str, reason: str = "") -> dict[str, Any]:
		"""Propose amending a cancelled document.

		Args:
			doctype: The DocType to amend.
			name: The document name.
			reason: Optional explanation of why this change is needed.

		Returns:
			A pending action proposal that requires confirmation.
		"""
		return self._proposal("amend", f"Amend {doctype} {name}", reason, doctype=doctype, name=name)

	def delete(self, doctype: str, name: str, reason: str = "") -> dict[str, Any]:
		"""Propose deleting a document.

		Args:
			doctype: The DocType to delete.
			name: The document name.
			reason: Optional explanation of why this change is needed.

		Returns:
			A pending action proposal that requires confirmation.
		"""
		return self._proposal("delete", f"Delete {doctype} {name}", reason, doctype=doctype, name=name)

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
		return self._proposal(
			"rename_doc",
			f"Rename {doctype} {name} to {new_name}",
			reason,
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
		return self._proposal(
			"attach_file",
			f"Attach {file_url} to {doctype} {name}",
			reason,
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
		return self._proposal(
			"run_method",
			f"Call {method}",
			reason,
			method=method,
			args=args or {},
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
- Render responses as Markdown when that helps.
- Current request context:
{context}

Edit-mode rules:
- Edit mode is currently {self.runtime.mode}.
- Write tools do not execute immediately. They only create a pending action proposal.
- Before insert or save, call get_meta for the target DocType and follow field types exactly.
- Child table fields (fieldtype Table) must be arrays of row objects, never plain strings.
- Only call a write tool when the user clearly wants to create, update, submit, cancel, amend, rename, delete, attach, or invoke a method that changes data.
- After a write tool succeeds, explain what will happen when the user confirms it.
- Excluded DocTypes for edit mode: {excluded_doctypes}
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
			self.toolset.search_code,
			self.toolset.read_code_file,
			self.toolset.read_file_record,
			self.toolset.run_read_only_sql,
			self.toolset.get_app_version,
			self.toolset.read_github_releases,
			self.toolset.read_documentation_page,
		]

		if self.runtime.mode == "Edit-Mode":
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
				]
			)

		return tool_defs

	def run(self, message: str, conversation_history: list[dict[str, Any]]) -> dict[str, Any]:
		trace = self.agent.run(build_prompt(message, conversation_history))
		return {
			"response": str(trace.final_output or "").strip(),
			"pending_action": self.runtime.pending_action,
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
