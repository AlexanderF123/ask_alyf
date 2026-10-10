/**
 * Documents dropped onto the chat window or onto the closed chat bubble.
 *
 * The bubble only opens the chat; the panel below it takes the drop. Each
 * dropped file goes through Frappe's own `upload_file` endpoint, so the File
 * record, permissions and server-side size limits are the same as from the
 * file dialog, and is then handed to the widget like a file from that dialog.
 *
 * What it needs from the chat widget:
 *   - panel, bubbleEl, state.loading
 *   - toggle(open)
 *   - openChatWithConversation() -> Promise<boolean>
 *   - onFileUploaded(fileDoc)
 */
import { isFileUploadEnabled } from "./boot";

/** A drag that carries files, and that the settings allow us to accept. */
function isDocumentDrag(event) {
	return isFileUploadEnabled() && Array.from(event.dataTransfer?.types || []).includes("Files");
}

/**
 * The readable text of a failed Frappe request: `_server_messages` is a JSON
 * list of JSON-encoded message objects, not a message.
 */
function getServerMessage(payload) {
	try {
		const messages = JSON.parse(payload?._server_messages || "[]");
		const text = messages
			.map((message) => JSON.parse(message)?.message)
			.filter(Boolean)
			.join("<br>");
		if (text) {
			return text;
		}
	} catch (error) {
		// Not the shape Frappe usually sends; fall through to the generic text.
	}
	return typeof payload?.message === "string" ? payload.message : __("Upload failed.");
}

async function uploadFile(file, conversationName) {
	const form = new FormData();
	form.append("file", file, file.name);
	form.append("is_private", "1");
	form.append("folder", "Home/Attachments");
	form.append("doctype", "Ask ALYF Conversation");
	form.append("docname", conversationName);

	const response = await fetch("/api/method/upload_file", {
		method: "POST",
		headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
		body: form,
	});
	const payload = await response.json().catch(() => ({}));
	if (!response.ok) {
		throw new Error(getServerMessage(payload));
	}
	return payload.message;
}

async function uploadDroppedFiles(widget, files) {
	if (!files.length) {
		return;
	}
	if (widget.state.loading) {
		frappe.show_alert({
			message: __(
				"Ask ALYF is still working on the previous message. Please drop the document again when the answer is there."
			),
			indicator: "orange",
		});
		return;
	}
	if (!(await widget.openChatWithConversation())) {
		return;
	}
	for (const file of files) {
		try {
			const fileDoc = await uploadFile(file, widget.state.conversation.name);
			await widget.onFileUploaded(fileDoc);
		} catch (error) {
			frappe.msgprint(error.message || __("Failed to attach file to conversation."));
		}
	}
}

export function setupDropZone(widget) {
	const { panel, bubbleEl } = widget;
	const overlay = document.createElement("div");
	overlay.className = "ask_alyf-dropzone ask_alyf-hidden";
	overlay.innerHTML = `<div class="ask_alyf-dropzone-label">${__(
		"Drop the document here for Ask ALYF"
	)}</div>`;
	panel.appendChild(overlay);

	// dragleave also fires when the pointer moves onto a child, so count
	// enter and leave instead of hiding on the first leave.
	let depth = 0;
	const setDepth = (value) => {
		depth = Math.max(0, value);
		overlay.classList.toggle("ask_alyf-hidden", !depth);
	};

	panel.addEventListener("dragenter", (event) => {
		if (isDocumentDrag(event)) {
			event.preventDefault();
			setDepth(depth + 1);
		}
	});
	panel.addEventListener("dragleave", () => setDepth(depth - 1));
	panel.addEventListener("dragover", (event) => {
		if (isDocumentDrag(event)) {
			event.preventDefault();
			event.dataTransfer.dropEffect = "copy";
		}
	});
	panel.addEventListener("drop", (event) => {
		if (!isDocumentDrag(event)) {
			return;
		}
		event.preventDefault();
		setDepth(0);
		uploadDroppedFiles(widget, Array.from(event.dataTransfer.files || []));
	});

	bubbleEl.addEventListener("dragenter", (event) => {
		if (isDocumentDrag(event)) {
			event.preventDefault();
			widget.toggle(true);
		}
	});
	bubbleEl.addEventListener("dragover", (event) => {
		if (isDocumentDrag(event)) {
			event.preventDefault();
		}
	});
}
