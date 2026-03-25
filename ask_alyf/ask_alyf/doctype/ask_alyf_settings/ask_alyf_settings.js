// Copyright (c) 2026, ALYF GmbH and contributors
// For license information, please see license.txt

const CHAT_MODEL_CONFIGURATION = "chat";
const VISION_MODEL_CONFIGURATION = "vision";
const VISION_PROVIDER_FIELDS = [
	"vision_llm_provider",
	"vision_base_url",
	"vision_api_key",
	"vision_model",
];

frappe.ui.form.on("Ask ALYF Settings", {
	async refresh(frm) {
		await refresh_model_options(frm);
		render_roles_editor(frm);
	},

	async llm_provider(frm) {
		await refresh_chat_model_options(frm);
	},

	async base_url(frm) {
		await refresh_chat_model_options(frm);
	},

	async api_key(frm) {
		await refresh_chat_model_options(frm);
	},

	async vision_model_is_chat_model(frm) {
		toggle_vision_provider_fields(frm);
		await refresh_vision_model_options(frm);
	},

	async vision_llm_provider(frm) {
		await refresh_vision_model_options(frm);
	},

	async vision_base_url(frm) {
		await refresh_vision_model_options(frm);
	},

	async vision_api_key(frm) {
		await refresh_vision_model_options(frm);
	},

	validate(frm) {
		frm.roles_editor?.set_roles_in_table();
	},
});

async function refresh_model_options(frm) {
	toggle_vision_provider_fields(frm);
	await refresh_chat_model_options(frm);
	await refresh_vision_model_options(frm);
}

async function refresh_chat_model_options(frm) {
	clear_model_options(frm, "model");
	await load_model_options(frm, {
		fieldname: "model",
		configuration: CHAT_MODEL_CONFIGURATION,
	});
}

async function refresh_vision_model_options(frm) {
	clear_model_options(frm, "vision_model");

	if (uses_chat_model_for_vision(frm)) {
		return;
	}

	await load_model_options(frm, {
		fieldname: "vision_model",
		configuration: VISION_MODEL_CONFIGURATION,
	});
}

async function load_model_options(frm, { fieldname, configuration }) {
	const model_field = frm.fields_dict[fieldname];
	if (!model_field) {
		return;
	}

	if (!is_model_configuration_ready(frm, configuration)) {
		model_field.set_data([]);
		return;
	}

	try {
		const response = await frappe.call({
			method: "ask_alyf.ask_alyf.doctype.ask_alyf_settings.ask_alyf_settings.get_available_models",
			args: { configuration },
		});

		const models = response.message || [];
		const options = models.map((model) => ({
			label: model.id,
			value: model.id,
		}));
		model_field.set_data(options);
	} catch {
		model_field.set_data([]);
	}
}

function clear_model_options(frm, fieldname) {
	frm.fields_dict[fieldname]?.set_data([]);
}

function toggle_vision_provider_fields(frm) {
	frm.toggle_display(VISION_PROVIDER_FIELDS, !uses_chat_model_for_vision(frm));
}

function uses_chat_model_for_vision(frm) {
	return Boolean(frm.doc.vision_model_is_chat_model);
}

function is_model_configuration_ready(frm, configuration) {
	const field_prefix = configuration === VISION_MODEL_CONFIGURATION ? "vision_" : "";
	const llm_provider = (frm.doc[`${field_prefix}llm_provider`] || "").trim();
	const api_key = (frm.doc[`${field_prefix}api_key`] || "").trim();
	const base_url = (frm.doc[`${field_prefix}base_url`] || "").trim();

	if (!llm_provider || !api_key) {
		return false;
	}

	if (llm_provider === "OpenAI Compatible" && !base_url) {
		return false;
	}

	return true;
}

function render_roles_editor(frm) {
	if (!frm.fields_dict.roles_html) {
		return;
	}

	if (!frm.roles_editor) {
		const role_area = $('<div class="role-editor">').appendTo(
			frm.fields_dict.roles_html.wrapper
		);
		frm.roles_editor = new AskALYFRoleEditor(role_area, frm);
	}

	frm.roles_editor.show();
}

