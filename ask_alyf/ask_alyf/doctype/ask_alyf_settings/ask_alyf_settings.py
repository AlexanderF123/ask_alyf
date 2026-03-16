import frappe
from any_llm import AnyLLM
from frappe import _
from frappe.model.document import Document

NON_TEXT_MODEL_PATTERNS = (
	"audio",
	"dall",
	"embed",
	"image",
	"moderation",
	"omni-moderation",
	"realtime",
	"search",
	"similarity",
	"speech",
	"transcribe",
	"tts",
	"vision-preview",
	"whisper",
)


class AskALYFSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.core.doctype.has_role.has_role import HasRole
		from frappe.types import DF

		from ask_alyf.ask_alyf.doctype.ask_alyf_excluded_doctype.ask_alyf_excluded_doctype import (
			AskALYFExcludedDocType,
		)

		allow_agent_mode: DF.Check
		allowed_roles: DF.Table[HasRole]
		api_key: DF.Password | None
		base_url: DF.Data | None
		enabled: DF.Check
		excluded_doctypes: DF.TableMultiSelect[AskALYFExcludedDocType]
		llm_provider: DF.Literal["OpenAI", "OpenAI Compatible"]
		model: DF.Autocomplete | None
		support_phone_number: DF.Phone | None
		system_prompt: DF.Code | None
	# end: auto-generated types

	pass


@frappe.whitelist()
def get_available_models() -> list[dict[str, str]]:
	settings = frappe.get_single("Ask ALYF Settings")
	settings.check_permission("write")

	base_url = (settings.base_url or "").strip() or None
	api_key = (settings.get_password("api_key", raise_exception=False) or "").strip()

	if not api_key:
		frappe.msgprint(
			_("Please configure an API key first and save the settings, then we can fetch available models."),
			alert=True,
		)
		return []

	if settings.llm_provider == "OpenAI Compatible" and not base_url:
		frappe.msgprint(
			_("Please configure a Base URL first and save the settings, then we can fetch available models."),
			alert=True,
		)
		return []

	client = AnyLLM.create(
		provider=get_any_llm_provider(settings.llm_provider),
		api_key=api_key,
		api_base=base_url,
	)
	response = client.list_models()
	models = sorted(
		[model for model in response if is_text_generation_model(model.id)],
		key=lambda model: model.id.lower(),
	)

	return [{"id": model.id} for model in models]


def get_any_llm_provider(llm_provider: str) -> str:
	llm_provider = (llm_provider or "").strip()
	if llm_provider in {"OpenAI", "OpenAI Compatible"}:
		return "openai"

	frappe.throw(_("Unsupported LLM provider: {0}").format(llm_provider))


def normalize_api_key(api_key: str | None) -> str:
	api_key = (api_key or "").strip()
	if not api_key:
		return ""

	# Password fields may send a masked placeholder when the document is already saved.
	if set(api_key) == {"*"}:
		return ""

	return api_key


def is_text_generation_model(model_id: str) -> bool:
	model_id = (model_id or "").strip().lower()
	if not model_id:
		return False

	return not any(pattern in model_id for pattern in NON_TEXT_MODEL_PATTERNS)
