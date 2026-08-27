from __future__ import annotations

import json
from typing import Any, cast

import streamlit as st

from services.supabase_client import get_supabase_client


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
    """
    Menormalkan response Supabase menjadi list[dict].

    Supabase response.data memiliki union type yang cukup luas
    pada type stub, sehingga helper ini juga menghilangkan
    warning Pylance saat melakukan indexing.
    """

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


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def _load_my_profile() -> ProfileRow:
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
    return _load_my_profile()


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def _load_my_assignments() -> list[AssignmentRow]:
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
    return _load_my_assignments()


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def _load_my_unit_users() -> list[UnitUserRow]:
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
    return _load_my_unit_users()


def clear_profile_cache() -> None:
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