class AskALYFRoleEditor {
	constructor(wrapper, frm) {
		this.frm = frm;
		this.wrapper = wrapper;

		this.multicheck = frappe.ui.form.make_control({
			parent: wrapper,
			df: {
				fieldname: "allowed_roles",
				fieldtype: "MultiCheck",
				label: __("Allowed Roles"),
				select_all: true,
				columns: "15rem",
				get_data: () => {
					return frappe
						.xcall("frappe.core.doctype.user.user.get_all_roles")
						.then((roles) =>
							roles.map((role) => ({
								label: __(role),
								value: role,
								checked: this.get_selected_roles().includes(role),
							}))
						);
				},
				on_change: () => {
					this.set_roles_in_table();
					this.frm.dirty();
				},
			},
			render_input: true,
		});

		const original_make_checkboxes = this.multicheck.make_checkboxes;
		this.multicheck.make_checkboxes = () => {
			original_make_checkboxes.call(this.multicheck);
			this.multicheck.$wrapper.find(".label-area").click((event) => {
				const role = $(event.target).data("unit");
				if (role) {
					this.show_permissions(role);
				}
				event.preventDefault();
			});
		};
	}

	show() {
		this.reset();
	}

	get_selected_roles() {
		return (this.frm.doc.allowed_roles || []).map((row) => row.role);
	}

	reset() {
		this.multicheck.selected_options = this.get_selected_roles();
		this.multicheck.refresh_input();
	}

	set_roles_in_table() {
		const role_rows = this.frm.doc.allowed_roles || [];
		const checked_roles = this.multicheck.get_checked_options();

		role_rows.forEach((role_doc) => {
			if (!checked_roles.includes(role_doc.role)) {
				frappe.model.clear_doc(role_doc.doctype, role_doc.name);
			}
		});

		checked_roles.forEach((role) => {
			if (!role_rows.find((row) => row.role === role)) {
				const role_doc = frappe.model.add_child(this.frm.doc, "Has Role", "allowed_roles");
				role_doc.role = role;
			}
		});
	}

	show_permissions(role) {
		if (!this.perm_dialog) {
			this.make_perm_dialog();
		}

		$(this.perm_dialog.body).empty();
		const is_dark_theme = document.documentElement.getAttribute("data-theme") === "dark";
		const header_bg_color = is_dark_theme ? "bg-dark text-white" : "bg-light";

		return frappe
			.xcall("frappe.core.doctype.user.user.get_perm_info", { role })
			.then((permissions) => {
				const $body = $(this.perm_dialog.body);
				if (!permissions.length) {
					$body.append(`<div class="text-muted text-center padding">
						${__("{0} role does not have permission on any doctype", [__(role)])}
					</div>`);
				} else {
					$body.append(`
						<div style="max-height:calc(100vh - 200px); overflow-y:auto;">
							<table class="user-perm">
								<thead>
									<tr>
										<th class="sticky-top ${header_bg_color}"> ${__("Document Type")} </th>
										<th class="sticky-top ${header_bg_color}"> ${__("Level")} </th>
										<th class="sticky-top ${header_bg_color}"> ${__("If Owner")} </th>
										${frappe.perm.rights
											.map(
												(permission) =>
													`<th class="sticky-top ${header_bg_color}">${__(
														frappe.unscrub(permission)
													)}</th>`
											)
											.join("")}
									</tr>
								</thead>
								<tbody></tbody>
							</table>
						</div>
					`);

					permissions.forEach((permission) => {
						$body.find("tbody").append(`
							<tr>
								<td>${__(permission.parent)}</td>
								<td>${permission.permlevel}</td>
								<td>${permission.if_owner ? frappe.utils.icon("check", "xs") : "-"}</td>
								${frappe.perm.rights
									.map(
										(right) =>
											`<td class="text-muted bold">${
												permission[right]
													? frappe.utils.icon("check", "xs")
													: "-"
											}</td>`
									)
									.join("")}
							</tr>
						`);
					});
				}

				this.perm_dialog.set_title(__(role));
				this.perm_dialog.show();
			});
	}

	make_perm_dialog() {
		this.perm_dialog = new frappe.ui.Dialog({
			title: __("Role Permissions"),
		});

		this.perm_dialog.$wrapper
			.find(".modal-dialog")
			.css("width", "auto")
			.css("max-width", "1200px");
		this.perm_dialog.$wrapper.find(".modal-body").css("overflow", "overlay");
	}
}
