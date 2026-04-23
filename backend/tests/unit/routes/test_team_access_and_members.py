from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.apis.deps.opportunity_access import can_user_access_opportunity
from src.apis.routes.team_routes import TeamMemberInput, _validate_team_members


class _User:
    def __init__(self, user_id: int, roles_assigned: list[str] | None = None) -> None:
        self.id = user_id
        self.roles_assigned = roles_assigned or []


def test_can_user_access_opportunity_admin_has_full_access() -> None:
    user = _User(user_id=99, roles_assigned=["ADMIN"])
    access = can_user_access_opportunity(
        user,
        {"owner_id": 1, "user_is_team_member": False, "user_is_team_lead": False},
    )
    assert access.can_view is True
    assert access.can_edit is True
    assert access.can_assign is True


def test_can_user_access_opportunity_owner_has_read_access() -> None:
    user = _User(user_id=10, roles_assigned=[])
    access = can_user_access_opportunity(
        user,
        {"owner_id": 10, "user_is_team_member": False, "user_is_team_lead": False},
    )
    assert access.can_view is True
    assert access.can_edit is False
    assert access.can_assign is False


def test_can_user_access_opportunity_team_lead_can_edit_and_assign() -> None:
    user = _User(user_id=12, roles_assigned=["TEAM_LEAD"])
    access = can_user_access_opportunity(
        user,
        {"owner_id": 5, "user_is_team_member": True, "user_is_team_lead": True},
    )
    assert access.can_view is True
    assert access.can_edit is True
    assert access.can_assign is False


def test_can_user_access_opportunity_team_member_read_only() -> None:
    user = _User(user_id=13, roles_assigned=["TEAM_MEMBER"])
    access = can_user_access_opportunity(
        user,
        {"owner_id": 5, "user_is_team_member": True, "user_is_team_lead": False},
    )
    assert access.can_view is True
    assert access.can_edit is False
    assert access.can_assign is False


def test_validate_team_members_rejects_duplicates() -> None:
    members = [
        TeamMemberInput(user_id=1, is_lead=False),
        TeamMemberInput(user_id=1, is_lead=True),
    ]
    with pytest.raises(HTTPException):
        _validate_team_members(members)


def test_validate_team_members_rejects_more_than_two_leads() -> None:
    members = [
        TeamMemberInput(user_id=1, is_lead=True),
        TeamMemberInput(user_id=2, is_lead=True),
        TeamMemberInput(user_id=3, is_lead=True),
    ]
    with pytest.raises(HTTPException):
        _validate_team_members(members)


def test_validate_team_members_accepts_two_leads() -> None:
    members = [
        TeamMemberInput(user_id=1, is_lead=True),
        TeamMemberInput(user_id=2, is_lead=True),
        TeamMemberInput(user_id=3, is_lead=False),
    ]
    assert _validate_team_members(members) == [1, 2, 3]
