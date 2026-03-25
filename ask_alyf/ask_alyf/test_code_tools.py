from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from ask_alyf.ask_alyf import tools
from ask_alyf.ask_alyf.agent import ask_alyfAgentRunner, ask_alyfToolset


class FakeSettings(SimpleNamespace):
	def __init__(self, *, allow_code_search: bool):
		super().__init__(allow_code_search=allow_code_search)

	def is_code_search_enabled(self) -> bool:
		return bool(self.allow_code_search)


class UnitTestCodeTools(UnitTestCase):
	def make_runner(self, *, allow_code_search: bool):
		runtime = SimpleNamespace(
			conversation_name="TEST-CONVERSATION",
			user=frappe.session.user,
			mode="Ask",
			request_context={},
			emit_status=lambda _text: None,
		)
		runner = object.__new__(ask_alyfAgentRunner)
		runner.runtime = runtime
		runner.settings = FakeSettings(allow_code_search=allow_code_search)
		runner.toolset = ask_alyfToolset(runtime)
		return runner

	def test_build_tools_only_adds_code_tools_when_enabled(self):
		code_tool_names = {"search_code", "read_code_file", "ls", "find", "grep"}

		disabled_runner = self.make_runner(allow_code_search=False)
		disabled_tool_names = {tool.__name__ for tool in disabled_runner._build_tools()}
		self.assertFalse(code_tool_names.intersection(disabled_tool_names))

		enabled_runner = self.make_runner(allow_code_search=True)
		enabled_tool_names = {tool.__name__ for tool in enabled_runner._build_tools()}
		self.assertTrue(code_tool_names.issubset(enabled_tool_names))

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
			pending_operation=None,
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
