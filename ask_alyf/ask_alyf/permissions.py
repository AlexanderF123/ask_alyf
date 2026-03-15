import frappe


def get_conversation_permission_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user

	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return ""

	return f"`tabAsk ALYF Conversation`.`user` = {frappe.db.escape(user)}"


def has_conversation_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
	user = user or frappe.session.user

	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return True

	return doc.user == user
