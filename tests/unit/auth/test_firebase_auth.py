import types
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import src.apis.deps.firebase_auth as firebase_auth


@pytest.fixture(autouse=True)
def _reset_module_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep tests isolated/deterministic: clear auth caches between tests.
    firebase_auth._TOKEN_CACHE.clear()
    firebase_auth._USER_CACHE.clear()

    # Default settings fixture (tests override as needed).
    settings = types.SimpleNamespace(
        firebase_auth=types.SimpleNamespace(
            project_id="test-project",
            email_allowlist="",
        )
    )
    monkeypatch.setattr(firebase_auth, "get_settings", lambda: settings)


def _make_request(auth_header: str | None) -> MagicMock:
    req = MagicMock()
    req.headers = {}
    if auth_header is not None:
        req.headers["Authorization"] = auth_header
    return req


def test_get_bearer_token__happy_path_extracts_token() -> None:
    req = _make_request("Bearer abc.def.ghi")
    assert firebase_auth.get_bearer_token(req) == "abc.def.ghi"


def test_get_bearer_token__rejects_missing_header() -> None:
    req = _make_request(None)
    with pytest.raises(HTTPException) as ei:
        firebase_auth.get_bearer_token(req)
    assert ei.value.status_code == 401


def test_get_bearer_token__rejects_non_bearer_scheme() -> None:
    req = _make_request("Basic xyz")
    with pytest.raises(HTTPException) as ei:
        firebase_auth.get_bearer_token(req)
    assert ei.value.status_code == 401


def test_get_bearer_token__rejects_empty_token() -> None:
    req = _make_request("Bearer   ")
    with pytest.raises(HTTPException) as ei:
        firebase_auth.get_bearer_token(req)
    assert ei.value.status_code == 401


def test__extract_roles_assigned_from_claims__dedupes_and_uppercases() -> None:
    # Note: the implementation coerces each list element via `str(...)`, so avoid
    # including `None` here (which would normalize to the literal role "NONE").
    decoded = {"roles": ["admin", " ADMIN ", "team_member", ""]}
    assert firebase_auth._extract_roles_assigned_from_claims(decoded) == [
        "ADMIN",
        "TEAM_MEMBER",
    ]


def test__extract_roles_assigned_from_claims__parses_comma_and_semicolon_list() -> None:
    decoded = {"roles": " admin ; team_lead, TEAM_MEMBER,, "}
    assert firebase_auth._extract_roles_assigned_from_claims(decoded) == [
        "ADMIN",
        "TEAM_LEAD",
        "TEAM_MEMBER",
    ]


def test__extract_roles_assigned_from_claims__supports_single_role_key() -> None:
    decoded = {"role": "sales_rep"}
    assert firebase_auth._extract_roles_assigned_from_claims(decoded) == ["SALES_REP"]


def test__extract_roles_assigned_from_claims__returns_none_when_absent_or_empty() -> None:
    assert firebase_auth._extract_roles_assigned_from_claims({}) is None
    assert firebase_auth._extract_roles_assigned_from_claims({"roles": ""}) is None


def test__extract_user_name_from_claims__returns_none_for_nullish_strings() -> None:
    assert firebase_auth._extract_user_name_from_claims({"name": "null"}, "a@b.com") is None
    assert firebase_auth._extract_user_name_from_claims({"displayName": " None "}, "a@b.com") is None


def test__extract_user_name_from_claims__trims_and_returns_string() -> None:
    assert (
        firebase_auth._extract_user_name_from_claims({"display_name": "  Jane Doe  "}, None)
        == "Jane Doe"
    )


def test__parse_email_allowlist__lowercases_and_strips() -> None:
    assert firebase_auth._parse_email_allowlist(" A@B.COM, c@d.com ,, ") == frozenset(
        {"a@b.com", "c@d.com"}
    )


