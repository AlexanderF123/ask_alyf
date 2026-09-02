from frappe.tests import UnitTestCase

from ask_alyf.ask_alyf.utils import (
	AWESOMEBAR_CHAT_DEFAULT,
	AWESOMEBAR_CHAT_DISABLED,
	AWESOMEBAR_CHAT_OFFER,
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
