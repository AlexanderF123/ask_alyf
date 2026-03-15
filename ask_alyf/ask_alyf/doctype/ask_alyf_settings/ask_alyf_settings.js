// Copyright (c) 2026, ALYF GmbH and contributors
// For license information, please see license.txt

frappe.ui.form.on("Ask ALYF Settings", {
	refresh(frm) {
		load_model_options(frm);
		render_roles_editor(frm);
	},

	llm_provider(frm) {
		clear_model_options(frm);
		load_model_options(frm);
	},

	base_url(frm) {
		clear_model_options(frm);
		load_model_options(frm);
	},

	api_key(frm) {
		clear_model_options(frm);
		load_model_options(frm);
	},

	validate(frm) {
		frm.roles_editor?.set_roles_in_table();
	},
});

async function load_model_options(frm) {
	const model_field = frm.fields_dict.model;
	if (!model_field) {
		return;
	}

	try {
		const response = await frappe.call({
			method: "ask_alyf.ask_alyf.doctype.ask_alyf_settings.ask_alyf_settings.get_available_models",
			args: {
				llm_provider: frm.doc.llm_provider,
				base_url: frm.doc.base_url,
				api_key: frm.doc.api_key,
			},
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

function clear_model_options(frm) {
	frm.fields_dict.model?.set_data([]);
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
