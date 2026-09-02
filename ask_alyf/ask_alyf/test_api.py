from unittest.mock import patch

from frappe.tests import UnitTestCase

from ask_alyf.ask_alyf import api


class UnitTestAskALYFApi(UnitTestCase):
	def test_can_access_ask_alyf_allows_user_with_role(self):
		with patch.object(api.frappe, "get_roles", return_value=["Desk User", api.ASK_ALYF_USER_ROLE]):
			self.assertTrue(api.can_access_ask_alyf())

	def test_can_access_ask_alyf_rejects_user_without_role(self):
		with patch.object(api.frappe, "get_roles", return_value=["Desk User"]):
			self.assertFalse(api.can_access_ask_alyf())

	def test_can_access_ask_alyf_rejects_guest(self):
		with (
			patch.dict(api.frappe.session, {"user": "Guest"}),
			patch.object(api.frappe, "get_roles", return_value=[api.ASK_ALYF_USER_ROLE]),
		):
			self.assertFalse(api.can_access_ask_alyf())

	def test_boot_payload_reports_awesomebar_chat_mode(self):
		settings = type(
			"Settings",
			(),
			{
				"allow_agent_mode": 0,
				"allow_field_agent": 0,
				"allow_file_upload": 0,
				"model": "gpt-test",
				"support_phone_number": "",
				"get": lambda self, key, default=None: {"awesomebar_chat": "Default Action"}.get(
					key, default
				),
				"get_password": lambda self, *args, **kwargs: "secret",
			},
		)()
		with (
			patch.object(api.frappe.db, "exists", return_value=True),
			patch.object(api, "get_settings", return_value=settings),
			patch.object(api, "can_access_ask_alyf", return_value=True),
		):
			payload = api.get_ask_alyf_boot_payload()

		self.assertEqual(payload["awesomebar_chat"], "Default Action")
		self.assertEqual(payload["assistant_name"], "Frag mich")
		self.assertTrue(payload["configured"])

	def test_boot_payload_falls_back_to_disabled_for_unknown_awesomebar_mode(self):
		settings = type(
			"Settings",
			(),
			{
				"allow_agent_mode": 0,
				"allow_field_agent": 0,
				"allow_file_upload": 0,
				"model": "",
				"support_phone_number": "",
				"get": lambda self, key, default=None: {"awesomebar_chat": "Something Else"}.get(
					key, default
				),
				"get_password": lambda self, *args, **kwargs: "",
			},
		)()
		with (
			patch.object(api.frappe.db, "exists", return_value=True),
			patch.object(api, "get_settings", return_value=settings),
			patch.object(api, "can_access_ask_alyf", return_value=False),
		):
			payload = api.get_ask_alyf_boot_payload()

		self.assertEqual(payload["awesomebar_chat"], "Disabled")
		self.assertEqual(payload["assistant_name"], api.ASSISTANT_NAME)
		self.assertFalse(payload["configured"])
