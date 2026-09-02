from unittest.mock import patch

from frappe.tests import UnitTestCase

from ask_alyf.ask_alyf import utils
from ask_alyf.ask_alyf.utils import (
	ASSISTANT_NAME,
	AWESOMEBAR_CHAT_DEFAULT,
	AWESOMEBAR_CHAT_DISABLED,
	AWESOMEBAR_CHAT_OFFER,
	get_assistant_name,
	normalize_awesomebar_chat_mode,
)


class UnitTestAwesomebarChatMode(UnitTestCase):
	def test_known_modes_are_kept(self):
		for mode in (AWESOMEBAR_CHAT_DISABLED, AWESOMEBAR_CHAT_OFFER, AWESOMEBAR_CHAT_DEFAULT):
			self.assertEqual(normalize_awesomebar_chat_mode(mode), mode)

	def test_unknown_or_empty_values_fall_back_to_disabled(self):
		for value in (None, "", "  ", "Always", "default action"):
			self.assertEqual(normalize_awesomebar_chat_mode(value), AWESOMEBAR_CHAT_DISABLED)

	def test_surrounding_whitespace_is_ignored(self):
		self.assertEqual(normalize_awesomebar_chat_mode("  Offer in Results "), AWESOMEBAR_CHAT_OFFER)


class UnitTestAssistantName(UnitTestCase):
	def test_configured_name_is_used(self):
		with patch.object(utils.frappe.db, "get_single_value", return_value="  Frag mich  "):
			self.assertEqual(get_assistant_name(), "Frag mich")

	def test_empty_setting_falls_back_to_default(self):
		for value in (None, "", "   "):
			with patch.object(utils.frappe.db, "get_single_value", return_value=value):
				self.assertEqual(get_assistant_name(), ASSISTANT_NAME)

	def test_lookup_errors_fall_back_to_default(self):
		with patch.object(utils.frappe.db, "get_single_value", side_effect=RuntimeError("no db")):
			self.assertEqual(get_assistant_name(), ASSISTANT_NAME)
