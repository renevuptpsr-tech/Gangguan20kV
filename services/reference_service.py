from typing import Any, cast

import streamlit as st

from services.supabase_client import get_supabase_client


ReferenceRow = dict[str, Any]


# ==========================================================
# INTERNAL LOADERS
# ==========================================================


@st.cache_data(ttl=600, show_spinner=False)
def _load_annunciators(
    user_id: str,
) -> list[ReferenceRow]:
    """
    Mengambil master annunciator aktif.
    user_id digunakan sebagai cache key.
    """

    supabase = get_supabase_client()

    response = (
        supabase
        .table("ref_gangguan_annunciator")
        .select(
            "annunciator_code, description, sequence_no"
        )
        .eq("is_active", True)
        .order("sequence_no")
        .execute()
    )

    if not response.data:
        return []

    return cast(
        list[ReferenceRow],
        response.data,
    )


@st.cache_data(ttl=600, show_spinner=False)
def _load_indications(
    user_id: str,
) -> list[ReferenceRow]:
    """
    Mengambil master indikasi relay aktif.
    """

    supabase = get_supabase_client()

    response = (
        supabase
        .table("ref_gangguan_indikasi")
        .select(
            "indikasi_code, description, sequence_no"
        )
        .eq("is_active", True)
        .order("sequence_no")
        .execute()
    )

    if not response.data:
        return []

    return cast(
        list[ReferenceRow],
        response.data,
    )


@st.cache_data(ttl=600, show_spinner=False)
def _load_pics(
    user_id: str,
) -> list[ReferenceRow]:
    """
    Mengambil master PIC aktif.
    """

    supabase = get_supabase_client()

    response = (
        supabase
        .table("ref_gangguan_pic")
        .select(
            "pic_code, description, sequence_no"
        )
        .eq("is_active", True)
        .order("sequence_no")
        .execute()
    )

    if not response.data:
        return []

    return cast(
        list[ReferenceRow],
        response.data,
    )


@st.cache_data(ttl=600, show_spinner=False)
def _load_causes(
    user_id: str,
) -> list[ReferenceRow]:
    """
    Mengambil master penyebab aktif.
    """

    supabase = get_supabase_client()

    response = (
        supabase
        .table("ref_gangguan_cause")
        .select(
            "cause_code, description, sequence_no"
        )
        .eq("is_active", True)
        .order("sequence_no")
        .execute()
    )

    if not response.data:
        return []

    return cast(
        list[ReferenceRow],
        response.data,
    )


@st.cache_data(ttl=600, show_spinner=False)
def _load_cause_rules(
    user_id: str,
) -> list[ReferenceRow]:
    """
    Mengambil mapping:
    Status PMT + PIC -> Penyebab
    """

    supabase = get_supabase_client()

    response = (
        supabase
        .table("ref_gangguan_cause_rule")
        .select(
            "status_code, pic_code, cause_code, sequence_no"
        )
        .eq("is_active", True)
        .order("sequence_no")
        .execute()
    )

    if not response.data:
        return []

    return cast(
        list[ReferenceRow],
        response.data,
    )


# ==========================================================
# CURRENT USER
# ==========================================================


def _get_current_user_id() -> str | None:
    """
    Mengambil ID user Supabase yang sedang login.
    """

    user = st.session_state.get("auth_user")

    if user is None:
        return None

    user_id = getattr(
        user,
        "id",
        None,
    )

    if user_id is None:
        return None

    return str(user_id)


# ==========================================================
# PUBLIC FUNCTIONS
# ==========================================================


def get_annunciators() -> list[ReferenceRow]:
    user_id = _get_current_user_id()

    if user_id is None:
        return []

    return _load_annunciators(user_id)


def get_indications() -> list[ReferenceRow]:
    user_id = _get_current_user_id()

    if user_id is None:
        return []

    return _load_indications(user_id)


def get_pics() -> list[ReferenceRow]:
    user_id = _get_current_user_id()

    if user_id is None:
        return []

    return _load_pics(user_id)


def get_causes() -> list[ReferenceRow]:
    user_id = _get_current_user_id()

    if user_id is None:
        return []

    return _load_causes(user_id)


def get_cause_rules() -> list[ReferenceRow]:
    user_id = _get_current_user_id()

    if user_id is None:
        return []

    return _load_cause_rules(user_id)


# ==========================================================
# CACHE
# ==========================================================


def clear_reference_cache() -> None:
    """
    Menghapus seluruh cache master/reference.
    """

    _load_annunciators.clear()
    _load_indications.clear()
    _load_pics.clear()
    _load_causes.clear()
    _load_cause_rules.clear()