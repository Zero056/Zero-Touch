"""Frappe hooks for Document Intake and Processing Log access. Mirrors security/policy.py in SQL."""

import frappe

from zero_touch.security.policy import (
	ROLE_ADMIN,
	ROLE_MANAGER,
	intake_scope,
	can_see_intake,
)

INTAKE = "tabDocument Intake"
LOG = "tabDocument Processing Log"


def _companies_for(user: str) -> list[str]:
	from frappe.core.doctype.user_permission.user_permission import get_user_permissions

	return [p.doc for p in get_user_permissions(user).get("Company", [])]


def _scope(user: str):
	return intake_scope(set(frappe.get_roles(user)), _companies_for(user))


def _intake_condition(user: str) -> str:
	scope = _scope(user)
	if scope.deny_all:
		return "1=0"
	companies = ", ".join(frappe.db.escape(c) for c in scope.companies)
	condition = f"`{INTAKE}`.`company` in ({companies})"
	if scope.own_only:
		condition += f" and `{INTAKE}`.`submitted_by` = {frappe.db.escape(user)}"
	return f"({condition})"


def intake_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	return _intake_condition(user)


def log_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	scope = _scope(user)
	if scope.deny_all:
		return "1=0"
	visible = (
		f"`{LOG}`.`intake` in (select `{INTAKE}`.`name` from `{INTAKE}` where {_intake_condition(user)})"
	)
	if ROLE_ADMIN in frappe.get_roles(user) or ROLE_MANAGER in frappe.get_roles(user):
		return f"({visible} or `{LOG}`.`intake` is null or `{LOG}`.`intake` = '')"
	return visible


def intake_has_permission(doc=None, ptype: str = "read", user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	scope = _scope(user)
	if doc is None:
		return not scope.deny_all
	company = doc.get("company")
	if ptype == "create":
		return not scope.deny_all and company in scope.companies
	if ptype in ("write", "delete"):
		return can_see_intake(scope, user, company, doc.get("submitted_by")) and not scope.own_only
	return can_see_intake(scope, user, company, doc.get("submitted_by"))


def log_has_permission(doc=None, ptype: str = "read", user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	if ptype != "read":
		return False
	if doc is None:
		return not _scope(user).deny_all
	if not doc.get("intake"):
		return ROLE_ADMIN in frappe.get_roles(user) or ROLE_MANAGER in frappe.get_roles(user)
	intake = frappe.db.get_value("Document Intake", doc.get("intake"), ["company", "submitted_by"], as_dict=True)
	if not intake:
		return False
	return can_see_intake(_scope(user), user, intake.company, intake.submitted_by)
