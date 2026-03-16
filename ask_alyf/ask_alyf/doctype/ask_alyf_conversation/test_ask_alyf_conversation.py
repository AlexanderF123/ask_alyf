# Copyright (c) 2026, ALYF GmbH and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from ask_alyf.ask_alyf import api, tools
from ask_alyf.ask_alyf.utils import dumps, loads


class UnitTestAskALYFConversation(UnitTestCase):
	def make_conversation(self, *, messages: list[dict] | None = None, pending_operation: dict | None = None):
		doc = frappe.get_doc(
			{
				"doctype": "Ask ALYF Conversation",
				"title": "Test Conversation",
				"user": frappe.session.user,
				"status": "Active",
				"messages_json": dumps(messages or []),
				"pending_operation_json": dumps(pending_operation) if pending_operation else "",
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_process_message_job_publishes_pending_operation(self):
		user_message = api.make_message("user", "Open Sales Invoice list", mode=api.MODE_ASK)
		conversation = self.make_conversation(messages=[user_message])
		expected_operation = {
			"kind": "frontend_action",
			"tool": "set_route",
			"summary": "Navigate to Sales Invoice list",
			"requires_confirmation": False,
			"payload": {"route": ["List", "Sales Invoice"]},
			"call_id": "call-123",
		}
		realtime_calls = []

		def record_realtime(event, payload=None, user=None, **kwargs):
			realtime_calls.append({"event": event, "payload": payload, "user": user, "kwargs": kwargs})

		with patch(
			"ask_alyf.ask_alyf.api.run_message",
			return_value={"response": "Done", "pending_operation": expected_operation},
		):
			with patch("ask_alyf.ask_alyf.api.frappe.publish_realtime", side_effect=record_realtime):
				api.process_message_job(
					conversation_name=conversation.name,
					message="Open Sales Invoice list",
					mode=api.MODE_ASK,
					context_data={},
					user_message_id=user_message["id"],
				)

		conversation.reload()
		payload = api.conversation_payload(conversation)
		self.assertEqual(payload["pending_operation"], expected_operation)

		complete_events = [call for call in realtime_calls if call["event"] == "ask_alyf_response_complete"]
		self.assertEqual(len(complete_events), 1)
		self.assertEqual(complete_events[0]["payload"]["pending_operation"], expected_operation)

	def test_invalid_frontend_operation_rejected_server_side(self):
		with self.assertRaises(frappe.ValidationError):
			tools.execute_pending_operation(
				{
					"kind": "frontend_action",
					"tool": "unsupported_tool",
					"payload": {},
				}
			)

	def test_confirm_pending_operation_executes_backend_path(self):
		pending_operation = {
			"kind": "backend_action",
			"tool": "set_value",
			"summary": "Set status",
			"requires_confirmation": True,
			"payload": {"doctype": "ToDo", "name": "TODO-0001", "fieldname": "status", "value": "Closed"},
			"call_id": "call-backend-1",
		}
		conversation = self.make_conversation(messages=[], pending_operation=pending_operation)

		with patch("ask_alyf.ask_alyf.api.can_access_ask_alyf", return_value=True):
			with patch(
				"ask_alyf.ask_alyf.api.execute_pending_operation",
				return_value={"name": "TODO-0001", "message": "Updated"},
			) as execute_operation:
				response = api.confirm_pending_operation(conversation=conversation.name, mode=api.MODE_ASK)

		execute_operation.assert_called_once_with(pending_operation)
		self.assertIsNone(response["conversation"]["pending_operation"])

		conversation.reload()
		messages = loads(conversation.messages_json, [])
		self.assertTrue(messages)
		self.assertIn("Confirmed operation", messages[-1]["content"])

	def test_frontend_action_result_clears_pending_operation(self):
		pending_operation = {
			"kind": "frontend_action",
			"tool": "set_route",
			"summary": "Navigate to Sales Invoice list",
			"requires_confirmation": False,
			"payload": {"route": ["List", "Sales Invoice"]},
			"call_id": "call-frontend-1",
		}
		conversation = self.make_conversation(messages=[], pending_operation=pending_operation)

		with patch("ask_alyf.ask_alyf.api.can_access_ask_alyf", return_value=True):
			response = api.frontend_action_result(
				conversation=conversation.name,
				call_id="call-frontend-1",
				status="success",
				mode=api.MODE_ASK,
				result={"route": ["List", "Sales Invoice"]},
			)

		self.assertIsNone(response["conversation"]["pending_operation"])

		conversation.reload()
		messages = loads(conversation.messages_json, [])
		self.assertTrue(messages)
		self.assertEqual(messages[-1]["metadata"].get("frontend_action_status"), "success")
		self.assertTrue(messages[-1]["metadata"].get("frontend_action_result"))
