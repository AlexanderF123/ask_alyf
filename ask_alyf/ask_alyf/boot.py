import frappe

from ask_alyf.ask_alyf.api import get_ask_alyf_boot_payload


def boot_session(bootinfo):
	bootinfo.ask_alyf = get_ask_alyf_boot_payload()
