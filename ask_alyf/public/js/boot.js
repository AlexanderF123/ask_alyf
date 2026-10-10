/**
 * Reads of the Ask ALYF boot payload (`frappe.boot.ask_alyf`), in one place.
 *
 * The payload is built server-side in `api.get_ask_alyf_boot_payload` and
 * delivered with the desk boot, so it is available before the widget starts.
 */

export function getAskAlyfBoot() {
	return frappe?.boot?.ask_alyf || {};
}

export function isAgentModeEnabled() {
	return Boolean(getAskAlyfBoot().agent_mode_enabled);
}

export function isFileUploadEnabled() {
	return Boolean(getAskAlyfBoot().file_upload_enabled);
}

export function isConversationDeletionEnabled() {
	return Boolean(getAskAlyfBoot().conversation_deletion_enabled);
}
