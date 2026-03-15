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

		allowed_roles: DF.Table[HasRole]
		api_key: DF.Password | None
		base_url: DF.Data | None
		enable_edit_mode: DF.Check
		enabled: DF.Check
		excluded_doctypes: DF.SmallText | None
		llm_provider: DF.Literal["OpenAI", "OpenAI Compatible"]
		model: DF.Autocomplete | None
		system_prompt: DF.Code | None
	# end: auto-generated types

	pass


@frappe.whitelist()
def get_available_models(
	llm_provider: str | None = None,
	base_url: str | None = None,
	api_key: str | None = None,
) -> list[dict[str, str]]:
	settings = frappe.get_single("Ask ALYF Settings")

	llm_provider = (llm_provider or settings.llm_provider or "OpenAI").strip()
	base_url = (base_url or settings.base_url or "").strip() or None
	api_key = (
		normalize_api_key(api_key) or (settings.get_password("api_key", raise_exception=False) or "").strip()
	)

	if not api_key:
		frappe.throw(_("Configure an API key first, then fetch available models."))

	if llm_provider == "OpenAI Compatible" and not base_url:
		frappe.throw(_("Base URL is required for OpenAI-compatible providers."))

	client = AnyLLM.create(
		provider=get_any_llm_provider(llm_provider),
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
