from __future__ import annotations

from datetime import date
from typing import Any, cast

import streamlit as st

from services.supabase_client import get_supabase_client


AccessRow = dict[str, Any]


ROLE_INSPECTOR = "INSPECTOR"
ROLE_VERIFICATOR = "VERIFICATOR"
ROLE_MONITORING = "MONITORING"
ROLE_EVALUATOR = "EVALUATOR"
ROLE_ADMIN = "ADMIN"
ROLE_SUPER_ADMIN = "SUPER_ADMIN"


def get_current_user_id() -> str | None:
    user = st.session_state.get("auth_user")

    if user is None:
        return None

    user_id = getattr(user, "id", None)

    if user_id is None:
        return None

    return str(user_id)


@st.cache_data(ttl=120, show_spinner=False)
def _load_user_access_assignments(
    user_id: str,
) -> list[AccessRow]:
    if not user_id:
        return []

    supabase = get_supabase_client()

    response = (
        supabase
        .table("user_access_assignment")
        .select(
            "assignment_id,"
            "user_id,"
            "role_code,"
            "functloc_id,"
            "include_children,"
            "is_primary,"
            "is_active,"
            "valid_from,"
            "valid_until"
        )
        .eq("user_id", user_id)
        .eq("is_active", True)
        .execute()
    )

    if not response.data:
        return []

    rows = cast(
        list[AccessRow],
        response.data,
    )

    today = date.today()
    valid_rows: list[AccessRow] = []

    for row in rows:
        valid_from_raw = row.get("valid_from")
        valid_until_raw = row.get("valid_until")

        valid_from: date | None = None
        valid_until: date | None = None

        if valid_from_raw:
            try:
                valid_from = date.fromisoformat(
                    str(valid_from_raw)[:10]
                )
            except ValueError:
                valid_from = None

        if valid_until_raw:
            try:
                valid_until = date.fromisoformat(
                    str(valid_until_raw)[:10]
                )
            except ValueError:
                valid_until = None

        if (
            valid_from is not None
            and valid_from > today
        ):
            continue

        if (
            valid_until is not None
            and valid_until < today
        ):
            continue

        valid_rows.append(row)

    return valid_rows


def get_user_access_assignments() -> list[AccessRow]:
    user_id = get_current_user_id()

    if user_id is None:
        return []

    return _load_user_access_assignments(user_id)


def clear_access_cache() -> None:
    _load_user_access_assignments.clear()


def get_role_codes() -> set[str]:
    return {
        str(row.get("role_code") or "")
        .strip()
        .upper()
        for row in get_user_access_assignments()
        if str(row.get("role_code") or "").strip()
    }


def has_role(role_code: str) -> bool:
    target = str(role_code or "").strip().upper()

    if not target:
        return False

    return target in get_role_codes()


def has_any_role(*role_codes: str) -> bool:
    if not role_codes:
        return False

    current_roles = get_role_codes()

    return any(
        str(role_code or "").strip().upper()
        in current_roles
        for role_code in role_codes
    )


def is_super_admin() -> bool:
    return has_role(ROLE_SUPER_ADMIN)


def is_admin() -> bool:
    return has_role(ROLE_ADMIN)


def is_evaluator() -> bool:
    return has_role(ROLE_EVALUATOR)


def is_verificator() -> bool:
    return has_role(ROLE_VERIFICATOR)


def is_inspector() -> bool:
    return has_role(ROLE_INSPECTOR)


def is_monitoring() -> bool:
    return has_role(ROLE_MONITORING)


def can_view() -> bool:
    return has_any_role(
        ROLE_INSPECTOR,
        ROLE_VERIFICATOR,
        ROLE_MONITORING,
        ROLE_EVALUATOR,
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN,
    )


def can_input() -> bool:
    return has_any_role(
        ROLE_INSPECTOR,
        ROLE_EVALUATOR,
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN,
    )


def can_edit() -> bool:
    return has_any_role(
        ROLE_INSPECTOR,
        ROLE_EVALUATOR,
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN,
    )


def can_soft_delete() -> bool:
    return has_any_role(
        ROLE_INSPECTOR,
        ROLE_EVALUATOR,
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN,
    )


def can_verify() -> bool:
    return has_any_role(
        ROLE_VERIFICATOR,
        ROLE_EVALUATOR,
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN,
    )


def can_evaluate() -> bool:
    return has_any_role(
        ROLE_EVALUATOR,
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN,
    )


def can_manage_access() -> bool:
    return has_any_role(
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN,
    )


def can_restore_deleted() -> bool:
    return has_any_role(
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN,
    )


def get_primary_role_code() -> str | None:
    assignments = get_user_access_assignments()

    for row in assignments:
        if bool(row.get("is_primary")):
            role_code = str(
                row.get("role_code") or ""
            ).strip().upper()

            if role_code:
                return role_code

    roles = sorted(get_role_codes())

    if not roles:
        return None

    return roles[0]


def get_role_labels() -> list[str]:
    labels: dict[str, str] = {
        ROLE_INSPECTOR: "Inspector",
        ROLE_VERIFICATOR: "Verifikator",
        ROLE_MONITORING: "Monitoring",
        ROLE_EVALUATOR: "Evaluator",
        ROLE_ADMIN: "Administrator",
        ROLE_SUPER_ADMIN: "Super Administrator",
    }

    role_codes = get_role_codes()

    ordered_roles = [
        ROLE_SUPER_ADMIN,
        ROLE_ADMIN,
        ROLE_EVALUATOR,
        ROLE_VERIFICATOR,
        ROLE_INSPECTOR,
        ROLE_MONITORING,
    ]

    return [
        labels.get(role_code, role_code)
        for role_code in ordered_roles
        if role_code in role_codes
    ]