def test_verify_firebase_token__cache_hit_returns_cached_without_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "t1"
    now = 1000.0
    monkeypatch.setattr(firebase_auth.time, "time", lambda: now)

    firebase_auth._TOKEN_CACHE[token] = ({"uid": "U1", "exp": now + 999}, now + 60.0)

    # If these get called, the test should fail.
    monkeypatch.setattr(firebase_auth, "ensure_firebase_initialized", lambda: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(firebase_auth.auth, "verify_id_token", lambda _t: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(firebase_auth, "verify_firebase_id_token_public", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError()))

    assert firebase_auth.verify_firebase_token(token) == {"uid": "U1", "exp": now + 999}


def test_verify_firebase_token__admin_sdk_path_on_cache_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "t2"
    now = 2000.0
    monkeypatch.setattr(firebase_auth.time, "time", lambda: now)
    monkeypatch.setattr(firebase_auth.time, "perf_counter", lambda: 123.0)

    monkeypatch.setattr(firebase_auth, "ensure_firebase_initialized", lambda: None)
    monkeypatch.setattr(firebase_auth.firebase_admin, "get_app", lambda: object())

    verify_mock = MagicMock(return_value={"uid": "U2", "exp": now + 100})
    monkeypatch.setattr(firebase_auth.auth, "verify_id_token", verify_mock)

    decoded = firebase_auth.verify_firebase_token(token)
    assert decoded["uid"] == "U2"
    assert verify_mock.call_count == 1
    assert token in firebase_auth._TOKEN_CACHE


def test_verify_firebase_token__public_keys_path_when_no_admin_app(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "t3"
    now = 3000.0
    monkeypatch.setattr(firebase_auth.time, "time", lambda: now)
    monkeypatch.setattr(firebase_auth.time, "perf_counter", lambda: 123.0)

    # No firebase app -> triggers public-key verification branch.
    monkeypatch.setattr(firebase_auth, "ensure_firebase_initialized", lambda: None)
    monkeypatch.setattr(firebase_auth.firebase_admin, "get_app", lambda: (_ for _ in ()).throw(ValueError("no app")))

    public_mock = MagicMock(return_value={"sub": "U3", "exp": now + 200})
    monkeypatch.setattr(firebase_auth, "verify_firebase_id_token_public", public_mock)

    decoded = firebase_auth.verify_firebase_token(token)
    assert decoded["sub"] == "U3"
    assert public_mock.call_count == 1
    assert token in firebase_auth._TOKEN_CACHE


def test_verify_firebase_token__not_configured_raises_503(monkeypatch: pytest.MonkeyPatch) -> None:
    # No admin app + empty project_id => 503.
    settings = types.SimpleNamespace(
        firebase_auth=types.SimpleNamespace(project_id="", email_allowlist="")
    )
    monkeypatch.setattr(firebase_auth, "get_settings", lambda: settings)
    monkeypatch.setattr(firebase_auth, "ensure_firebase_initialized", lambda: None)
    monkeypatch.setattr(firebase_auth.firebase_admin, "get_app", lambda: (_ for _ in ()).throw(ValueError("no app")))

    with pytest.raises(HTTPException) as ei:
        firebase_auth.verify_firebase_token("t4")
    assert ei.value.status_code == 503


def test_get_firebase_user__existing_user_via_raw_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    req = _make_request("Bearer tok")
    db = MagicMock()

    monkeypatch.setattr(firebase_auth, "verify_firebase_token", lambda _t: {"uid": "UID1", "email": "x@y.com"})
    monkeypatch.setattr(firebase_auth, "_raw_user_lookup_by_firebase_uid", lambda _uid: (12, "x@y.com", "Name", ["ADMIN"]))

    u = firebase_auth.get_firebase_user(req, db)
    assert int(u.id) == 12
    assert u.email == "x@y.com"
    assert u.firebase_uid == "UID1"
    assert u.roles_assigned == ["ADMIN"]


def test_get_firebase_user__allowlist_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = types.SimpleNamespace(
        firebase_auth=types.SimpleNamespace(project_id="test-project", email_allowlist="allowed@x.com")
    )
    monkeypatch.setattr(firebase_auth, "get_settings", lambda: settings)
    req = _make_request("Bearer tok")
    db = MagicMock()

    monkeypatch.setattr(firebase_auth, "verify_firebase_token", lambda _t: {"uid": "UID2", "email": "nope@x.com"})
    monkeypatch.setattr(firebase_auth, "_raw_user_lookup_by_firebase_uid", lambda _uid: None)

    with pytest.raises(HTTPException) as ei:
        firebase_auth.get_firebase_user(req, db)
    assert ei.value.status_code == 403


def test_get_firebase_user__links_by_email_when_uid_missing_in_db(monkeypatch: pytest.MonkeyPatch) -> None:
    req = _make_request("Bearer tok")
    db = MagicMock()

    monkeypatch.setattr(
        firebase_auth,
        "verify_firebase_token",
        lambda _t: {"uid": "UID3", "email": "link@x.com", "roles": ["team_member"], "name": "Link User"},
    )
    monkeypatch.setattr(firebase_auth, "_raw_user_lookup_by_firebase_uid", lambda _uid: None)

    by_email_user = firebase_auth.User()
    by_email_user.id = 77
    by_email_user.email = "link@x.com"
    by_email_user.firebase_uid = None
    by_email_user.name = None
    by_email_user.roles_assigned = None

    q = MagicMock()
    q.filter.return_value.first.return_value = by_email_user
    db.query.return_value = q

    u = firebase_auth.get_firebase_user(req, db)
    assert u.id == 77
    assert u.firebase_uid == "UID3"
    assert u.roles_assigned == ["TEAM_MEMBER"]
    assert u.name == "Link User"
    assert db.commit.called


def test_get_firebase_user__email_linked_to_different_uid_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    req = _make_request("Bearer tok")
    db = MagicMock()

    monkeypatch.setattr(
        firebase_auth,
        "verify_firebase_token",
        lambda _t: {"uid": "UID4", "email": "e@x.com"},
    )
    monkeypatch.setattr(firebase_auth, "_raw_user_lookup_by_firebase_uid", lambda _uid: None)

    by_email_user = firebase_auth.User()
    by_email_user.id = 88
    by_email_user.email = "e@x.com"
    by_email_user.firebase_uid = "OTHER_UID"

    q = MagicMock()
    q.filter.return_value.first.return_value = by_email_user
    db.query.return_value = q

    with pytest.raises(HTTPException) as ei:
        firebase_auth.get_firebase_user(req, db)
    assert ei.value.status_code == 403


def test_get_firebase_user__creates_new_user_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    req = _make_request("Bearer tok")
    db = MagicMock()

    monkeypatch.setattr(
        firebase_auth,
        "verify_firebase_token",
        lambda _t: {"uid": "UID5", "email": "new@x.com", "roles": "admin"},
    )
    monkeypatch.setattr(firebase_auth, "_raw_user_lookup_by_firebase_uid", lambda _uid: None)

    q = MagicMock()
    q.filter.return_value.first.return_value = None
    db.query.return_value = q

    u = firebase_auth.get_firebase_user(req, db)
    assert u.email == "new@x.com"
    assert u.firebase_uid == "UID5"
    assert u.roles_assigned == ["ADMIN"]
    assert db.add.called
    assert db.commit.called


def test_get_existing_firebase_user__requires_existing_row(monkeypatch: pytest.MonkeyPatch) -> None:
    req = _make_request("Bearer tok")
    db = MagicMock()
    monkeypatch.setattr(firebase_auth, "verify_firebase_token", lambda _t: {"uid": "UID6", "email": "x@y.com"})
    monkeypatch.setattr(firebase_auth, "_raw_user_lookup_by_firebase_uid", lambda _uid: None)

    with pytest.raises(HTTPException) as ei:
        firebase_auth.get_existing_firebase_user(req, db)
    assert ei.value.status_code == 404

