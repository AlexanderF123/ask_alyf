import frappe


def execute():
	"""Keep the Responses API for "OpenAI" settings that use a custom Base URL.

	Before the switch to LangChain provider keys, the "OpenAI" provider always
	used the Responses API, while "OpenAI Compatible" opted in through
	`use_responses_api`. Both become "openai", where a custom Base URL now means
	opt-in. Runs before `use_langchain_provider_keys`, while the old value is
	still stored.
	"""
	provider = frappe.db.get_single_value("Ask ALYF Settings", "llm_provider")
	base_url = (frappe.db.get_single_value("Ask ALYF Settings", "base_url") or "").strip()
	if provider == "OpenAI" and base_url:
		frappe.db.set_single_value("Ask ALYF Settings", "use_responses_api", 1)
