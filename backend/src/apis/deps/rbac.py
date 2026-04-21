from __future__ import annotations

from collections.abc import Iterable


def _normalize_role(raw: object) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().upper()
    return s or None


def get_user_roles(user: object) -> set[str]:
    """Return normalized roles for a user.

    Source of truth:
    - users.roles_assigned (multi-role). No fallback to legacy users.role.
    """
    roles_assigned = getattr(user, "roles_assigned", None)
    out: set[str] = set()

    # Treat NULL as "no roles"; treat empty array as "no roles".
    if roles_assigned is None:
        return set()
    if isinstance(roles_assigned, str):
        nr = _normalize_role(roles_assigned)
        return {nr} if nr else set()
    if isinstance(roles_assigned, Iterable):
        for r in roles_assigned:
            nr = _normalize_role(r)
            if nr:
                out.add(nr)
        return out
    return set()


def has_role(user: object, role: str) -> bool:
    return _normalize_role(role) in get_user_roles(user)


def is_admin(user: object) -> bool:
    return has_role(user, "ADMIN")

