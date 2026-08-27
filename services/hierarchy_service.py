from typing import Any, cast

import streamlit as st

from services.supabase_client import get_supabase_client


HierarchyRow = dict[str, Any]


@st.cache_data(
    ttl=300,
    show_spinner=False,
)
def _load_penyulang_hierarchy(
    user_id: str,
) -> list[HierarchyRow]:
    """
    Membaca hierarchy Penyulang yang boleh diakses
    oleh user yang sedang login.

    Scope data ditentukan oleh Supabase melalui:
    - SUPER_ADMIN
    - user_access_assignment
    - hierarchy mst_functloc

    user_id tetap digunakan sebagai bagian dari cache key
    agar cache tidak tercampur antar-user.
    """

    if not user_id:
        return []

    supabase = get_supabase_client()

    response = (
        supabase
        .table(
            "vw_penyulang_hierarchy_accessible"
        )
        .select("*")
        .execute()
    )

    if not response.data:
        return []

    return cast(
        list[HierarchyRow],
        response.data,
    )


def get_penyulang_hierarchy() -> list[HierarchyRow]:
    """
    Mengambil hierarchy Penyulang untuk
    user yang sedang login.

    User biasa hanya menerima hierarchy
    sesuai unit access.

    SUPER_ADMIN menerima seluruh hierarchy.
    """

    user = st.session_state.get(
        "auth_user"
    )

    if user is None:
        return []

    user_id = getattr(
        user,
        "id",
        None,
    )

    if user_id is None:
        return []

    return _load_penyulang_hierarchy(
        str(user_id)
    )


def clear_hierarchy_cache() -> None:
    """
    Menghapus cache hierarchy.

    Dipakai setelah:
    - perubahan Role
    - perubahan Unit Access
    - perubahan master Penyulang
    - perubahan hierarchy FunctLoc
    """

    _load_penyulang_hierarchy.clear()