import json
from collections.abc import Iterable
from typing import Any

import frappe


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
