(function () {
	if (window.ask_alyfWidget) {
		return;
	}

	class ask_alyfWidget {
		constructor() {
			this.state = {
				open: false,
				loading: false,
				conversation: null,
				conversations: [],
				messages: [],
				pendingAction: null,
				status: "",
				mode: localStorage.getItem("ask_alyf-mode") || "Read-Only",
			};
			this.pendingStreamMessageId = null;
			this.resizeState = null;
			this.preventConversationAutocompleteReopen = false;
			this.boundResizeMove = (event) => this.resizePanel(event);
			this.boundResizeEnd = (event) => this.stopPanelResize(event);
		}

		init() {
			if (this.initialized || !frappe?.boot?.ask_alyf?.allowed) {
				return;
			}

			if (this.state.mode === "Edit-Mode" && !frappe.boot.ask_alyf.edit_mode_enabled) {
				this.state.mode = "Read-Only";
			}

			this.initialized = true;
			this.make();
			this.bindRealtime();
			this.bindRouteChange();
			this.loadBootstrap();
		}

		make() {
			const root = document.createElement("div");
			root.className = "ask_alyf-root";
			root.innerHTML = `
				<button class="ask_alyf-bubble" type="button" title="${__("Open Ask ALYF")}" aria-label="${__(
				"Open Ask ALYF"
			)}"><img class="ask_alyf-bubble-logo" src="/assets/ask_alyf/img/logo.png" alt="" aria-hidden="true"></button>
				<div class="ask_alyf-panel ask_alyf-hidden">
					<div class="ask_alyf-resize-handle" title="${__("Resize chat window")}"></div>
					<div class="ask_alyf-header">
						<div>
							<div class="ask_alyf-title">Ask ALYF</div>
							<div class="ask_alyf-subtitle">${__("ERPNext assistant")}</div>
						</div>
						<div class="ask_alyf-actions">
							<button class="ask_alyf-header-button ask_alyf-new-chat" type="button" title="${__(
								"Start a new conversation"
							)}" aria-label="${__("New chat")}">${__("New chat")}</button>
							<button class="ask_alyf-header-button ask_alyf-close" type="button" title="${__(
								"Close"
							)}" aria-label="${__("Close")}">&times;</button>
						</div>
					</div>
					<div class="ask_alyf-toolbar">
						<div class="ask_alyf-conversation-field"></div>
						<div class="ask_alyf-mode-field"></div>
					</div>
					<div class="ask_alyf-config-warning ask_alyf-hidden"></div>
					<div class="ask_alyf-messages"></div>
					<div class="ask_alyf-composer">
						<div class="ask_alyf-input-shell">
							<textarea class="ask_alyf-input" rows="3" placeholder="${__(
								"Ask about this ERPNext instance"
							)}"></textarea>
							<div class="ask_alyf-composer-actions">
								<button class="ask_alyf-icon-button ask_alyf-mic" type="button" title="${__(
									"Voice input"
								)}" aria-label="${__(
				"Voice input"
			)}"><i class="fa fa-microphone"></i></button>
								<button class="ask_alyf-send" type="button">${__("Send")}</button>
							</div>
						</div>
					</div>
				</div>
			`;

			document.body.appendChild(root);

			this.root = root;
			this.panel = root.querySelector(".ask_alyf-panel");
			this.messagesEl = root.querySelector(".ask_alyf-messages");
			this.warningEl = root.querySelector(".ask_alyf-config-warning");
			this.inputEl = root.querySelector(".ask_alyf-input");
			this.conversationFieldEl = root.querySelector(".ask_alyf-conversation-field");
			this.modeFieldEl = root.querySelector(".ask_alyf-mode-field");
			this.bubbleEl = root.querySelector(".ask_alyf-bubble");
			this.micEl = root.querySelector(".ask_alyf-mic");
			this.resizeHandleEl = root.querySelector(".ask_alyf-resize-handle");

			this.conversationControl = frappe.ui.form.make_control({
				parent: this.conversationFieldEl,
				df: {
					fieldname: "ask_alyf_conversation",
					fieldtype: "Autocomplete",
					label: __("Conversation"),
					placeholder: __("Search conversations"),
					options: [],
					onchange: () => this.onConversationChange(),
				},
				render_input: true,
			});
			this.conversationControl.$input.on("mousedown", (event) =>
				this.onConversationInputMouseDown(event)
			);
			this.conversationControl.$input.on("input", () => this.onConversationInputTyping());
			this.conversationControl.$input.on("awesomplete-open", () =>
				this.onConversationAutocompleteOpen()
			);
			this.conversationControl.$input.on("awesomplete-selectcomplete", () =>
				this.onConversationAutocompleteSelect()
			);
			this.modeControl = frappe.ui.form.make_control({
				parent: this.modeFieldEl,
				df: {
					fieldname: "ask_alyf_edit_mode",
					fieldtype: "Check",
					label: __("Edit-Mode"),
					default: 0,
					onchange: () => this.onModeChange(),
				},
				render_input: true,
			});
			this.syncModeControl();
			if (!frappe.boot.ask_alyf.edit_mode_enabled) {
				this.modeControl.$input.prop("disabled", true);
			}

			root.querySelector(".ask_alyf-bubble").addEventListener("click", () =>
				this.toggle(true)
			);
			root.querySelector(".ask_alyf-close").addEventListener("click", () =>
				this.toggle(false)
			);
			root.querySelector(".ask_alyf-send").addEventListener("click", () =>
				this.sendMessage()
			);
			root.querySelector(".ask_alyf-new-chat").addEventListener("click", () =>
				this.startNewConversation()
			);
			this.micEl.addEventListener("click", () => this.startVoiceInput());
			this.resizeHandleEl.addEventListener("pointerdown", (event) =>
				this.startPanelResize(event)
			);
			this.inputEl.addEventListener("keydown", (event) => {
				if (event.key === "Enter" && !event.shiftKey) {
					event.preventDefault();
					this.sendMessage();
				}
			});
			this.inputEl.addEventListener("input", () => this.autoResizeInput());
			this.updateVoiceInputHint();
			this.autoResizeInput();
		}

		bindRealtime() {
			frappe.realtime.on("ask_alyf_status", (message) => {
				if (message.conversation !== this.state.conversation?.name) return;
				this.setStatus(message.text || "");
			});

			frappe.realtime.on("ask_alyf_response_start", (message) => {
				if (message.conversation !== this.state.conversation?.name) return;
				this.setLoading(true);
				this.setStatus(__("Thinking..."));
			});

			frappe.realtime.on("ask_alyf_response_chunk", (message) => {
				if (message.conversation !== this.state.conversation?.name) return;
				this.appendAssistantChunk(message.message_id, message.chunk || "");
			});

			frappe.realtime.on("ask_alyf_response_complete", (message) => {
				if (message.conversation !== this.state.conversation?.name) return;
				this.setLoading(false);
				this.setStatus("");
				this.state.pendingAction = message.pending_action || null;
				this.pendingStreamMessageId = null;
				this.renderMessages();
				this.refreshConversationList();
			});
		}

		bindRouteChange() {
			frappe.router.on("change", () => {
				if (this.state.open) {
					this.setStatus("");
				}
			});
		}

		async loadBootstrap() {
			const response = await frappe.call({
				method: "ask_alyf.api.bootstrap",
				args: {
					conversation: this.state.conversation?.name,
				},
			});
			this.applyConversation(response.message.conversation);
			await this.refreshConversationList();

			if (!response.message.ask_alyf.configured) {
				this.warningEl.classList.remove("ask_alyf-hidden");
				this.warningEl.textContent = __(
					"Ask ALYF is visible, but no API key/model is configured yet in Ask ALYF Settings."
				);
			}
		}

		applyConversation(conversation) {
			this.state.conversation = conversation;
			this.state.messages = conversation.messages || [];
			this.state.pendingAction = conversation.pending_action || null;
			this.state.mode = conversation.mode || this.state.mode;
			if (this.state.mode === "Edit-Mode" && !frappe.boot.ask_alyf.edit_mode_enabled) {
				this.state.mode = "Read-Only";
			}
			this.syncModeControl();
			this.renderConversationOptions();
			this.renderMessages();
		}

		onConversationChange() {
			const conversationName = this.conversationControl?.get_value();
			if (!conversationName || conversationName === this.state.conversation?.name) {
				this.renderConversationOptions();
				return;
			}
			this.openConversation(conversationName);
		}

		onModeChange() {
			this.state.mode = this.modeControl?.get_value() ? "Edit-Mode" : "Read-Only";
			localStorage.setItem("ask_alyf-mode", this.state.mode);
		}

		syncModeControl() {
			if (!this.modeControl) {
				return;
			}
			this.modeControl.set_input(this.state.mode === "Edit-Mode" ? 1 : 0);
		}

		onConversationInputMouseDown(event) {
			if (event.button !== undefined && event.button !== 0) {
				return;
			}

			this.preventConversationAutocompleteReopen = false;
			this.openConversationAutocomplete();
		}

		onConversationInputTyping() {
			this.preventConversationAutocompleteReopen = false;
		}

		onConversationAutocompleteOpen() {
			if (!this.preventConversationAutocompleteReopen) {
				return;
			}
			this.closeConversationAutocomplete();
		}

		onConversationAutocompleteSelect() {
			this.preventConversationAutocompleteReopen = true;
			this.closeConversationAutocomplete();
		}

		openConversationAutocomplete() {
			const autocomplete = this.conversationControl?.awesomplete;
			if (!autocomplete) {
				return;
			}

			const originalFilter = autocomplete.filter;
			try {
				autocomplete.filter = () => true;
				autocomplete.evaluate();
			} finally {
				autocomplete.filter = originalFilter;
			}
		}

		closeConversationAutocomplete() {
			this.conversationControl?.awesomplete?.close();
		}

		formatConversationLabel(conversation) {
			const title = (conversation.title || "").trim() || __("Untitled conversation");
			return `${title}`;
		}

		renderConversationOptions() {
			if (!this.conversationControl) {
				return;
			}

			const currentName = this.state.conversation?.name || "";
			const options = [...(this.state.conversations || [])];
			if (
				currentName &&
				!options.some((conversation) => conversation.name === currentName)
			) {
				options.unshift({
					name: currentName,
					title: this.state.conversation?.title || __("Current conversation"),
				});
			}

			const autocompleteOptions = options
				.filter((conversation) => conversation?.name)
				.map((conversation) => ({
					value: conversation.name,
					label: this.formatConversationLabel(conversation),
				}));

			this.conversationControl.set_data(autocompleteOptions);
			this.conversationControl.set_input(currentName || "");
		}

		async refreshConversationList() {
			try {
				const response = await frappe.call({
					method: "ask_alyf.api.list_conversations",
					args: { limit: 30 },
				});
				this.state.conversations = response.message || [];
				this.renderConversationOptions();
			} catch {
				// Ignore list refresh errors to keep chat usable.
			}
		}

		async openConversation(conversationName) {
			this.setLoading(true);
			this.setStatus(__("Loading conversation..."));

			try {
				const response = await frappe.call({
					method: "ask_alyf.api.bootstrap",
					args: { conversation: conversationName },
				});
				this.applyConversation(response.message.conversation);
				this.setStatus("");
			} catch (error) {
				this.setStatus("");
				frappe.msgprint(error.message || __("Failed to open conversation."));
				this.renderConversationOptions();
			} finally {
				this.setLoading(false);
			}
		}

		toggle(open) {
			this.state.open = open;
			this.panel.classList.toggle("ask_alyf-hidden", !open);
			this.bubbleEl.classList.toggle("ask_alyf-hidden", open);
			if (open) {
				this.autoResizeInput();
				this.inputEl.focus();
				this.refreshConversationList();
			} else {
				this.stopPanelResize();
			}
		}

		setLoading(value) {
			this.state.loading = value;
			this.root.classList.toggle("ask_alyf-loading", value);
		}

		setStatus(text) {
			if ((text || "") === this.state.status) {
				return;
			}
			this.state.status = text || "";
			this.renderMessages();
		}

		getCurrentContext() {
			const route = frappe.get_route() || [];
			const context = {
				route: route.join("/"),
				route_parts: route,
				lang: frappe.boot.lang || document.documentElement.lang || "en",
				locale: navigator.language || "en",
			};

			if (route[0] === "Form" && window.cur_frm?.doc) {
				context.current_doctype = cur_frm.doc.doctype;
				context.current_docname = cur_frm.doc.name;
			}

			if (route[0] === "List" && window.cur_list?.filter_area) {
				context.list_filters = cur_list.filter_area
					.get()
					.map((filter) => filter.slice(0, 4));
				context.list_doctype = cur_list.doctype;
			}

			return context;
		}

		autoResizeInput() {
			if (!this.inputEl) {
				return;
			}

			this.inputEl.style.height = "auto";
			const computedMinHeight = Number.parseFloat(getComputedStyle(this.inputEl).minHeight);
			const computedMaxHeight = Number.parseFloat(getComputedStyle(this.inputEl).maxHeight);
			const minHeight = Number.isFinite(computedMinHeight) ? computedMinHeight : 0;
			const maxHeight = Number.isFinite(computedMaxHeight)
				? computedMaxHeight
				: this.inputEl.scrollHeight || minHeight;
			const contentHeight = this.inputEl.scrollHeight || minHeight;
			const nextHeight = Math.max(minHeight, Math.min(contentHeight, maxHeight));

			this.inputEl.style.height = `${nextHeight}px`;
			this.inputEl.style.overflowY =
				this.inputEl.scrollHeight > nextHeight ? "auto" : "hidden";
		}

		startPanelResize(event) {
			if (event.button !== undefined && event.button !== 0) {
				return;
			}

			event.preventDefault();
			const panelRect = this.panel.getBoundingClientRect();
			const bounds = this.getPanelResizeBounds();
			this.resizeState = {
				pointerId: event.pointerId,
				startX: event.clientX,
				startY: event.clientY,
				startWidth: panelRect.width,
				startHeight: panelRect.height,
				...bounds,
			};
			this.root.classList.add("ask_alyf-resizing");

			if (this.resizeHandleEl?.setPointerCapture) {
				try {
					this.resizeHandleEl.setPointerCapture(event.pointerId);
				} catch {
					// Ignore pointer capture failures.
				}
			}

			window.addEventListener("pointermove", this.boundResizeMove);
			window.addEventListener("pointerup", this.boundResizeEnd);
			window.addEventListener("pointercancel", this.boundResizeEnd);
		}

		resizePanel(event) {
			if (!this.resizeState) {
				return;
			}

			if (event.pointerId !== undefined && event.pointerId !== this.resizeState.pointerId) {
				return;
			}

			event.preventDefault();
			const deltaX = this.resizeState.startX - event.clientX;
			const deltaY = this.resizeState.startY - event.clientY;
			const nextWidth = this.clamp(
				this.resizeState.startWidth + deltaX,
				this.resizeState.minWidth,
				this.resizeState.maxWidth
			);
			const nextHeight = this.clamp(
				this.resizeState.startHeight + deltaY,
				this.resizeState.minHeight,
				this.resizeState.maxHeight
			);

			this.panel.style.width = `${nextWidth}px`;
			this.panel.style.height = `${nextHeight}px`;
		}

		stopPanelResize(event) {
			if (!this.resizeState) {
				return;
			}

			if (
				event?.pointerId !== undefined &&
				this.resizeState.pointerId !== undefined &&
				event.pointerId !== this.resizeState.pointerId
			) {
				return;
			}

			if (event?.pointerId !== undefined && this.resizeHandleEl?.releasePointerCapture) {
				try {
					this.resizeHandleEl.releasePointerCapture(event.pointerId);
				} catch {
					// Ignore pointer capture release failures.
				}
			}

			this.resizeState = null;
			this.root.classList.remove("ask_alyf-resizing");
			window.removeEventListener("pointermove", this.boundResizeMove);
			window.removeEventListener("pointerup", this.boundResizeEnd);
			window.removeEventListener("pointercancel", this.boundResizeEnd);
		}

		getPanelResizeBounds() {
			const styles = getComputedStyle(this.panel);
			const minWidth = Number.parseFloat(styles.minWidth);
			const minHeight = Number.parseFloat(styles.minHeight);
			const maxWidth = Number.parseFloat(styles.maxWidth);
			const maxHeight = Number.parseFloat(styles.maxHeight);
			const fallbackMaxWidth = Math.max(window.innerWidth - 16, 280);
			const fallbackMaxHeight = Math.max(window.innerHeight - 16, 320);
			const resolvedMinWidth = Number.isFinite(minWidth) ? minWidth : 280;
			const resolvedMinHeight = Number.isFinite(minHeight) ? minHeight : 320;
			const resolvedMaxWidth = Number.isFinite(maxWidth) ? maxWidth : fallbackMaxWidth;
			const resolvedMaxHeight = Number.isFinite(maxHeight) ? maxHeight : fallbackMaxHeight;

			return {
				minWidth: resolvedMinWidth,
				minHeight: resolvedMinHeight,
				maxWidth: Math.max(resolvedMinWidth, resolvedMaxWidth),
				maxHeight: Math.max(resolvedMinHeight, resolvedMaxHeight),
			};
		}

		clamp(value, min, max) {
			return Math.min(Math.max(value, min), max);
		}

		async sendMessage() {
			const text = this.inputEl.value.trim();
			if (!text || this.state.loading) {
				return;
			}

			this.toggle(true);
			this.setLoading(true);
			this.setStatus(__("Sending..."));

			const optimisticMessage = {
				id: `local-${Date.now()}`,
				role: "user",
				content: text,
			};
			this.state.messages.push(optimisticMessage);
			this.renderMessages();
			this.inputEl.value = "";
			this.autoResizeInput();

			try {
				const response = await frappe.call({
					method: "ask_alyf.api.send_message",
					type: "POST",
					args: {
						message: text,
						mode: this.state.mode,
						conversation: this.state.conversation?.name,
						context: this.getCurrentContext(),
					},
				});
				if (response.message.conversation) {
					this.state.conversation = {
						...(this.state.conversation || {}),
						name: response.message.conversation,
					};
				}
				this.refreshConversationList();
				this.setStatus(__("Waiting for response..."));
			} catch (error) {
				this.setLoading(false);
				this.setStatus("");
				frappe.msgprint(error.message || __("Failed to send message."));
			}
		}

		appendAssistantChunk(messageId, chunk) {
			let message = this.state.messages.find((item) => item.id === messageId);
			if (!message) {
				message = { id: messageId, role: "assistant", content: "" };
				this.state.messages.push(message);
			}

			message.content += chunk;
			this.pendingStreamMessageId = messageId;
			this.renderMessages();
			this.scrollToBottom();
		}

		async startNewConversation() {
			const response = await frappe.call({
				method: "ask_alyf.api.start_new_conversation",
				type: "POST",
				args: {
					mode: this.state.mode,
				},
			});
			this.applyConversation(response.message);
			this.refreshConversationList();
			this.setStatus("");
		}

		async confirmPendingAction() {
			if (!this.state.pendingAction || !this.state.conversation?.name) return;

			const response = await frappe.call({
				method: "ask_alyf.api.confirm_pending_action",
				type: "POST",
				args: { conversation: this.state.conversation.name },
			});
			this.applyConversation(response.message.conversation);
			this.refreshConversationList();
		}

		async rejectPendingAction() {
			if (!this.state.conversation?.name) return;

			const response = await frappe.call({
				method: "ask_alyf.api.reject_pending_action",
				type: "POST",
				args: { conversation: this.state.conversation.name },
			});
			this.applyConversation(response.message.conversation);
			this.refreshConversationList();
		}

		renderMessages() {
			this.messagesEl.innerHTML = "";

			this.state.messages.forEach((message) => {
				const wrapper = document.createElement("div");
				wrapper.className = `ask_alyf-message ask_alyf-${message.role}`;

				const body = document.createElement("div");
				body.className = "ask_alyf-message-body";
				body.innerHTML =
					message.role === "assistant"
						? frappe.markdown(message.content || "")
						: this.escapeHtml(message.content || "").replace(/\n/g, "<br>");
				wrapper.appendChild(body);

				this.messagesEl.appendChild(wrapper);
			});

			if (this.state.status) {
				const statusWrapper = document.createElement("div");
				statusWrapper.className = "ask_alyf-message ask_alyf-status-message";

				const statusBody = document.createElement("div");
				statusBody.className = "ask_alyf-message-body";
				statusBody.textContent = this.state.status;

				statusWrapper.appendChild(statusBody);
				this.messagesEl.appendChild(statusWrapper);
			}

			if (this.state.pendingAction) {
				const proposal = document.createElement("div");
				proposal.className = "ask_alyf-proposal";
				proposal.innerHTML = `
					<div class="ask_alyf-proposal-title">${__("Pending action")}</div>
					<div class="ask_alyf-proposal-summary">${this.escapeHtml(
						this.state.pendingAction.summary || this.state.pendingAction.action || ""
					)}</div>
					<div class="ask_alyf-proposal-actions">
						<button class="ask_alyf-confirm" type="button">${__("Confirm")}</button>
						<button class="ask_alyf-reject" type="button">${__("Reject")}</button>
					</div>
				`;
				proposal
					.querySelector(".ask_alyf-confirm")
					.addEventListener("click", () => this.confirmPendingAction());
				proposal
					.querySelector(".ask_alyf-reject")
					.addEventListener("click", () => this.rejectPendingAction());
				this.messagesEl.appendChild(proposal);
			}

			this.scrollToBottom();
		}

		scrollToBottom() {
			this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
		}

		startVoiceInput() {
			const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
			if (!Recognition) {
				frappe.msgprint(__("Your browser does not support voice input."));
				return;
			}

			const speechLanguage = this.getPreferredSpeechLanguage();
			this.updateVoiceInputHint(speechLanguage);

			const recognition = new Recognition();
			recognition.lang = speechLanguage;
			recognition.interimResults = false;
			recognition.maxAlternatives = 1;
			recognition.onresult = (event) => {
				const transcript = event.results?.[0]?.[0]?.transcript;
				if (transcript) {
					this.inputEl.value = transcript;
					this.autoResizeInput();
				}
			};
			recognition.start();
		}

		updateVoiceInputHint(languageCode = this.getPreferredSpeechLanguage()) {
			if (!this.micEl) {
				return;
			}

			const tooltip = __("Voice input language: {0}", [languageCode]);
			this.micEl.title = tooltip;
			this.micEl.setAttribute("aria-label", tooltip);
		}

		getPreferredSpeechLanguage() {
			const langCandidate =
				frappe?.boot?.lang ||
				document.documentElement.lang ||
				navigator.language ||
				"en-US";
			return this.normalizeSpeechLanguage(langCandidate);
		}

		normalizeSpeechLanguage(lang) {
			const normalized = (lang || "").toString().replace("_", "-").trim();
			if (!normalized) {
				return "en-US";
			}

			const key = normalized.toLowerCase();
			const languageMap = {
				de: "de-DE",
				en: "en-US",
				es: "es-ES",
				fr: "fr-FR",
				it: "it-IT",
				ja: "ja-JP",
				ko: "ko-KR",
				nl: "nl-NL",
				pt: "pt-PT",
				zh: "zh-CN",
				"zh-hans": "zh-CN",
				"zh-hant": "zh-TW",
			};

			if (languageMap[key]) {
				return languageMap[key];
			}

			const [base, region] = normalized.split("-");
			if (base && region) {
				return `${base.toLowerCase()}-${region.toUpperCase()}`;
			}

			if (normalized.length === 2) {
				return `${normalized.toLowerCase()}-${normalized.toUpperCase()}`;
			}

			return "en-US";
		}

		escapeHtml(value) {
			const div = document.createElement("div");
			div.textContent = value;
			return div.innerHTML;
		}
	}

	window.ask_alyfWidget = new ask_alyfWidget();
	$(function () {
		window.ask_alyfWidget.init();
	});
})();
