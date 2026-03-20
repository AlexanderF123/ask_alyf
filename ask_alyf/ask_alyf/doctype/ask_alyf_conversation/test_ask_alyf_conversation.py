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
		messages = payload["messages"]
		self.assertTrue(messages)
		assistant = messages[-1]
		expected_with_id = {**expected_operation, "assistant_message_id": assistant["id"]}
		self.assertEqual(payload["pending_operation"], expected_with_id)

		complete_events = [call for call in realtime_calls if call["event"] == "ask_alyf_response_complete"]
		self.assertEqual(len(complete_events), 1)
		self.assertEqual(complete_events[0]["payload"]["pending_operation"], expected_with_id)

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
				with patch(
					"ask_alyf.ask_alyf.api.run_message",
					return_value={
						"response": "The ToDo TODO-0001 was updated successfully.",
						"pending_operation": None,
					},
				) as summarize_call:
					response = api.confirm_pending_operation(
						conversation=conversation.name, mode=api.MODE_ASK
					)

		execute_operation.assert_called_once_with(pending_operation)
		summarize_call.assert_called_once()
		system_message = summarize_call.call_args.kwargs["conversation_history"][-1]
		self.assertEqual(system_message["role"], "system")
		self.assertIn('"status": "success"', system_message["content"])
		self.assertIsNone(response["conversation"]["pending_operation"])

		conversation.reload()
		messages = loads(conversation.messages_json, [])
		self.assertTrue(messages)
		self.assertEqual(messages[-1]["content"], "The ToDo TODO-0001 was updated successfully.")

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
			with patch(
				"ask_alyf.ask_alyf.api.run_message",
				return_value={
					"response": "Opened the Sales Invoice list view in your browser.",
					"pending_operation": None,
				},
			) as summarize_call:
				response = api.frontend_action_result(
					conversation=conversation.name,
					call_id="call-frontend-1",
					status="success",
					mode=api.MODE_ASK,
					result={"route": ["List", "Sales Invoice"]},
				)

		summarize_call.assert_called_once()
		system_message = summarize_call.call_args.kwargs["conversation_history"][-1]
		self.assertEqual(system_message["role"], "system")
		self.assertIn('"status": "success"', system_message["content"])
		self.assertIsNone(response["conversation"]["pending_operation"])

		conversation.reload()
		messages = loads(conversation.messages_json, [])
		self.assertTrue(messages)
		self.assertEqual(messages[-1]["content"], "Opened the Sales Invoice list view in your browser.")
		self.assertEqual(messages[-1]["metadata"].get("frontend_action_status"), "success")
		self.assertTrue(messages[-1]["metadata"].get("frontend_action_result"))

	def test_show_chart_frontend_action_persists_charts_on_assistant_message(self):
		assistant_message = api.make_message(
			"assistant",
			"Here is your data.",
			mode=api.MODE_ASK,
			pending_operation=True,
		)
		frappe_charts = [
			{
				"type": "bar",
				"title": "Units",
				"height": 300,
				"colors": ["#7cd6fd"],
				"data": {
					"labels": ["A", "B"],
					"datasets": [{"name": "Qty", "values": [1, 2]}],
				},
			},
			{
				"type": "line",
				"title": "",
				"height": 0,
				"colors": [],
				"data": {
					"labels": ["Mon", "Tue"],
					"datasets": [{"name": "", "values": [3, 4]}],
				},
			},
		]
		pending_operation = {
			"kind": "frontend_action",
			"tool": "show_chart",
			"summary": "Show 2 charts",
			"requires_confirmation": False,
			"payload": {"frappe_charts": frappe_charts},
			"call_id": "call-chart-1",
			"assistant_message_id": assistant_message["id"],
		}
		conversation = self.make_conversation(
			messages=[assistant_message],
			pending_operation=pending_operation,
		)

		with patch("ask_alyf.ask_alyf.api.can_access_ask_alyf", return_value=True):
			response = api.frontend_action_result(
				conversation=conversation.name,
				call_id="call-chart-1",
				status="success",
				mode=api.MODE_ASK,
				result={"tool": "show_chart"},
			)

		self.assertIsNone(response["conversation"]["pending_operation"])
		conversation.reload()
		messages = loads(conversation.messages_json, [])
		self.assertEqual(len(messages), 1)
		stored = messages[0]["metadata"].get("frappe_charts")
		self.assertTrue(isinstance(stored, list))
		self.assertEqual(len(stored), 2)
		self.assertEqual(stored[0]["type"], "bar")
		self.assertEqual(stored[0]["title"], "Units")
		self.assertEqual(stored[0]["height"], 300)
		self.assertNotIn("height", stored[1])
		self.assertFalse(messages[0]["metadata"].get("pending_operation"))
