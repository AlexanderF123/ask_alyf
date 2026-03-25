from __future__ import annotations

from typing import Any
from uuid import uuid4

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.background_jobs import enqueue
from frappe.utils.data import cint

from ask_alyf.ask_alyf.agent import run_message
from ask_alyf.ask_alyf.tools import (
	OPERATION_KIND_BACKEND,
	OPERATION_KIND_FRONTEND,
	execute_pending_operation,
	get_settings,
	validate_frappe_charts_payload,
)
from ask_alyf.ask_alyf.utils import chunk_text, dumps, loads

MODE_ASK = "Ask"
MODE_AGENT = "Agent"


def get_support_phone_uri(phone_number: str | None) -> str:
	phone_number = (phone_number or "").strip()
	if not phone_number:
		return ""

	digits_only = "".join(character for character in phone_number if character.isdigit())
	if not digits_only:
		return ""

	prefix = "+" if phone_number.startswith("+") else ""
	return f"tel:{prefix}{digits_only}"


def has_app_permission() -> bool:
	return can_access_ask_alyf()


def get_ask_alyf_boot_payload() -> dict:
	settings_available = frappe.db.exists("DocType", "Ask ALYF Settings")
	configured = False
	agent_mode_enabled = False
	file_upload_enabled = False
	support_phone_number = ""
	support_phone_uri = ""

	try:
		settings = get_settings()
		agent_mode_enabled = bool(settings.allow_agent_mode)
		file_upload_enabled = bool(settings.allow_file_upload)
		api_key = (settings.get_password("api_key", raise_exception=False) or "").strip()
		configured = bool(api_key and (settings.model or "").strip())
		support_phone_number = (settings.support_phone_number or "").strip()
		support_phone_uri = get_support_phone_uri(support_phone_number)
	except Exception:
		pass

	return {
		"allowed": can_access_ask_alyf(),
		"configured": configured,
		"agent_mode_enabled": agent_mode_enabled,
		"file_upload_enabled": file_upload_enabled,
		"support_phone_number": support_phone_number,
		"support_phone_uri": support_phone_uri,
		"default_mode": MODE_ASK,
		"site_name": frappe.local.site,
		"user": frappe.session.user,
		"settings_available": bool(settings_available),
	}


def can_access_ask_alyf() -> bool:
	if frappe.session.user == "Guest":
		return False

	try:
		settings = get_settings()
	except Exception:
		return True

	allowed_roles = get_allowed_roles(settings)
	return bool(allowed_roles.intersection(set(frappe.get_roles())))


def get_allowed_roles(settings) -> set[str]:
	rows = settings.get("allowed_roles") or []

	allowed_roles = set()
	for row in rows:
		role = row.get("role") if isinstance(row, dict) else getattr(row, "role", None)
		if role and isinstance(role, str) and role.strip():
			allowed_roles.add(role.strip())

	return allowed_roles


def can_use_agent_mode() -> bool:
	if not can_access_ask_alyf():
		return False

	try:
		settings = get_settings()
	except Exception:
		return False

	return bool(settings.allow_agent_mode)


def normalize_mode(mode: str | None) -> str:
	if mode == MODE_AGENT:
		if not can_use_agent_mode():
			frappe.throw(_("Agent mode is disabled or not available for your user."))
		return MODE_AGENT

	return MODE_ASK


def make_message(role: str, content: str, **metadata) -> dict:
	return {
		"id": uuid4().hex,
		"role": role,
		"content": content,
		"created_at": now_datetime().isoformat(),
		"metadata": metadata,
	}


