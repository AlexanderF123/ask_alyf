from frappe.model.document import Document


class AskALYFConversation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		last_context_json: DF.Code | None
		last_message_at: DF.Datetime | None
		messages_json: DF.Code | None
		pending_action_json: DF.Code | None
		route: DF.Data | None
		status: DF.Literal["Active", "Closed"]
		title: DF.Data
		user: DF.Link
	# end: auto-generated types

	pass
