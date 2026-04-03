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
