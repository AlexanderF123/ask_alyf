/**
 * The desk search bar (Awesomebar) as an input for the assistant.
 *
 * Frappe rebuilds the dropdown in `AwesomeBar.add_defaults` on every
 * keystroke, so wrapping that method is enough to add our own entry; the
 * entry's `onclick` receives `match`, which is the typed text. On top of that
 * entry this module owns a composer that folds out below the search bar for
 * longer texts, a microphone button, and an entry that opens the file
 * uploader when the typed text mentions a document.
 *
 * What it needs from the chat widget is deliberately small:
 *   - sendMessageFromText(text)
 *   - openFileUploaderFromAwesomebar()
 *   - startVoiceRecognition({ onListening, onResult })
 *   - isSpeechRecognitionAvailable()
 */
import { getAskAlyfBoot, getAssistantName, isFileUploadEnabled } from "./boot";

export const MODE_DISABLED = "Disabled";
export const MODE_OFFER = "Offer in Results";
export const MODE_DEFAULT = "Default Action";
const MODES = new Set([MODE_DISABLED, MODE_OFFER, MODE_DEFAULT]);

// Awesomplete sorts by index and `autoFirst` selects the highest one;
// Frappe's own "Search for ..." entry sits at 100.
const INDEX_DEFAULT = 110;
const INDEX_UPLOAD = 96;
const INDEX_OFFER = 95;

// A leading "?" always means "send this to the assistant".
const PREFIX = "?";

const UPLOAD_PATTERN = /(upload|hochlad|datei|dokument|anhang|anh[äa]ng|beleg|scan|attach|file\b|document)/i;

const COMPOSER_MAX_HEIGHT = 320;
const NAVBAR_RETRIES = 10;
const NAVBAR_RETRY_MS = 500;

export function getAwesomebarChatMode() {
	const boot = getAskAlyfBoot();
	if (!boot.allowed) {
		return MODE_DISABLED;
	}
	const mode = String(boot.awesomebar_chat || "");
	return MODES.has(mode) ? mode : MODE_DISABLED;
}

/** The text as the single-line search input shows it. */
export function flattenText(text) {
	return (text || "").replace(/\s*\n\s*/g, " ").trim();
}

/** The navbar is rendered by the desk, so wait for the search input. */
function whenNavbarSearchReady(callback, attempt = 0) {
	const input = document.getElementById("navbar-search");
	if (input?.parentElement) {
		callback(input);
		return;
	}
	if (attempt < NAVBAR_RETRIES) {
		setTimeout(() => whenNavbarSearchReady(callback, attempt + 1), NAVBAR_RETRY_MS);
	}
}

class AwesomebarChat {
	constructor(widget) {
		this.widget = widget;
		this.inputEl = null;
		this.composerEl = null;
		this.textareaEl = null;
		this.micEl = null;
		this.draft = "";
		this.composerDismissed = false;
	}

	install() {
		this.patchOptions();
		whenNavbarSearchReady((input) => {
			this.inputEl = input;
			this.mountComposer(input);
			this.mountVoiceButton(input);
		});
	}

	/** Add our entries to the dropdown. The prototype is patched once per page. */
	patchOptions() {
		const AwesomeBar = frappe.search?.AwesomeBar;
		if (!AwesomeBar?.prototype || AwesomeBar.prototype._askAlyfChatPatched) {
			return;
		}
		const originalAddDefaults = AwesomeBar.prototype.add_defaults;
		if (typeof originalAddDefaults !== "function") {
			return;
		}
		const integration = this;
		AwesomeBar.prototype.add_defaults = function (txt) {
			originalAddDefaults.call(this, txt);
			integration.addChatOption(this, txt);
		};
		AwesomeBar.prototype._askAlyfChatPatched = true;
	}

