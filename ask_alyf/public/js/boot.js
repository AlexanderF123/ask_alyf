/**
 * Reads of the Ask ALYF boot payload (`frappe.boot.ask_alyf`), in one place.
 *
 * The payload is built server-side in `api.get_ask_alyf_boot_payload` and
 * delivered with the desk boot, so it is available before the widget starts.
 */

const DEFAULT_ASSISTANT_NAME = "Frage mich";

export function getAskAlyfBoot() {
	return frappe?.boot?.ask_alyf || {};
}

export function getAssistantName() {
	return getAskAlyfBoot().assistant_name || DEFAULT_ASSISTANT_NAME;
}

export function isAgentModeEnabled() {
	return Boolean(getAskAlyfBoot().agent_mode_enabled);
}

export function isFileUploadEnabled() {
	return Boolean(getAskAlyfBoot().file_upload_enabled);
}
