from __future__ import annotations

import json
from typing import Any, cast

import streamlit as st

from services.supabase_client import (
    SESSION_USER_KEY,
    get_supabase_client,
)


ProfileRow = dict[str, Any]
AssignmentRow = dict[str, Any]
UnitUserRow = dict[str, Any]


def _normalize_function_response(
    response: Any,
) -> dict[str, Any]:
    data = getattr(
        response,
        "data",
        response,
    )

    if data is None:
        return {}

    if isinstance(data, dict):
        return cast(
            dict[str, Any],
            data,
        )

    if isinstance(data, bytes):
        decoded = data.decode(
            "utf-8",
            errors="replace",
        )

        try:
            parsed = json.loads(
                decoded
            )

            if isinstance(
                parsed,
                dict,
            ):
                return cast(
                    dict[str, Any],
                    parsed,
                )

            return {
                "data":
                    parsed
            }

        except Exception:
            return {
                "raw":
                    decoded
            }

    if isinstance(data, str):
        try:
            parsed = json.loads(
                data
            )

            if isinstance(
                parsed,
                dict,
            ):
                return cast(
                    dict[str, Any],
                    parsed,
                )

            return {
                "data":
                    parsed
            }

        except Exception:
            return {
                "raw":
                    data
            }

    return {
        "data":
            data
    }


def _as_dict_list(
    data: Any,
) -> list[dict[str, Any]]:
    if not isinstance(
        data,
        list,
    ):
        return []

    result: list[dict[str, Any]] = []

    for item in data:
        if isinstance(
            item,
            dict,
        ):
            result.append(
                cast(
                    dict[str, Any],
                    item,
                )
            )

    return result


def _get_current_user_id() -> str:
    """
    UUID user login digunakan sebagai bagian dari cache key.

    st.cache_data bersifat shared lintas session/browser,
    sehingga cache profile/assignment tidak boleh menggunakan
    cache key kosong.
    """

    user = st.session_state.get(
        SESSION_USER_KEY
    )

    if user is None:
        return ""

    user_id = getattr(
        user,
        "id",
        None,
    )

    return str(
        user_id
        or ""
    ).strip()


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def _load_my_profile(
    user_id: str,
) -> ProfileRow:
    if not user_id:
        return {}

    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_my_profile"
        )
        .execute()
    )

    rows = _as_dict_list(
        response.data
    )

    if not rows:
        return {}

    return cast(
        ProfileRow,
        rows[0],
    )


def get_my_profile() -> ProfileRow:
    user_id = _get_current_user_id()

    if not user_id:
        return {}

    return _load_my_profile(
        user_id
    )


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def _load_my_assignments(
    user_id: str,
) -> list[AssignmentRow]:
    if not user_id:
        return []

    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_my_assignments"
        )
        .execute()
    )

    rows = _as_dict_list(
        response.data
    )

    return cast(
        list[AssignmentRow],
        rows,
    )


def get_my_assignments() -> list[AssignmentRow]:
    user_id = _get_current_user_id()

    if not user_id:
        return []

    return _load_my_assignments(
        user_id
    )


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def _load_my_unit_users(
    user_id: str,
) -> list[UnitUserRow]:
    if not user_id:
        return []

    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_my_unit_users"
        )
        .execute()
    )

    rows = _as_dict_list(
        response.data
    )

    return cast(
        list[UnitUserRow],
        rows,
    )


def get_my_unit_users() -> list[UnitUserRow]:
    user_id = _get_current_user_id()

    if not user_id:
        return []

    return _load_my_unit_users(
        user_id
    )


def clear_profile_cache() -> None:
    """
    Bersihkan cache profile/access-derived data.

    Dipanggil setelah:
    - login;
    - logout;
    - perubahan role;
    - perubahan assignment.
    """

    _load_my_profile.clear()
    _load_my_assignments.clear()
    _load_my_unit_users.clear()


def change_my_password(
    *,
    password: str,
) -> bool:
    password_clean = str(
        password
        or ""
    )

    if len(
        password_clean
    ) < 8:
        raise ValueError(
            "Password minimal 8 karakter."
        )

    supabase = get_supabase_client()

    response = (
        supabase
        .functions
        .invoke(
            "change-my-password",
            invoke_options={
                "body": {
                    "password":
                        password_clean,
                },
            },
        )
    )

    result = (
        _normalize_function_response(
            response
        )
    )

    error_message = result.get(
        "error"
    )

    if error_message:
        raise RuntimeError(
            str(
                error_message
            )
        )

    if not bool(
        result.get(
            "success"
        )
    ):
        raise RuntimeError(
            "Password tidak berhasil diperbarui."
        )

    return True