	addChatOption(awesomeBar, txt) {
		const mode = getAwesomebarChatMode();
		if (mode === MODE_DISABLED || !Array.isArray(awesomeBar?.options)) {
			return;
		}
		let text = (txt || "").trim();
		let forced = false;
		if (text.startsWith(PREFIX)) {
			forced = true;
			text = text.slice(PREFIX.length).trim();
		}
		if (!text) {
			return;
		}
		const isDefault = forced || mode === MODE_DEFAULT;
		const safeText = frappe.utils.xss_sanitise(text);
		const name = getAssistantName();
		awesomeBar.options.push({
			label: `
				<span class="flex justify-between text-medium">
					<span class="ellipsis">${__("Send to {0}: {1}", [name, safeText.bold()])}</span>
					${isDefault ? "<kbd>↵</kbd>" : ""}
				</span>
			`,
			value: __("Send to {0}: {1}", [name, safeText]),
			match: text,
			index: isDefault ? INDEX_DEFAULT : INDEX_OFFER,
			default: "AskAlyfChat",
			onclick: (message) => this.widget.sendMessageFromText(message),
		});

		if (isFileUploadEnabled() && UPLOAD_PATTERN.test(text)) {
			awesomeBar.options.push({
				label: `
					<span class="flex justify-between text-medium">
						<span class="ellipsis">${__("Attach a document for {0}", [name])}</span>
					</span>
				`,
				value: __("Attach a document for {0}", [name]),
				match: text,
				index: INDEX_UPLOAD,
				default: "AskAlyfUpload",
				onclick: () => this.widget.openFileUploaderFromAwesomebar(),
			});
		}
	}

	/**
	 * Name the assistant in the placeholder and add the composer that folds
	 * out below the search bar for longer texts.
	 *
	 * The composer opens when the typed text no longer fits into the input,
	 * on Shift+Enter, or when multi-line text is pasted. Enter sends the text
	 * to the assistant, Shift+Enter adds a line, Escape folds it back.
	 */
	mountComposer(input) {
		if (input.parentElement.querySelector(".ask_alyf-awesomebar-composer")) {
			return;
		}
		const name = getAssistantName();
		const shortcut = frappe.utils.is_mac?.() ? "⌘ + G" : "Ctrl + G";
		input.placeholder = __("{0}, search or type a command ({1})", [name, shortcut]);

		const composer = document.createElement("div");
		composer.className = "ask_alyf-awesomebar-composer";
		composer.hidden = true;
		const textareaLabel = frappe.utils.escape_html(__("Your question or task for {0}", [name]));
		composer.innerHTML = `
			<textarea
				class="ask_alyf-awesomebar-textarea"
				rows="2"
				placeholder="${textareaLabel}"
				aria-label="${textareaLabel}"
			></textarea>
			<div class="ask_alyf-awesomebar-composer-footer">
				<span class="ask_alyf-awesomebar-composer-hint">${__(
					"Enter sends to {0}, Shift + Enter adds a line, Esc closes",
					[name]
				)}</span>
				<button type="button" class="btn btn-primary btn-xs ask_alyf-awesomebar-send">${__("Send")}</button>
			</div>
		`;
		input.parentElement.classList.add("ask_alyf-has-awesomebar-composer");
		input.parentElement.appendChild(composer);
		this.composerEl = composer;
		this.textareaEl = composer.querySelector("textarea");

		// Capture runs before Awesomplete's own Enter handler on the same
		// input, so Shift+Enter never selects a result.
		input.addEventListener(
			"keydown",
			(event) => {
				if (event.key !== "Enter" || !event.shiftKey) {
					return;
				}
				event.preventDefault();
				event.stopPropagation();
				this.composerDismissed = false;
				this.openComposer(`${this.getDraft()}\n`);
			},
			true
		);
		input.addEventListener("input", () => {
			if (!input.value.trim()) {
				this.draft = "";
				this.composerDismissed = false;
				return;
			}
			if (this.composerDismissed || !this.shouldOpenComposer(input)) {
				return;
			}
			this.openComposer(this.getDraft());
		});
		input.addEventListener("blur", () => {
			this.composerDismissed = false;
		});

		const textarea = this.textareaEl;
		textarea.addEventListener("input", () => this.autoResizeComposer());
		textarea.addEventListener("keydown", (event) => {
			if (event.key === "Enter" && !event.shiftKey) {
				event.preventDefault();
				event.stopPropagation();
				this.submitComposer();
			} else if (event.key === "Escape") {
				event.preventDefault();
				event.stopPropagation();
				this.composerDismissed = true;
				this.closeComposer({ focusInput: true });
			}
		});
		composer.querySelector(".ask_alyf-awesomebar-send").addEventListener("click", (event) => {
			event.preventDefault();
			this.submitComposer();
		});
		composer.addEventListener("focusout", (event) => {
			const next = event.relatedTarget;
			if (next && (composer.contains(next) || next.classList?.contains("ask_alyf-navbar-mic"))) {
				return;
			}
			this.closeComposer();
		});
	}

	isComposerOpen() {
		return Boolean(this.composerEl && !this.composerEl.hidden);
	}

	/** Full text behind the single-line search input, including line breaks. */
	getDraft() {
		const value = this.inputEl?.value || "";
		if (this.draft && flattenText(this.draft) === value.trim()) {
			return this.draft;
		}
		return value;
	}

