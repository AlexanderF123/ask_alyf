import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import frappe
from frappe.tests import UnitTestCase

from ask_alyf.ask_alyf import tools
from ask_alyf.ask_alyf.agent import ask_alyfAgentRunner, ask_alyfToolset


class FakeSettings(SimpleNamespace):
	def __init__(self, *, allow_code_search: bool):
		super().__init__(
			allow_code_search=allow_code_search,
			system_prompt="",
			model="gpt-test",
			llm_provider="OpenAI",
			base_url="",
		)

	def is_code_search_enabled(self) -> bool:
		return bool(self.allow_code_search)

	def get_password(self, _fieldname, raise_exception=False):
		return "test-key"


class UnitTestCodeTools(UnitTestCase):
	def make_runner(self, *, allow_code_search: bool, mode: str = "Ask"):
		runtime = SimpleNamespace(
			conversation_name="TEST-CONVERSATION",
			user=frappe.session.user,
			mode=mode,
			request_context={},
			conversation_history=[],
			pending_operation=None,
			document_extractions=[],
			emit_status=lambda _text: None,
		)
		runner = object.__new__(ask_alyfAgentRunner)
		runner.runtime = runtime
		runner.settings = FakeSettings(allow_code_search=allow_code_search)
		runner.toolset = ask_alyfToolset(runtime, settings=runner.settings)
		return runner

	def test_build_tools_only_adds_source_code_analyzer_when_enabled(self):
		raw_code_tool_names = {"search_code", "read_code_file", "ls", "find", "grep"}

		disabled_runner = self.make_runner(allow_code_search=False)
		disabled_tool_names = {tool.__name__ for tool in disabled_runner._build_tools()}
		self.assertNotIn("source_code_analyzer", disabled_tool_names)
		self.assertFalse(raw_code_tool_names.intersection(disabled_tool_names))

		enabled_runner = self.make_runner(allow_code_search=True)
		enabled_tool_names = {tool.__name__ for tool in enabled_runner._build_tools()}
		self.assertIn("source_code_analyzer", enabled_tool_names)
		self.assertFalse(raw_code_tool_names.intersection(enabled_tool_names))

	def test_build_tools_only_adds_document_planner_in_agent_mode(self):
		ask_runner = self.make_runner(allow_code_search=False, mode="Ask")
		ask_tool_names = {tool.__name__ for tool in ask_runner._build_tools()}
		self.assertNotIn("document_planner", ask_tool_names)

		agent_runner = self.make_runner(allow_code_search=False, mode="Agent")
		agent_tool_names = {tool.__name__ for tool in agent_runner._build_tools()}
		self.assertIn("document_planner", agent_tool_names)

	def test_code_tools_require_setting_to_be_enabled(self):
		with patch(
			"ask_alyf.ask_alyf.tools.get_settings", return_value=FakeSettings(allow_code_search=False)
		):
			with self.assertRaises(frappe.ValidationError):
				tools.ls("ask_alyf")

	def test_read_code_file_rejects_non_app_paths(self):
		with patch("ask_alyf.ask_alyf.tools.get_settings", return_value=FakeSettings(allow_code_search=True)):
			with self.assertRaises(frappe.ValidationError):
				tools.read_code_file("sites/common_site_config.json")

	def test_ls_find_and_grep_are_scoped_to_installed_app_paths(self):
		with patch("ask_alyf.ask_alyf.tools.get_settings", return_value=FakeSettings(allow_code_search=True)):
			listing = tools.ls("ask_alyf", "ask_alyf", limit=10)
			self.assertEqual(listing["app_name"], "ask_alyf")
			self.assertTrue(listing["entries"])
			self.assertTrue(all(entry["path"].startswith("apps/ask_alyf/") for entry in listing["entries"]))

			find_result = tools.find("ask_alyf", name_pattern="agent.py", limit=10)
			find_paths = {match["path"] for match in find_result["matches"]}
			self.assertIn("apps/ask_alyf/ask_alyf/ask_alyf/agent.py", find_paths)

			grep_result = tools.grep(
				"ask_alyf",
				"class ask_alyfAgentRunner",
				file_pattern="*.py",
				limit=10,
			)
			grep_paths = {match["path"] for match in grep_result["matches"]}
			self.assertIn("apps/ask_alyf/ask_alyf/ask_alyf/agent.py", grep_paths)

	def test_get_list_coerces_single_field_string_to_list(self):
		with patch("ask_alyf.ask_alyf.tools.client.get_list", return_value=[]) as get_list:
			result = tools.get_list("Item Group", fields="name", filters={})

		get_list.assert_called_once_with(
			doctype="Item Group",
			fields=["name"],
			filters={},
			order_by=None,
			limit_page_length=20,
			group_by=None,
		)
		self.assertEqual(result, [])

	def test_get_list_coerces_comma_separated_fields_to_list(self):
		with patch("ask_alyf.ask_alyf.tools.client.get_list", return_value=[]) as get_list:
			result = tools.get_list(
				"Purchase Taxes and Charges Template",
				fields="name,company",
				filters={"company": "ALYF GmbH"},
			)

		get_list.assert_called_once_with(
			doctype="Purchase Taxes and Charges Template",
			fields=["name", "company"],
			filters={"company": "ALYF GmbH"},
			order_by=None,
			limit_page_length=20,
			group_by=None,
		)
		self.assertEqual(result, [])

	def test_get_file_id_uses_reference_filters(self):
		expected_filters = {
			"attached_to_doctype": "Sales Invoice",
			"attached_to_name": "SINV-0001",
			"attached_to_field": "custom_attachment",
			"file_name": "invoice.pdf",
		}
		with patch("ask_alyf.ask_alyf.tools.get_list", return_value=[{"name": "FILE-0001"}]) as get_list:
			file_id = tools.get_file_id(
				reference_doctype="Sales Invoice",
				reference_name="SINV-0001",
				reference_field="custom_attachment",
				file_name="invoice.pdf",
			)

		get_list.assert_called_once_with(
			"File",
			fields=["name"],
			filters=expected_filters,
			order_by="modified desc",
			limit=2,
		)
		self.assertEqual(file_id, "FILE-0001")

	def test_get_file_id_rejects_ambiguous_matches(self):
		with patch(
			"ask_alyf.ask_alyf.tools.get_list",
			return_value=[{"name": "FILE-0001"}, {"name": "FILE-0002"}],
		):
			with self.assertRaises(frappe.ValidationError):
				tools.get_file_id(reference_doctype="Sales Invoice", reference_name="SINV-0001")

	def test_attach_file_proposal_uses_linked_file_name_summary(self):
		runtime = SimpleNamespace(
			conversation_name="TEST-CONVERSATION",
			user=frappe.session.user,
			mode="Agent",
			request_context={},
			conversation_history=[],
			pending_operation=None,
			document_extractions=[],
			emit_status=lambda _text: None,
		)
		toolset = ask_alyfToolset(runtime)
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "invoice.txt",
				"content": "Test Content",
				"is_private": 1,
			}
		).save()

		result = toolset.attach_file("ToDo", "TODO-0001", file_doc.name)

		self.assertTrue(result["success"])
		self.assertEqual(result["proposal"]["payload"]["file_id"], file_doc.name)
		self.assertIn(f"[{file_doc.file_name}](", result["proposal"]["summary"])
		self.assertIn(file_doc.file_url, result["proposal"]["summary"])

	def test_source_code_analyzer_tool_delegates_to_specialist(self):
		runtime = SimpleNamespace(
			conversation_name="TEST-CONVERSATION",
			user=frappe.session.user,
			mode="Ask",
			request_context={},
			conversation_history=[],
			pending_operation=None,
			document_extractions=[],
			emit_status=lambda _text: None,
		)
		toolset = ask_alyfToolset(runtime)
		expected = {
			"answer": "The main agent runner is in agent.py.",
			"summary": "Found the main runner.",
			"evidence": [{"path": "apps/ask_alyf/ask_alyf/ask_alyf/agent.py", "start_line": 989}],
			"uncertainty": "",
			"searched_paths": ["apps/ask_alyf/ask_alyf/ask_alyf"],
		}
		specialist = SimpleNamespace(analyze=AsyncMock(return_value=expected))

		with patch.object(toolset, "_get_source_code_analyzer", return_value=specialist):
			result = asyncio.run(
				toolset.source_code_analyzer(
					"Where is the main agent runner defined?",
					relative_path="ask_alyf/ask_alyf",
				)
			)

		specialist.analyze.assert_awaited_once_with(
			question="Where is the main agent runner defined?",
			relative_path="ask_alyf/ask_alyf",
		)
		self.assertEqual(result, expected)

	def test_source_code_analyzer_initializes_internal_agent_async(self):
		runtime = SimpleNamespace(
			conversation_name="TEST-CONVERSATION",
			user=frappe.session.user,
			mode="Ask",
			request_context={},
			conversation_history=[],
			pending_operation=None,
			document_extractions=[],
			emit_status=lambda _text: None,
		)
		toolset = ask_alyfToolset(runtime, settings=FakeSettings(allow_code_search=True))
		fake_trace = SimpleNamespace(final_output='{"answer":"Verified","summary":"Verified"}')
		fake_agent = SimpleNamespace(run_async=AsyncMock(return_value=fake_trace))
		analyzer = toolset._get_source_code_analyzer()

		with patch(
			"ask_alyf.ask_alyf.agent._create_internal_agent_async",
			AsyncMock(return_value=fake_agent),
		) as create_agent:
			first = asyncio.run(analyzer.analyze("Where is tax logic implemented?", relative_path="erpnext"))
			second = asyncio.run(analyzer.analyze("Where is tax logic implemented?", relative_path="erpnext"))

		create_agent.assert_awaited_once()
		self.assertEqual(fake_agent.run_async.await_count, 2)
		self.assertEqual(first["answer"], "Verified")
		self.assertEqual(second["summary"], "Verified")

	def test_document_planner_tool_delegates_to_specialist(self):
		runtime = SimpleNamespace(
			conversation_name="TEST-CONVERSATION",
			user=frappe.session.user,
			mode="Agent",
			request_context={},
			conversation_history=[],
			pending_operation=None,
			document_extractions=[],
			emit_status=lambda _text: None,
		)
		toolset = ask_alyfToolset(runtime)
		expected = {
			"ready": True,
			"recommended_tool": "insert",
			"payload": {"doctype": "ToDo", "values": {"description": "Call customer"}},
			"reason": "The user asked to create a new ToDo.",
			"missing_information": [],
			"checks": ["Loaded ToDo metadata."],
			"warnings": [],
		}
		specialist = SimpleNamespace(plan=AsyncMock(return_value=expected))

		with patch.object(toolset, "_get_document_planner", return_value=specialist):
			result = asyncio.run(
				toolset.document_planner(
					user_request="Create a ToDo to call the customer.",
					doctype="ToDo",
					operation="insert",
					values_hint={"description": "Call customer"},
				)
			)

		specialist.plan.assert_awaited_once_with(
			user_request="Create a ToDo to call the customer.",
			doctype="ToDo",
			operation="insert",
			name="",
			values_hint={"description": "Call customer"},
		)
		self.assertEqual(result, expected)

	def test_document_planner_initializes_internal_agent_async(self):
		runtime = SimpleNamespace(
			conversation_name="TEST-CONVERSATION",
			user=frappe.session.user,
			mode="Agent",
			request_context={},
			conversation_history=[],
			pending_operation=None,
			document_extractions=[],
			emit_status=lambda _text: None,
		)
		toolset = ask_alyfToolset(runtime, settings=FakeSettings(allow_code_search=False))
		fake_trace = SimpleNamespace(
			final_output='{"ready":true,"recommended_tool":"insert","payload":{"doctype":"ToDo","values":{}},"reason":"ok","missing_information":[],"checks":[],"warnings":[]}'
		)
		fake_agent = SimpleNamespace(run_async=AsyncMock(return_value=fake_trace))
		planner = toolset._get_document_planner()

		with patch(
			"ask_alyf.ask_alyf.agent._create_internal_agent_async",
			AsyncMock(return_value=fake_agent),
		) as create_agent:
			result = asyncio.run(
				planner.plan(
					user_request="Create a ToDo.",
					doctype="ToDo",
					operation="insert",
				)
			)

		create_agent.assert_awaited_once()
		fake_agent.run_async.assert_awaited_once()
		self.assertTrue(result["ready"])
		self.assertEqual(result["recommended_tool"], "insert")
