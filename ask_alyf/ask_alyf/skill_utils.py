import frappe
from frappe import _


def get_available_skill_summaries() -> list[dict[str, str]]:
	"""Load skill name and title pairs available to the current user."""
	return frappe.get_all(
		"Ask ALYF Skill",
		filters=[["Has Role", "role", "in", frappe.get_roles()]],
		fields=["name", "title"],
		distinct=True,
	)


def build_available_skills_instruction() -> str:
	"""Build an instruction block describing the current user's available skills."""
	available_skills = get_available_skill_summaries()
	if not available_skills:
		return "- No skills are available for the current user's roles."

	lines = [
		"- Skills available for the current user's roles. Use `read_skill` with the exact `name` before following one:",
	]
	for skill in available_skills:
		lines.append(f"  - name: {skill['name']} | title: {skill['title']}")
	return "\n".join(lines)


def get_accessible_skill_doc(skill_name: str):
	"""Load one skill document after enforcing role-based access."""
	clean_skill_name = (skill_name or "").strip()
	if not clean_skill_name:
		frappe.throw(_("Skill name is required."))

	try:
		skill_doc = frappe.get_doc("Ask ALYF Skill", clean_skill_name)
	except frappe.DoesNotExistError:
		frappe.throw(_("Skill '{0}' was not found.").format(clean_skill_name))

	allowed_roles = {row.role for row in skill_doc.roles if row.role}
	user_roles = set(frappe.get_roles())
	if not allowed_roles or not allowed_roles.intersection(user_roles):
		frappe.throw(_("Skill '{0}' is not available for the current user.").format(clean_skill_name))

	return skill_doc