	shouldOpenComposer(input) {
		const value = input.value || "";
		const forced = value.trimStart().startsWith(PREFIX);
		if (getAwesomebarChatMode() !== MODE_DEFAULT && !forced) {
			return false;
		}
		if (value.includes("\n")) {
			return true;
		}
		return input.scrollWidth > input.clientWidth + 1;
	}

	openComposer(text) {
		const { composerEl: composer, textareaEl: textarea, inputEl: input } = this;
		if (!composer || !textarea || !input) {
			return;
		}
		input.awesomplete?.close?.();
		textarea.value = text || "";
		composer.hidden = false;
		input.parentElement.classList.add("is-composing");
		this.autoResizeComposer();
		textarea.focus();
		const end = textarea.value.length;
		textarea.setSelectionRange(end, end);
	}

	/**
	 * Fold the composer back. The text is kept: the search input shows it on
	 * one line and the full draft (with line breaks) is restored when the
	 * composer opens again.
	 */
	closeComposer({ clear = false, focusInput = false } = {}) {
		const { composerEl: composer, textareaEl: textarea, inputEl: input } = this;
		if (!composer || composer.hidden) {
			return;
		}
		const text = clear ? "" : textarea.value;
		this.draft = text;
		input.value = flattenText(text);
		textarea.value = "";
		composer.hidden = true;
		input.parentElement.classList.remove("is-composing");
		if (focusInput) {
			input.focus();
		}
	}

	autoResizeComposer() {
		const textarea = this.textareaEl;
		if (!textarea) {
			return;
		}
		textarea.style.height = "auto";
		textarea.style.height = `${Math.min(textarea.scrollHeight, COMPOSER_MAX_HEIGHT)}px`;
		textarea.style.overflowY = textarea.scrollHeight > COMPOSER_MAX_HEIGHT ? "auto" : "hidden";
	}

	async submitComposer() {
		let text = (this.textareaEl?.value || "").trim();
		if (text.startsWith(PREFIX)) {
			text = text.slice(PREFIX.length).trim();
		}
		if (!text) {
			return;
		}
		this.closeComposer({ clear: true });
		this.inputEl?.blur();
		await this.widget.sendMessageFromText(text);
	}

	/**
	 * A microphone next to the search input, so a question can be spoken
	 * instead of typed. The transcript lands in the composer when it is open,
	 * otherwise in the search input, where Enter sends it like typed text.
	 */
	mountVoiceButton(input) {
		if (!this.widget.isSpeechRecognitionAvailable()) {
			return;
		}
		if (input.parentElement.querySelector(".ask_alyf-navbar-mic")) {
			return;
		}
		const button = document.createElement("button");
		button.type = "button";
		button.className = "ask_alyf-navbar-mic";
		button.innerHTML =
			typeof frappe.utils?.icon === "function"
				? frappe.utils.icon("mic", "sm", "", "", "", true)
				: "";
		const tooltip = __("Voice input for {0}", [getAssistantName()]);
		button.title = tooltip;
		button.setAttribute("aria-label", tooltip);
		button.setAttribute("aria-pressed", "false");
		button.addEventListener("click", (event) => {
			event.preventDefault();
			event.stopPropagation();
			this.startVoiceInput(input, button);
		});
		input.parentElement.classList.add("ask_alyf-has-navbar-mic");
		input.insertAdjacentElement("afterend", button);
		this.micEl = button;
	}

	startVoiceInput(input, button) {
		this.widget.startVoiceRecognition({
			onListening: (isListening) => {
				button.classList.toggle("is-listening", isListening);
				button.setAttribute("aria-pressed", isListening ? "true" : "false");
			},
			onResult: (transcript) => {
				if (this.isComposerOpen()) {
					const textarea = this.textareaEl;
					const current = textarea.value.trimEnd();
					textarea.value = current ? `${current} ${transcript}` : transcript;
					this.autoResizeComposer();
					textarea.focus();
					return;
				}
				input.value =
					getAwesomebarChatMode() === MODE_DEFAULT ? transcript : `${PREFIX} ${transcript}`;
				input.focus();
				input.dispatchEvent(new Event("input", { bubbles: true }));
			},
		});
	}
}

/**
 * Wire the search bar up to the chat widget. Returns nothing when the feature
 * is switched off in the settings, which leaves the search bar untouched.
 */
export function setupAwesomebarIntegration(widget) {
	if (getAwesomebarChatMode() === MODE_DISABLED) {
		return null;
	}
	const integration = new AwesomebarChat(widget);
	integration.install();
	return integration;
}
