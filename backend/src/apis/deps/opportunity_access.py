from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.apis.deps.rbac import is_admin


@dataclass(frozen=True)
class OpportunityAccessDecision:
    can_view: bool
    can_edit: bool
    can_assign: bool


def _read_field(opportunity: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    if isinstance(opportunity, Mapping):
        return opportunity.get(key, default)
    return getattr(opportunity, key, default)


def can_user_access_opportunity(
    user: object,
    opportunity: Mapping[str, Any] | Any,
) -> OpportunityAccessDecision:
    """Evaluate opportunity access from a caller-provided opportunity context.

    Expected opportunity fields:
    - owner_id
    - user_is_team_member (bool)
    - user_is_team_lead (bool)
    """
    if is_admin(user):
        return OpportunityAccessDecision(can_view=True, can_edit=True, can_assign=True)

    user_id = int(getattr(user, "id"))
    owner_id = _read_field(opportunity, "owner_id")
    user_is_team_lead = bool(_read_field(opportunity, "user_is_team_lead", False))
    user_is_team_member = bool(_read_field(opportunity, "user_is_team_member", False))

    if user_is_team_lead:
        return OpportunityAccessDecision(can_view=True, can_edit=True, can_assign=False)
    if user_is_team_member:
        return OpportunityAccessDecision(can_view=True, can_edit=False, can_assign=False)
    if owner_id is not None and int(owner_id) == user_id:
        return OpportunityAccessDecision(can_view=True, can_edit=False, can_assign=False)
    return OpportunityAccessDecision(can_view=False, can_edit=False, can_assign=False)
    