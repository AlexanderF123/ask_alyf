from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.background_jobs import enqueue
from frappe.utils.data import cint

from ask_alyf.ask_alyf.agent import run_message
from ask_alyf.ask_alyf.tools import execute_action, get_settings
from ask_alyf.ask_alyf.utils import chunk_text, dumps, loads


def has_app_permission() -> bool:
	return can_access_ask_alyf()


def get_ask_alyf_boot_payload() -> dict:
	settings_available = frappe.db.exists("DocType", "Ask ALYF Settings")
	configured = False
	edit_mode_enabled = False

	try:
		settings = get_settings()
		edit_mode_enabled = bool(settings.allow_agent_mode)
		api_key = (settings.get_password("api_key", raise_exception=False) or "").strip()
		configured = bool(api_key and (settings.model or "").strip())
	except Exception:
		pass

	return {
		"allowed": can_access_ask_alyf(),
		"configured": configured,
		"edit_mode_enabled": edit_mode_enabled,
		"default_mode": "Read-Only",
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
	if not allowed_roles:
		return True

	return bool(allowed_roles.intersection(set(frappe.get_roles())))


def get_allowed_roles(settings) -> set[str]:
	rows = settings.get("allowed_roles") or []

	allowed_roles = set()
	for row in rows:
		role = row.get("role") if isinstance(row, dict) else getattr(row, "role", None)
		if role and isinstance(role, str) and role.strip():
			allowed_roles.add(role.strip())

	return allowed_roles


def can_use_edit_mode() -> bool:
	if not can_access_ask_alyf():
		return False

	try:
		settings = get_settings()
	except Exception:
		return False

	return bool(settings.allow_agent_mode)


def normalize_mode(mode: str | None) -> str:
	if mode == "Edit-Mode":
		if not can_use_edit_mode():
			frappe.throw(_("Edit mode is disabled or not available for your user."))
		return "Edit-Mode"

	return "Read-Only"


def make_message(role: str, content: str, **metadata) -> dict:
	return {
		"id": uuid4().hex,
		"role": role,
		"content": content,
		"created_at": now_datetime().isoformat(),
		"metadata": metadata,
	}


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


def conversation_payload(conversation) -> dict:
	return {
		"name": conversation.name,
		"title": conversation.title,
		"status": conversation.status,
		"route": conversation.route,
		"messages": get_messages(conversation),
		"pending_action": loads(conversation.pending_action_json, None),
		"last_context": loads(conversation.last_context_json, {}),
	}


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
	mode: str = "Read-Only",
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
	doc.pending_action_json = ""
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
		pending_action = result.get("pending_action")
		if pending_action and not response:
			response = _("I prepared the requested action. Please review it and confirm if it looks correct.")
	except Exception as error:
		frappe.log_error(frappe.get_traceback(), "Ask ALYF Agent Error")
		response = str(error).strip() or _("I hit an error while processing that request. Please try again.")
		pending_action = None

	assistant_message = make_message("assistant", response, mode=mode, pending_action=bool(pending_action))
	messages.append(assistant_message)
	doc.pending_action_json = dumps(pending_action) if pending_action else ""
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
			"pending_action": pending_action,
		},
		user=doc.user,
	)


@frappe.whitelist(methods=["POST"])
def confirm_pending_action(conversation: str, mode: str = "Read-Only") -> dict:
	doc = frappe.get_doc("Ask ALYF Conversation", conversation)
	pending_action = loads(doc.pending_action_json, None)
	if not pending_action:
		frappe.throw(_("There is no pending action to confirm."))

	messages = get_messages(doc)
	normalized_mode = normalize_mode(mode)
	try:
		result = execute_action(pending_action)
	except Exception as error:
		frappe.log_error(frappe.get_traceback(), "Ask ALYF Confirm Action Error")
		content = _("Could not confirm action: {0}").format(str(error))
		messages.append(make_message("assistant", content, mode=normalized_mode))
		save_messages(doc, messages)
		return {"error": str(error), "conversation": conversation_payload(doc)}

	doc.pending_action_json = ""
	action_result = {
		"action": pending_action.get("action"),
		"summary": pending_action.get("summary"),
		"doctype": pending_action.get("doctype"),
		"name": pending_action.get("name"),
	}
	if isinstance(result, dict):
		action_result["name"] = result.get("name") or result.get("new_name") or action_result["name"]
		action_result["message"] = result.get("message")
	action_result = {key: value for key, value in action_result.items() if value not in (None, "")}

	content = _("Confirmed action: {0}").format(pending_action.get("summary") or pending_action.get("action"))
	if action_result.get("doctype") and action_result.get("name"):
		content += "\n\n" + _("Document: {0} {1}").format(action_result["doctype"], action_result["name"])
	elif action_result.get("message"):
		content += "\n\n" + str(action_result["message"])
	messages.append(make_message("assistant", content, confirmed_action=True, mode=normalized_mode))
	save_messages(doc, messages)

	return {"result": action_result, "conversation": conversation_payload(doc)}


@frappe.whitelist(methods=["POST"])
def reject_pending_action(conversation: str, mode: str = "Read-Only") -> dict:
	doc = frappe.get_doc("Ask ALYF Conversation", conversation)
	if not doc.pending_action_json:
		return {"conversation": conversation_payload(doc)}

	normalized_mode = normalize_mode(mode)
	doc.pending_action_json = ""
	messages = get_messages(doc)
	messages.append(
		make_message(
			"assistant",
			_("Cancelled the pending action."),
			rejected_action=True,
			mode=normalized_mode,
		)
	)
	save_messages(doc, messages)
	return {"conversation": conversation_payload(doc)}
