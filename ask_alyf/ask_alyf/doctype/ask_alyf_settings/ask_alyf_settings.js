// Copyright (c) 2026, ALYF GmbH and contributors
// For license information, please see license.txt

frappe.ui.form.on("Ask ALYF Settings", {
	refresh(frm) {
		load_model_options(frm);
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
