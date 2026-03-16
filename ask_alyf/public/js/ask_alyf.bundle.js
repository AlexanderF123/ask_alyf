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
				activeTab: "chat",
				messages: [],
				pendingOperation: null,
				status: "",
				mode: "Ask",
			};
			this.pendingStreamMessageId = null;
			this.renderedMessageKeys = new Set();
			this.handledFrontendCallIds = new Set();
			this.resizeState = null;
			this.voiceRecognition = null;
			this.boundResizeMove = (event) => this.resizePanel(event);
			this.boundResizeEnd = (event) => this.stopPanelResize(event);
			this.boundDocumentClick = (event) => this.onDocumentClick(event);
		}

		init() {
			if (this.initialized || !frappe?.boot?.ask_alyf?.allowed) {
				return;
			}

			if (this.state.mode === "Agent" && !this.isAgentModeEnabled()) {
				this.state.mode = "Ask";
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
							<button class="ask_alyf-header-button ask_alyf-new-chat btn btn-secondary btn-sm" type="button" title="${__(
								"Start a new conversation"
							)}" aria-label="${__("New chat")}">${__("New chat")}</button>
							<a class="ask_alyf-header-button ask_alyf-support-phone btn btn-secondary btn-sm ask_alyf-hidden" href="#" role="button" title="${__(
								"Call support"
							)}" aria-label="${__(
				"Call support"
			)}"><i class="fa fa-phone" aria-hidden="true"></i></a>
							<button class="ask_alyf-header-button ask_alyf-close btn btn-secondary btn-sm" type="button" title="${__(
								"Close"
							)}" aria-label="${__("Close")}">&times;</button>
						</div>
					</div>
					<div class="form-tabs-list ask_alyf-tabs-list">
						<ul class="nav form-tabs ask_alyf-tabs" role="tablist" aria-label="${__("Ask ALYF sections")}">
							<li class="nav-item">
								<button class="nav-link ask_alyf-tab active" type="button" role="tab" data-tab="chat" aria-selected="true">${__(
									"Chat"
								)}</button>
							</li>
							<li class="nav-item">
								<button class="nav-link ask_alyf-tab" type="button" role="tab" data-tab="history" aria-selected="false">${__(
									"History"
								)}</button>
							</li>
						</ul>
					</div>
					<div class="ask_alyf-config-warning ask_alyf-hidden"></div>
					<div class="ask_alyf-chat-view">
						<div class="ask_alyf-messages"></div>
						<div class="ask_alyf-composer">
							<div class="ask_alyf-input-shell">
								<textarea class="ask_alyf-input" rows="3" placeholder="${__(
									"Ask about this ERPNext instance"
								)}"></textarea>
								<div class="ask_alyf-mode-dropdown">
									<button class="ask_alyf-mode-trigger btn btn-secondary btn-sm" type="button" aria-haspopup="menu" aria-expanded="false">
										<span class="ask_alyf-mode-trigger-label"></span>
										<i class="fa fa-chevron-down ask_alyf-mode-trigger-chevron" aria-hidden="true"></i>
									</button>
									<div class="ask_alyf-mode-menu ask_alyf-hidden" role="menu">
										<button class="ask_alyf-mode-option btn btn-secondary btn-sm" type="button" role="menuitemradio" data-mode="Ask">${__(
											"Ask"
										)}</button>
										<button class="ask_alyf-mode-option btn btn-secondary btn-sm" type="button" role="menuitemradio" data-mode="Agent">${__(
											"Agent"
										)}</button>
									</div>
								</div>
								<div class="ask_alyf-composer-actions">
									<button class="ask_alyf-icon-button ask_alyf-mic btn btn-secondary btn-sm" type="button" title="${__(
										"Voice input"
									)}" aria-label="${__(
				"Voice input"
			)}"><i class="fa fa-microphone"></i></button>
									<button class="ask_alyf-send btn btn-primary btn-sm" type="button">${__("Send")}</button>
								</div>
							</div>
							<div class="ask_alyf-disclaimer">${__(
								"Ask ALYF is an AI and can make mistakes, including with numbers and information about people."
							)}</div>
						</div>
					</div>
					<div class="ask_alyf-history-view ask_alyf-hidden">
						<div class="ask_alyf-history-list"></div>
					</div>
				</div>
			`;

			document.body.appendChild(root);

			this.root = root;
			this.panel = root.querySelector(".ask_alyf-panel");
			this.messagesEl = root.querySelector(".ask_alyf-messages");
			this.warningEl = root.querySelector(".ask_alyf-config-warning");
			this.inputEl = root.querySelector(".ask_alyf-input");
			this.bubbleEl = root.querySelector(".ask_alyf-bubble");
			this.sendEl = root.querySelector(".ask_alyf-send");
			this.micEl = root.querySelector(".ask_alyf-mic");
			this.micEl.setAttribute("aria-pressed", "false");
			this.resizeHandleEl = root.querySelector(".ask_alyf-resize-handle");
			this.chatViewEl = root.querySelector(".ask_alyf-chat-view");
			this.historyViewEl = root.querySelector(".ask_alyf-history-view");
			this.historyListEl = root.querySelector(".ask_alyf-history-list");
			this.tabEls = Array.from(root.querySelectorAll(".ask_alyf-tab"));
			this.modeDropdownEl = root.querySelector(".ask_alyf-mode-dropdown");
			this.modeTriggerEl = root.querySelector(".ask_alyf-mode-trigger");
			this.modeTriggerLabelEl = root.querySelector(".ask_alyf-mode-trigger-label");
			this.modeMenuEl = root.querySelector(".ask_alyf-mode-menu");
			this.modeOptionEls = Array.from(root.querySelectorAll(".ask_alyf-mode-option"));
			this.supportPhoneEl = root.querySelector(".ask_alyf-support-phone");
			this.tabEls.forEach((tabEl) => {
				tabEl.addEventListener("click", (event) => this.onTabClick(event));
			});
			this.modeTriggerEl.addEventListener("click", (event) =>
				this.onModeTriggerClick(event)
			);
			this.modeOptionEls.forEach((optionEl) => {
				optionEl.addEventListener("click", (event) => this.onModeOptionClick(event));
			});
			document.addEventListener("click", this.boundDocumentClick);
			this.syncModeControl();
			this.syncSupportPhoneAction(frappe?.boot?.ask_alyf || {});

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
					return;
				}
				if (event.key === "Escape") {
					this.closeModeMenu();
				}
			});
			this.inputEl.addEventListener("input", () => this.autoResizeInput());
			this.updateVoiceInputHint();
			this.autoResizeInput();
			this.setActiveTab(this.state.activeTab);
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
				this.state.pendingOperation = message.pending_operation || null;
				this.pendingStreamMessageId = null;
				this.renderMessages();
				this.refreshConversationList();
				this.maybeAutoExecuteFrontendAction();
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
			const askAlyfBoot = response.message.ask_alyf || {};
			this.applyConversation(response.message.conversation);
			this.setModeToAskDefault();
			this.syncSupportPhoneAction(askAlyfBoot);
			await this.refreshConversationList();

			if (!askAlyfBoot.configured) {
				this.warningEl.classList.remove("ask_alyf-hidden");
				this.warningEl.textContent = __(
					"Ask ALYF is visible, but no API key/model is configured yet in Ask ALYF Settings."
				);
			}
		}

		applyConversation(conversation) {
			this.state.conversation = conversation;
			this.state.messages = conversation.messages || [];
			this.state.pendingOperation = conversation.pending_operation || null;
			this.cacheRenderedMessageKeys(this.state.messages);
			this.syncModeControl();
			this.renderHistoryList();
			this.renderMessages();
		}

		onTabClick(event) {
			const selectedTab = event.currentTarget?.dataset?.tab || "chat";
			this.setActiveTab(selectedTab);
			if (selectedTab === "history") {
				this.refreshConversationList();
			}
		}

		setActiveTab(tabName) {
			const nextTab = tabName === "history" ? "history" : "chat";
			this.state.activeTab = nextTab;

			const showHistory = nextTab === "history";
			this.chatViewEl?.classList.toggle("ask_alyf-hidden", showHistory);
			this.historyViewEl?.classList.toggle("ask_alyf-hidden", !showHistory);

			this.tabEls.forEach((tabEl) => {
				const isActive = tabEl.dataset.tab === nextTab;
				tabEl.classList.toggle("active", isActive);
				tabEl.setAttribute("aria-selected", isActive ? "true" : "false");
			});
		}

		onHistoryConversationClick(event) {
			const conversationName = event.currentTarget?.dataset?.conversation;
			if (!conversationName) {
				return;
			}

			this.setActiveTab("chat");
			if (conversationName === this.state.conversation?.name) {
				this.setModeToAskDefault();
				this.inputEl?.focus();
				return;
			}

			this.openConversation(conversationName);
		}

		onModeOptionClick(event) {
			const option = event.currentTarget;
			const selectedMode = option?.dataset?.mode;
			if (!selectedMode || option.disabled) {
				return;
			}

			this.state.mode = selectedMode;
			this.syncModeControl();
		}

		setModeToAskDefault() {
			this.state.mode = "Ask";
			this.syncModeControl();
		}

		isAgentModeEnabled() {
			const askAlyfSettings = frappe?.boot?.ask_alyf || {};
			return Boolean(askAlyfSettings.agent_mode_enabled);
		}

		syncSupportPhoneAction(askAlyfBoot = {}) {
			if (!this.supportPhoneEl) {
				return;
			}

			const supportPhoneNumber = (askAlyfBoot.support_phone_number || "").toString().trim();
			const supportPhoneUriFromBoot = (askAlyfBoot.support_phone_uri || "")
				.toString()
				.trim();
			const supportPhoneUri = supportPhoneUriFromBoot.startsWith("tel:")
				? supportPhoneUriFromBoot
				: this.getSupportPhoneUri(supportPhoneNumber);

			if (!supportPhoneUri) {
				this.supportPhoneEl.classList.add("ask_alyf-hidden");
				this.supportPhoneEl.removeAttribute("href");
				return;
			}

			const phoneButtonLabel = supportPhoneNumber
				? __("Call support: {0}", [supportPhoneNumber])
				: __("Call support");
			this.supportPhoneEl.href = supportPhoneUri;
			this.supportPhoneEl.title = phoneButtonLabel;
			this.supportPhoneEl.setAttribute("aria-label", phoneButtonLabel);
			this.supportPhoneEl.classList.remove("ask_alyf-hidden");
		}

		getSupportPhoneUri(phoneNumber) {
			const normalizedPhoneNumber = (phoneNumber || "").toString().trim();
			if (!normalizedPhoneNumber) {
				return "";
			}

			const digitsOnly = normalizedPhoneNumber.replace(/\D/g, "");
			if (!digitsOnly) {
				return "";
			}

			const prefix = normalizedPhoneNumber.startsWith("+") ? "+" : "";
			return `tel:${prefix}${digitsOnly}`;
		}

		onModeTriggerClick(event) {
			event.preventDefault();
			event.stopPropagation();
			const menuOpen = !this.modeMenuEl.classList.contains("ask_alyf-hidden");
			if (menuOpen) {
				this.closeModeMenu();
				return;
			}
			this.openModeMenu();
		}

		syncModeControl() {
			if (!this.modeTriggerEl) {
				return;
			}

			const isAgentModeAllowed = this.isAgentModeEnabled();
			if (!isAgentModeAllowed && this.state.mode === "Agent") {
				this.state.mode = "Ask";
			}

			const modeLabel = this.state.mode === "Agent" ? __("Agent") : __("Ask");
			this.modeTriggerLabelEl.textContent = modeLabel;
			this.modeTriggerEl.setAttribute("aria-label", __("Mode: {0}", modeLabel));

			this.modeOptionEls.forEach((option) => {
				const optionMode = option.dataset.mode;
				const isSelected = optionMode === this.state.mode;
				const isDisabled = optionMode === "Agent" && !isAgentModeAllowed;
				option.classList.toggle("btn-primary", isSelected);
				option.classList.toggle("btn-secondary", !isSelected);
				option.classList.toggle("is-disabled", isDisabled);
				option.disabled = isDisabled;
				option.setAttribute("aria-checked", isSelected ? "true" : "false");
			});

			this.closeModeMenu();
		}

		onDocumentClick(event) {
			if (!this.modeDropdownEl || this.modeMenuEl.classList.contains("ask_alyf-hidden")) {
				return;
			}
			if (this.modeDropdownEl.contains(event.target)) {
				return;
			}
			this.closeModeMenu();
		}

		openModeMenu() {
			if (!this.modeMenuEl) {
				return;
			}
			this.modeMenuEl.classList.remove("ask_alyf-hidden");
			this.modeTriggerEl.setAttribute("aria-expanded", "true");
		}

		closeModeMenu() {
			if (!this.modeMenuEl) {
				return;
			}
			this.modeMenuEl.classList.add("ask_alyf-hidden");
			this.modeTriggerEl.setAttribute("aria-expanded", "false");
		}

		formatConversationLabel(conversation) {
			const title = (conversation.title || "").trim() || __("Untitled conversation");
			return `${title}`;
		}

		formatConversationTimestamp(conversation) {
			const timestamp = conversation.last_message_at || conversation.modified;
			if (!timestamp) {
				return "";
			}

			if (!frappe.datetime?.str_to_user) {
				return timestamp;
			}

			try {
				return frappe.datetime.str_to_user(timestamp);
			} catch {
				return timestamp;
			}
		}

		renderHistoryList() {
			if (!this.historyListEl) {
				return;
			}

			const currentName = this.state.conversation?.name || "";
			const recentConversations = (this.state.conversations || [])
				.filter((conversation) => conversation?.name)
				.slice(0, 20);
			this.historyListEl.innerHTML = "";

			if (!recentConversations.length) {
				const emptyStateEl = document.createElement("div");
				emptyStateEl.className = "ask_alyf-history-empty";
				emptyStateEl.textContent = __("No conversations yet.");
				this.historyListEl.appendChild(emptyStateEl);
				return;
			}

			recentConversations.forEach((conversation) => {
				const itemEl = document.createElement("button");
				itemEl.type = "button";
				itemEl.className = "ask_alyf-history-item btn btn-secondary btn-sm";
				itemEl.dataset.conversation = conversation.name;

				if (conversation.name === currentName) {
					itemEl.classList.remove("btn-secondary");
					itemEl.classList.add("btn-primary");
				}

				const titleEl = document.createElement("div");
				titleEl.className = "ask_alyf-history-item-title";
				titleEl.textContent = this.formatConversationLabel(conversation);

				const metaEl = document.createElement("div");
				metaEl.className = "ask_alyf-history-item-meta";
				const timestampLabel = this.formatConversationTimestamp(conversation);
				metaEl.textContent = timestampLabel || "";

				itemEl.appendChild(titleEl);
				itemEl.appendChild(metaEl);
				itemEl.addEventListener("click", (event) =>
					this.onHistoryConversationClick(event)
				);
				this.historyListEl.appendChild(itemEl);
			});
		}

		async refreshConversationList() {
			try {
				const response = await frappe.call({
					method: "ask_alyf.api.list_conversations",
					args: { limit: 20 },
				});
				this.state.conversations = response.message || [];
				this.renderHistoryList();
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
				this.setModeToAskDefault();
				this.setStatus("");
			} catch (error) {
				this.setStatus("");
				frappe.msgprint(error.message || __("Failed to open conversation."));
				this.renderHistoryList();
			} finally {
				this.setLoading(false);
			}
		}

		toggle(open) {
			this.state.open = open;
			this.panel.classList.toggle("ask_alyf-hidden", !open);
			this.bubbleEl.classList.toggle("ask_alyf-hidden", open);
			this.closeModeMenu();
			if (open) {
				this.playPanelEnterAnimation();
				this.autoResizeInput();
				if (this.state.activeTab === "chat") {
					this.inputEl.focus();
				}
				this.refreshConversationList();
			} else {
				this.stopPanelResize();
			}
		}

		setLoading(value) {
			this.state.loading = value;
			this.root.classList.toggle("ask_alyf-loading", value);
			if (this.sendEl) {
				this.sendEl.setAttribute("aria-busy", value ? "true" : "false");
			}
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

			this.setActiveTab("chat");
			this.toggle(true);
			this.setLoading(true);
			this.setStatus(__("Sending..."));

			const optimisticMessage = {
				id: `local-${Date.now()}`,
				role: "user",
				content: text,
			};
			this.state.messages.push(optimisticMessage);
			this.state.pendingOperation = null;
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
			});
			this.setActiveTab("chat");
			this.applyConversation(response.message);
			this.setModeToAskDefault();
			this.refreshConversationList();
			this.setStatus("");
		}

		isFrontendAction(operation) {
			return operation?.kind === "frontend_action";
		}

		operationRequiresConfirmation(operation) {
			if (!operation || typeof operation !== "object") {
				return false;
			}
			if (!Object.prototype.hasOwnProperty.call(operation, "requires_confirmation")) {
				return true;
			}
			return Boolean(operation.requires_confirmation);
		}

		getPendingOperationSummary(operation) {
			if (!operation) {
				return "";
			}
			return operation.summary || operation.tool || __("Pending operation");
		}

		getMatchingForm(payload = {}) {
			if (!window.cur_frm?.doc) {
				throw new Error(__("No form is currently open."));
			}

			const expectedDoctype = payload.doctype;
			if (expectedDoctype && expectedDoctype !== cur_frm.doc.doctype) {
				throw new Error(
					__("Current form is {0}, expected {1}.", [
						cur_frm.doc.doctype,
						expectedDoctype,
					])
				);
			}

			const expectedDocname = payload.docname;
			if (expectedDocname && expectedDocname !== cur_frm.doc.name) {
				throw new Error(
					__("Current document is {0}, expected {1}.", [
						cur_frm.doc.name,
						expectedDocname,
					])
				);
			}

			return cur_frm;
		}

		async dispatchFrontendAction(tool, payload = {}) {
			if (tool === "set_route") {
				await frappe.set_route(...(payload.route || []));
				return { route: payload.route || [] };
			}

			if (tool === "new_doc") {
				frappe.new_doc(payload.doctype, payload.route_options || null);
				return { doctype: payload.doctype };
			}

			if (tool === "scroll_to_field") {
				const frm = this.getMatchingForm(payload);
				if (typeof frm.scroll_to_field !== "function") {
					throw new Error(__("Scrolling to fields is not available on this form."));
				}
				frm.scroll_to_field(payload.fieldname);
				return { fieldname: payload.fieldname };
			}

			if (tool === "frm_set_value") {
				const frm = this.getMatchingForm(payload);
				if (!frm.fields_dict?.[payload.fieldname]) {
					throw new Error(
						__("Field {0} does not exist on this form.", [payload.fieldname])
					);
				}
				await frm.set_value(payload.fieldname, payload.value);
				return { fieldname: payload.fieldname };
			}

			if (tool === "frm_add_child") {
				const frm = this.getMatchingForm(payload);
				if (!frm.fields_dict?.[payload.fieldname]) {
					throw new Error(
						__("Field {0} does not exist on this form.", [payload.fieldname])
					);
				}
				const row = frm.add_child(payload.fieldname, payload.values || {});
				frm.refresh_field(payload.fieldname);
				return { fieldname: payload.fieldname, row_name: row?.name || "" };
			}

			throw new Error(__("Unsupported frontend action: {0}", [tool]));
		}

		async reportFrontendActionResult(operation, status, result = null, errorMessage = "") {
			if (!operation?.call_id || !this.state.conversation?.name) {
				return;
			}

			const args = {
				conversation: this.state.conversation.name,
				call_id: operation.call_id,
				status,
				mode: this.state.mode,
			};
			if (result && typeof result === "object") {
				args.result = result;
			}
			if (errorMessage) {
				args.error = errorMessage;
			}

			const response = await frappe.call({
				method: "ask_alyf.api.frontend_action_result",
				type: "POST",
				args,
			});
			if (response.message?.conversation) {
				this.applyConversation(response.message.conversation);
			}
			this.refreshConversationList();
		}

		async executeFrontendAction(operation) {
			if (!this.isFrontendAction(operation)) {
				return false;
			}
			if (!operation.call_id) {
				frappe.msgprint(__("Frontend action is missing a call ID."));
				return false;
			}

			this.handledFrontendCallIds.add(operation.call_id);
			try {
				const actionResult = await this.dispatchFrontendAction(
					operation.tool,
					operation.payload || {}
				);
				await this.reportFrontendActionResult(operation, "success", actionResult);
				return true;
			} catch (error) {
				const errorMessage = error?.message || __("Failed to execute frontend action.");
				try {
					await this.reportFrontendActionResult(operation, "failed", null, errorMessage);
				} catch {
					// Keep the widget responsive even if status reporting fails.
				}
				frappe.msgprint(errorMessage);
				return false;
			}
		}

		async maybeAutoExecuteFrontendAction() {
			const operation = this.state.pendingOperation;
			if (!this.isFrontendAction(operation)) {
				return;
			}
			if (this.operationRequiresConfirmation(operation)) {
				return;
			}
			if (!operation.call_id || this.handledFrontendCallIds.has(operation.call_id)) {
				return;
			}
			await this.executeFrontendAction(operation);
		}

		async confirmPendingOperation() {
			const operation = this.state.pendingOperation;
			if (!operation || !this.state.conversation?.name) {
				return;
			}

			this.state.pendingOperation = null;
			this.renderMessages();
			try {
				if (this.isFrontendAction(operation)) {
					const actionCompleted = await this.executeFrontendAction(operation);
					if (!actionCompleted) {
						this.state.pendingOperation = operation;
						this.renderMessages();
					}
					return;
				}

				const response = await frappe.call({
					method: "ask_alyf.api.confirm_pending_operation",
					type: "POST",
					args: { conversation: this.state.conversation.name, mode: this.state.mode },
				});
				this.applyConversation(response.message.conversation);
				this.refreshConversationList();
			} catch (error) {
				this.state.pendingOperation = operation;
				this.renderMessages();
				frappe.msgprint(error.message || __("Failed to confirm pending operation."));
			}
		}

		async rejectPendingOperation() {
			const operation = this.state.pendingOperation;
			if (!operation || !this.state.conversation?.name) {
				return;
			}

			this.state.pendingOperation = null;
			this.renderMessages();
			try {
				if (this.isFrontendAction(operation)) {
					if (operation.call_id) {
						this.handledFrontendCallIds.add(operation.call_id);
					}
					await this.reportFrontendActionResult(operation, "rejected");
					return;
				}

				const response = await frappe.call({
					method: "ask_alyf.api.reject_pending_operation",
					type: "POST",
					args: { conversation: this.state.conversation.name, mode: this.state.mode },
				});
				this.applyConversation(response.message.conversation);
				this.refreshConversationList();
			} catch (error) {
				this.state.pendingOperation = operation;
				this.renderMessages();
				frappe.msgprint(error.message || __("Failed to reject pending operation."));
			}
		}

		renderMessages() {
			const previousMessageKeys = this.renderedMessageKeys;
			const nextMessageKeys = new Set();
			this.messagesEl.innerHTML = "";

			this.state.messages.forEach((message, index) => {
				const wrapper = document.createElement("div");
				wrapper.className = `ask_alyf-message ask_alyf-${message.role}`;
				const messageKey = this.getMessageRenderKey(message, index);
				nextMessageKeys.add(messageKey);
				if (!previousMessageKeys.has(messageKey)) {
					wrapper.classList.add("ask_alyf-message-enter");
				}

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
				if (this.state.loading) {
					statusWrapper.classList.add("ask_alyf-status-loading");
				}

				const statusBody = document.createElement("div");
				statusBody.className = "ask_alyf-message-body";
				statusBody.textContent = this.state.status;

				statusWrapper.appendChild(statusBody);
				this.messagesEl.appendChild(statusWrapper);
			}

			const pendingOperation = this.state.pendingOperation;
			if (pendingOperation && this.operationRequiresConfirmation(pendingOperation)) {
				const proposal = document.createElement("div");
				proposal.className = "ask_alyf-proposal";
				proposal.innerHTML = `
					<div class="ask_alyf-proposal-title">${__("Pending operation")}</div>
					<div class="ask_alyf-proposal-summary">${this.escapeHtml(
						this.getPendingOperationSummary(pendingOperation)
					)}</div>
					<div class="ask_alyf-proposal-actions">
						<button class="ask_alyf-confirm btn btn-primary btn-sm" type="button">${__("Confirm")}</button>
						<button class="ask_alyf-reject btn btn-secondary btn-sm" type="button">${__("Reject")}</button>
					</div>
				`;
				proposal
					.querySelector(".ask_alyf-confirm")
					.addEventListener("click", () => this.confirmPendingOperation());
				proposal
					.querySelector(".ask_alyf-reject")
					.addEventListener("click", () => this.rejectPendingOperation());
				this.messagesEl.appendChild(proposal);
			}

			this.renderedMessageKeys = nextMessageKeys;
			this.scrollToBottom();
		}

		playPanelEnterAnimation() {
			if (!this.panel) {
				return;
			}
			this.panel.classList.remove("ask_alyf-panel-pop");
			// Trigger reflow so the entrance animation restarts each open.
			void this.panel.offsetWidth;
			this.panel.classList.add("ask_alyf-panel-pop");
		}

		getMessageRenderKey(message, index) {
			if (message?.id) {
				return `id:${message.id}`;
			}
			return `fallback:${message?.role || "message"}:${index}`;
		}

		cacheRenderedMessageKeys(messages = []) {
			this.renderedMessageKeys = new Set(
				messages.map((message, index) => this.getMessageRenderKey(message, index))
			);
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

			if (this.voiceRecognition) {
				this.voiceRecognition.stop();
				return;
			}

			const speechLanguage = this.getPreferredSpeechLanguage();
			this.updateVoiceInputHint(speechLanguage);

			const recognition = new Recognition();
			this.voiceRecognition = recognition;
			recognition.lang = speechLanguage;
			recognition.interimResults = false;
			recognition.maxAlternatives = 1;
			recognition.onstart = () => {
				this.setVoiceInputListening(true);
			};
			recognition.onresult = (event) => {
				const transcript = event.results?.[0]?.[0]?.transcript;
				if (transcript) {
					this.inputEl.value = transcript;
					this.autoResizeInput();
				}
			};
			recognition.onerror = () => {
				this.setVoiceInputListening(false);
			};
			recognition.onend = () => {
				this.setVoiceInputListening(false);
			};

			try {
				recognition.start();
			} catch (error) {
				this.setVoiceInputListening(false);
			}
		}

		setVoiceInputListening(isListening) {
			if (!isListening) {
				this.voiceRecognition = null;
			}

			if (!this.micEl) {
				return;
			}

			this.micEl.classList.toggle("is-listening", isListening);
			this.micEl.setAttribute("aria-pressed", isListening ? "true" : "false");
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
