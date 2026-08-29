from __future__ import annotations

from typing import Any, cast

import streamlit as st

from services.supabase_client import get_supabase_client


EventRow = dict[str, Any]


@st.cache_data(
    ttl=10,
    show_spinner=False,
)
def get_active_gangguan_for_penyulang(
    penyulang_id: str,
) -> EventRow | None:
    """
    Mengambil satu Gangguan aktif (ONGOING) untuk penyulang tertentu.

    Digunakan sebagai guard UX agar operator tidak tanpa sengaja
    membuat record Gangguan baru pada penyulang yang masih memiliki
    Gangguan aktif.

    Guard ini bukan hard constraint database. User tetap dapat
    melanjutkan bila memang kejadian baru yang sah secara operasional.
    """

    clean_id = str(
        penyulang_id
        or ""
    ).strip()

    if not clean_id:
        return None

    supabase = get_supabase_client()

    response = (
        supabase
        .table(
            "vw_kejadian_penyulang_detail"
        )
        .select(
            "event_id,"
            "penyulang_id,"
            "penyulang_code,"
            "penyulang_name,"
            "event_date,"
            "event_time,"
            "record_status,"
            "record_status_name,"
            "supply_status_code,"
            "supply_status_name,"
            "cause_code,"
            "cause_name,"
            "operator_name"
        )
        .eq(
            "penyulang_id",
            clean_id,
        )
        .eq(
            "event_type_code",
            "GANGGUAN",
        )
        .eq(
            "record_status",
            "ONGOING",
        )
        .order(
            "event_date",
            desc=True,
        )
        .order(
            "event_time",
            desc=True,
        )
        .limit(
            1
        )
        .execute()
    )

    data = response.data

    if not isinstance(
        data,
        list,
    ) or not data:
        return None

    first = data[0]

    if not isinstance(
        first,
        dict,
    ):
        return None

    return cast(
        EventRow,
        first,
    )


def clear_duplicate_event_cache() -> None:
    """
    Bersihkan cache duplicate guard setelah event baru disimpan.
    """

    get_active_gangguan_for_penyulang.clear()