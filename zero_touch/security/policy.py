"""Visibility rules for Document Intake. Pure logic, mirrored by SQL in access.py.

Fail closed: no company scope, or no Zero Touch role, means no access.
"""

from dataclasses import dataclass

ROLE_UPLOADER = "Zero Touch Uploader"
ROLE_REVIEWER = "Zero Touch Reviewer"
ROLE_MANAGER = "Zero Touch Manager"
ROLE_ADMIN = "Zero Touch Admin"

COMPANY_WIDE_ROLES = frozenset({ROLE_REVIEWER, ROLE_MANAGER})


@dataclass(frozen=True)
class IntakeScope:
	deny_all: bool
	companies: tuple[str, ...]
	own_only: bool


def intake_scope(roles: set[str] | frozenset[str], companies: list[str] | tuple[str, ...]) -> IntakeScope:
	companies = tuple(c for c in companies if c)
	if not companies:
		return IntakeScope(deny_all=True, companies=(), own_only=False)
	if roles & COMPANY_WIDE_ROLES:
		return IntakeScope(deny_all=False, companies=companies, own_only=False)
	if ROLE_UPLOADER in roles:
		return IntakeScope(deny_all=False, companies=companies, own_only=True)
	return IntakeScope(deny_all=True, companies=(), own_only=False)


def can_see_intake(scope: IntakeScope, user: str, intake_company: str, submitted_by: str | None) -> bool:
	if scope.deny_all:
		return False
	if intake_company not in scope.companies:
		return False
	if scope.own_only and submitted_by != user:
		return False
	return True
