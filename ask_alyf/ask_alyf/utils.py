import json
from collections.abc import Iterable
from typing import Any

import frappe

# Display name of the assistant in user-facing texts. Technical identifiers
# (DocType names, roles, module, API paths) keep the "Ask ALYF" name.
ASSISTANT_NAME = "Frage mich"

AWESOMEBAR_CHAT_DISABLED = "Disabled"
AWESOMEBAR_CHAT_OFFER = "Offer in Results"
AWESOMEBAR_CHAT_DEFAULT = "Default Action"
AWESOMEBAR_CHAT_MODES = (AWESOMEBAR_CHAT_DISABLED, AWESOMEBAR_CHAT_OFFER, AWESOMEBAR_CHAT_DEFAULT)


def normalize_awesomebar_chat_mode(value: str | None) -> str:
	"""Return a valid `awesomebar_chat` mode, falling back to Disabled."""
	value = (value or "").strip()
	return value if value in AWESOMEBAR_CHAT_MODES else AWESOMEBAR_CHAT_DISABLED


def parse_newline_list(value: str | Iterable[str] | None) -> list[str]:
	if not value:
		return []

	if isinstance(value, str):
		items = value.replace(",", "\n").splitlines()
	else:
		items = list(value)

	return [item.strip() for item in items if item and item.strip()]


def dumps(data: Any) -> str:
	return frappe.as_json(data, indent=None)


def loads(value: str | None, default: Any):
	if not value:
		return default

	try:
		return json.loads(value)
	except Exception:
		return default


def chunk_text(text: str, size: int = 120) -> list[str]:
	if len(text) <= size:
		return [text]

	chunks: list[str] = []
	current = []
	current_length = 0

	for word in text.split(" "):
		extra = len(word) + (1 if current else 0)
		if current and current_length + extra > size:
			chunks.append(" ".join(current))
			current = [word]
			current_length = len(word)
			continue

		current.append(word)
		current_length += extra

	if current:
		chunks.append(" ".join(current))

	return chunks