def build_assistant_message_metadata(
	mode: str,
	*,
	pending_operation: dict[str, Any] | None = None,
	document_extractions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
	"""Build persisted metadata for an assistant message."""
	metadata = {
		"mode": mode,
		"pending_operation": bool(pending_operation),
	}
	if isinstance(document_extractions, list) and document_extractions:
		metadata["document_extractions"] = document_extractions
	return metadata


def find_assistant_message_for_pending_operation(
	messages: list[dict[str, Any]],
	pending_operation: dict[str, Any],
) -> dict[str, Any] | None:
	target_id = pending_operation.get("assistant_message_id")
	if not isinstance(target_id, str) or not target_id.strip():
		return None

	target_id = target_id.strip()
	for msg in messages:
		if msg.get("id") == target_id:
			return msg

	return None


def attach_frappe_charts_to_message(
	message: dict[str, Any],
	charts: list[dict[str, Any]],
) -> None:
	meta = message.setdefault("metadata", {})
	meta["frappe_charts"] = [*charts]
	meta["pending_operation"] = False


def get_or_create_conversation(conversation_name: str | None = None):
	if conversation_name:
		doc = frappe.get_doc("Ask ALYF Conversation", conversation_name)
		doc.check_permission("read")
		return doc

	existing = frappe.get_all(
		"Ask ALYF Conversation",
		filters={"user": frappe.session.user, "status": "Active"},
		fields=["name"],
		order_by="modified desc",
		limit=1,
	)
	if existing:
		return frappe.get_doc("Ask ALYF Conversation", existing[0].name)

	doc = frappe.get_doc(
		{
			"doctype": "Ask ALYF Conversation",
			"title": _("New Conversation"),
			"user": frappe.session.user,
			"status": "Active",
			"messages_json": "[]",
		}
	)
	doc.insert()
	return doc


def get_messages(conversation) -> list[dict]:
	return loads(conversation.messages_json, [])


def save_messages(conversation, messages: list[dict]):
	conversation.messages_json = dumps(messages)
	conversation.last_message_at = now_datetime()
	conversation.save()


def summarize_executed_action(
	conversation,
	mode: str,
	messages: list[dict[str, Any]],
	pending_operation: dict[str, Any],
	*,
	status: str,
	result_payload: dict[str, Any] | None = None,
	error: str | None = None,
) -> str | None:
	request_context = loads(conversation.last_context_json, {})
	if not isinstance(request_context, dict):
		request_context = {}

	operation_payload = pending_operation.get("payload")
	operation_payload = operation_payload if isinstance(operation_payload, dict) else {}
	system_payload: dict[str, Any] = {
		"status": status,
		"operation": {
			"kind": pending_operation.get("kind"),
			"tool": pending_operation.get("tool"),
			"summary": pending_operation.get("summary"),
			"payload": operation_payload,
		},
	}
	if result_payload:
		system_payload["result"] = result_payload
	if error:
		system_payload["error"] = error

	system_message = (
		"The user already approved this action and it has been executed. "
		"Use this system context to explain what happened next. "
		"Do not ask for confirmation again and do not propose a new action.\n"
		f"{dumps(system_payload)}"
	)
	history_with_result = list(messages)
	history_with_result.append({"role": "system", "content": system_message})

	try:
		summary_result = run_message(
			conversation_name=conversation.name,
			message="Summarize the action result for the user in a concise helpful way.",
			mode=mode,
			request_context=request_context,
			conversation_history=history_with_result,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Ask ALYF Action Summary Error")
		return None

	response = (summary_result.get("response") or "").strip()
	return response or None


def conversation_payload(conversation) -> dict:
	return {
		"name": conversation.name,
		"title": conversation.title,
		"status": conversation.status,
		"route": conversation.route,
		"messages": get_messages(conversation),
		"pending_operation": loads(conversation.pending_operation_json, None),
		"last_context": loads(conversation.last_context_json, {}),
	}


def publish_status_update(conversation_name: str, user: str, text: str):
	frappe.publish_realtime(
		"ask_alyf_status",
		{"conversation": conversation_name, "text": text},
		user=user,
	)


@frappe.whitelist()
def bootstrap(conversation: str | None = None) -> dict:
	if not can_access_ask_alyf():
		frappe.throw(_("You do not have access to Ask ALYF."))

	doc = get_or_create_conversation(conversation_name=conversation)
	return {
		"ask_alyf": get_ask_alyf_boot_payload(),
		"conversation": conversation_payload(doc),
	}


@frappe.whitelist()
def list_conversations(limit: int = 20) -> list[dict]:
	if not can_access_ask_alyf():
		frappe.throw(_("You do not have access to Ask ALYF."))

	limit = max(1, cint(limit))
	conversations = frappe.get_all(
		"Ask ALYF Conversation",
		filters={"user": frappe.session.user},
		fields=["name", "title", "status", "modified", "last_message_at"],
		order_by="modified desc",
		limit=limit,
	)

	return conversations


@frappe.whitelist(methods=["POST"])
def start_new_conversation() -> dict:
	if not can_access_ask_alyf():
		frappe.throw(_("You do not have access to Ask ALYF."))

	doc = frappe.get_doc(
		{
			"doctype": "Ask ALYF Conversation",
			"title": _("New Conversation"),
			"user": frappe.session.user,
			"status": "Active",
			"messages_json": "[]",
		}
	)
	doc.insert()
	return conversation_payload(doc)


@frappe.whitelist(methods=["POST"])
def send_message(
	message: str,
	mode: str = MODE_ASK,
	conversation: str | None = None,
	context: str | dict | None = None,
) -> dict:
	if not can_access_ask_alyf():
		frappe.throw(_("You do not have access to Ask ALYF."))

	normalized_mode = normalize_mode(mode)
	context_data = frappe.parse_json(context) if isinstance(context, str) else (context or {})
	doc = get_or_create_conversation(conversation_name=conversation)

	messages = get_messages(doc)
	user_message = make_message("user", message, mode=normalized_mode)
	messages.append(user_message)

	if doc.title == _("New Conversation"):
		doc.title = message[:72]

	doc.route = context_data.get("route")
	doc.last_context_json = dumps(context_data)
	doc.pending_operation_json = ""
	save_messages(doc, messages)

	enqueue(
		"ask_alyf.ask_alyf.api.process_message_job",
		queue="short",
		enqueue_after_commit=True,
		conversation_name=doc.name,
		message=message,
		mode=normalized_mode,
		context_data=context_data,
		user_message_id=user_message["id"],
	)

	return {
		"conversation": doc.name,
		"user_message_id": user_message["id"],
	}


def process_message_job(
	conversation_name: str,
	message: str,
	mode: str,
	context_data: dict,
	user_message_id: str | None = None,
):
	doc = frappe.get_doc("Ask ALYF Conversation", conversation_name)
	messages = get_messages(doc)
	history = messages[:-1] if messages and messages[-1].get("id") == user_message_id else messages

	frappe.publish_realtime(
		"ask_alyf_response_start",
		{"conversation": conversation_name},
		user=doc.user,
	)

	try:
		result = run_message(
			conversation_name=conversation_name,
			message=message,
			mode=mode,
			request_context=context_data,
			conversation_history=history,
		)
		response = result.get("response") or ""
		pending_operation = result.get("pending_operation")
		document_extractions = result.get("document_extractions")
		if pending_operation and not response:
			response = _(
				"I prepared the requested operation. Please review it and confirm if it looks correct."
			)
	except Exception as error:
		frappe.log_error(frappe.get_traceback(), "Ask ALYF Agent Error")
		response = str(error).strip() or _("I hit an error while processing that request. Please try again.")
		pending_operation = None
		document_extractions = None

	assistant_message = make_message(
		"assistant",
		response,
		**build_assistant_message_metadata(
			mode,
			pending_operation=pending_operation,
			document_extractions=document_extractions,
		),
	)
	messages.append(assistant_message)
	if pending_operation and isinstance(pending_operation, dict):
		pending_operation = {**pending_operation, "assistant_message_id": assistant_message["id"]}
	doc.pending_operation_json = dumps(pending_operation) if pending_operation else ""
	save_messages(doc, messages)

	for chunk in chunk_text(response or " "):
		frappe.publish_realtime(
			"ask_alyf_response_chunk",
			{
				"conversation": conversation_name,
				"message_id": assistant_message["id"],
				"chunk": chunk + " ",
			},
			user=doc.user,
		)

	frappe.publish_realtime(
		"ask_alyf_response_complete",
		{
			"conversation": conversation_name,
			"message_id": assistant_message["id"],
			"pending_operation": pending_operation,
		},
		user=doc.user,
	)


@frappe.whitelist(methods=["POST"])
def confirm_pending_operation(conversation: str, mode: str = MODE_ASK) -> dict:
	if not can_access_ask_alyf():
		frappe.throw(_("You do not have access to Ask ALYF."))

	doc = frappe.get_doc("Ask ALYF Conversation", conversation)
	doc.check_permission("write")
	pending_operation = loads(doc.pending_operation_json, None)
	if not pending_operation:
		frappe.throw(_("There is no pending operation to confirm."))

	messages = get_messages(doc)
	normalized_mode = normalize_mode(mode)
	if pending_operation.get("kind") != OPERATION_KIND_BACKEND:
		frappe.throw(_("Only backend actions can be confirmed by this endpoint."))

	publish_status_update(doc.name, doc.user, _("Confirming action..."))
	try:
		try:
			result = execute_pending_operation(pending_operation)
		except Exception as error:
			frappe.log_error(frappe.get_traceback(), "Ask ALYF Confirm Action Error")
			content = _("Could not confirm operation: {0}").format(str(error))
			messages.append(make_message("assistant", content, mode=normalized_mode))
			save_messages(doc, messages)
			return {"error": str(error), "conversation": conversation_payload(doc)}

		publish_status_update(doc.name, doc.user, _("Generating response..."))
		doc.pending_operation_json = ""
		operation_payload = pending_operation.get("payload") if isinstance(pending_operation, dict) else {}
		operation_payload = operation_payload if isinstance(operation_payload, dict) else {}
		action_result = {
			"kind": pending_operation.get("kind"),
			"tool": pending_operation.get("tool"),
			"summary": pending_operation.get("summary"),
			"doctype": operation_payload.get("doctype"),
			"name": operation_payload.get("name"),
		}
		if isinstance(result, dict):
			action_result["name"] = result.get("name") or result.get("new_name") or action_result["name"]
			action_result["message"] = result.get("message")
		action_result = {key: value for key, value in action_result.items() if value not in (None, "")}

		content = summarize_executed_action(
			doc,
			normalized_mode,
			messages,
			pending_operation,
			status="success",
			result_payload=action_result,
		)
		if not content:
			content = _("Confirmed operation: {0}").format(
				pending_operation.get("summary") or pending_operation.get("tool")
			)
			if action_result.get("doctype") and action_result.get("name"):
				content += "\n\n" + _("Document: {0} {1}").format(
					action_result["doctype"], action_result["name"]
				)
			elif action_result.get("message"):
				content += "\n\n" + str(action_result["message"])

		messages.append(make_message("assistant", content, confirmed_action=True, mode=normalized_mode))
		save_messages(doc, messages)

		return {"result": action_result, "conversation": conversation_payload(doc)}
	finally:
		publish_status_update(doc.name, doc.user, "")


@frappe.whitelist(methods=["POST"])
def reject_pending_operation(conversation: str, mode: str = MODE_ASK) -> dict:
	if not can_access_ask_alyf():
		frappe.throw(_("You do not have access to Ask ALYF."))

	doc = frappe.get_doc("Ask ALYF Conversation", conversation)
	doc.check_permission("write")
	pending_operation = loads(doc.pending_operation_json, None)
	if not pending_operation:
		return {"conversation": conversation_payload(doc)}

	normalized_mode = normalize_mode(mode)
	doc.pending_operation_json = ""
	messages = get_messages(doc)
	summary = pending_operation.get("summary") or pending_operation.get("tool")
	messages.append(
		make_message(
			"assistant",
			_("Cancelled the pending operation: {0}.").format(summary),
			rejected_action=True,
			mode=normalized_mode,
		)
	)
	save_messages(doc, messages)
	return {"conversation": conversation_payload(doc)}


def _resolve_show_chart_frontend_action(
	doc,
	messages: list[dict[str, Any]],
	pending_operation: dict[str, Any],
	status_value: str,
	error: str | None,
	normalized_mode: str,
) -> dict[str, Any]:
	doc.pending_operation_json = ""

	if status_value == "success":
		payload = pending_operation.get("payload")
		payload = payload if isinstance(payload, dict) else {}
		charts, validation_error = validate_frappe_charts_payload(payload.get("frappe_charts"))
		if validation_error:
			frappe.throw(validation_error)
		target = find_assistant_message_for_pending_operation(messages, pending_operation)
		if not target:
			frappe.throw(_("Could not attach charts to the assistant message."))
		attach_frappe_charts_to_message(target, charts)
		save_messages(doc, messages)
		return {"conversation": conversation_payload(doc)}

	if status_value == "rejected":
		content = _("Cancelled showing chart: {0}.").format(pending_operation.get("summary") or _("chart"))
	else:
		content = _("Could not display chart.")
		if error:
			content += " " + _("Reason: {0}").format(error)

	messages.append(
		make_message(
			"assistant",
			content,
			mode=normalized_mode,
			frontend_action_result=True,
			frontend_action_status=status_value,
		)
	)
	save_messages(doc, messages)
	return {"conversation": conversation_payload(doc)}


@frappe.whitelist(methods=["POST"])
def frontend_action_result(
	conversation: str,
	call_id: str,
	status: str,
	mode: str = MODE_ASK,
	result: str | dict | None = None,
	error: str | None = None,
) -> dict:
	if not can_access_ask_alyf():
		frappe.throw(_("You do not have access to Ask ALYF."))

	doc = frappe.get_doc("Ask ALYF Conversation", conversation)
	doc.check_permission("write")
	pending_operation = loads(doc.pending_operation_json, None)
	if not pending_operation:
		frappe.throw(_("There is no pending frontend action to resolve."))

	if pending_operation.get("kind") != OPERATION_KIND_FRONTEND:
		frappe.throw(_("The pending operation is not a frontend action."))

	if (pending_operation.get("call_id") or "") != (call_id or "").strip():
		frappe.throw(_("Frontend action call ID does not match the pending operation."))

	status_value = (status or "").strip().lower()
	if status_value not in {"success", "failed", "rejected"}:
		frappe.throw(_("Status must be one of success, failed, or rejected."))

	normalized_mode = normalize_mode(mode)
	result_payload: dict[str, Any] = {}
	if isinstance(result, str):
		parsed_result = frappe.parse_json(result)
		if isinstance(parsed_result, dict):
			result_payload = parsed_result
	elif isinstance(result, dict):
		result_payload = result

	publish_status_update(doc.name, doc.user, _("Generating response..."))
	try:
		messages = get_messages(doc)
		if (pending_operation.get("tool") or "").strip() == "show_chart":
			return _resolve_show_chart_frontend_action(
				doc,
				messages,
				pending_operation,
				status_value,
				error,
				normalized_mode,
			)

		summary = pending_operation.get("summary") or pending_operation.get("tool") or _("frontend action")
		content = summarize_executed_action(
			doc,
			normalized_mode,
			messages,
			pending_operation,
			status=status_value,
			result_payload=result_payload,
			error=error,
		)
		if not content:
			if status_value == "success":
				content = _("Executed frontend action: {0}").format(summary)
			elif status_value == "rejected":
				content = _("Cancelled frontend action: {0}").format(summary)
			else:
				content = _("Frontend action failed: {0}").format(summary)
				if error:
					content += "\n\n" + _("Reason: {0}").format(error)

		message_metadata = {
			"frontend_action_result": True,
			"frontend_action_status": status_value,
			"mode": normalized_mode,
		}
		if result_payload:
			message_metadata["frontend_action_payload"] = result_payload

		messages.append(make_message("assistant", content, **message_metadata))
		doc.pending_operation_json = ""
		save_messages(doc, messages)
		return {"conversation": conversation_payload(doc)}
	finally:
		publish_status_update(doc.name, doc.user, "")


@frappe.whitelist(methods=["POST"])
def attach_file(conversation: str, file: str | dict) -> dict:
	if not can_access_ask_alyf():
		frappe.throw(_("You do not have access to Ask ALYF."))

	settings = get_settings()
	if not settings.allow_file_upload:
		frappe.throw(_("File upload is not enabled."))

	doc = frappe.get_doc("Ask ALYF Conversation", conversation)
	doc.check_permission("write")

	file_data = frappe.parse_json(file) if isinstance(file, str) else file
	file_id = ""
	if isinstance(file_data, dict):
		file_id = (file_data.get("name") or file_data.get("file_id") or "").strip()
	elif isinstance(file_data, str):
		file_id = file_data.strip()

	if not file_id:
		frappe.throw(_("No valid file provided."))
	if not frappe.db.exists("File", file_id):
		frappe.throw(_("File '{0}' was not found.").format(file_id))

	file_doc = frappe.get_doc("File", file_id)
	file_doc.check_permission("read")

	file_entry = {
		"name": file_doc.name,
		"file_name": file_doc.file_name,
		"file_url": file_doc.file_url,
	}

	content = f"User attached a file: {file_entry['file_name']} (ID: {file_entry['name']})"
	messages = get_messages(doc)
	messages.append(make_message("system", content, files=[file_entry]))
	save_messages(doc, messages)

	return {"conversation": conversation_payload(doc)}
