from __future__ import annotations

from datetime import date
from typing import Any

import streamlit as st

from services.supabase_client import get_supabase_client


MONTH_NAMES: dict[int, str] = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}


@st.cache_data(
    ttl=15,
    show_spinner=False,
)
def is_event_period_approved(
    *,
    penyulang_id: str,
    event_date: date,
) -> bool:
    """
    Memeriksa apakah periode GI dari penyulang tersebut sudah APPROVED.

    Menggunakan RPC:
        fn_event_period_is_approved(uuid, date)

    RPC ini menggunakan logika yang sama dengan backend guard database,
    sehingga UI dan proteksi final tetap konsisten.
    """

    penyulang_id = str(
        penyulang_id
        or ""
    ).strip()

    if not penyulang_id:
        return False

    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_event_period_is_approved",
            {
                "p_penyulang_id":
                    penyulang_id,

                "p_event_date":
                    event_date.isoformat(),
            },
        )
        .execute()
    )

    data: Any = response.data

    if isinstance(
        data,
        bool,
    ):
        return data

    if isinstance(
        data,
        list,
    ):
        if not data:
            return False

        first = data[0]

        if isinstance(
            first,
            bool,
        ):
            return first

        if isinstance(
            first,
            dict,
        ):
            for value in first.values():
                if isinstance(
                    value,
                    bool,
                ):
                    return value

    if isinstance(
        data,
        dict,
    ):
        for value in data.values():
            if isinstance(
                value,
                bool,
            ):
                return value

    return bool(
        data
    )


def monthly_period_label(
    value: date,
) -> str:
    return (
        f"{MONTH_NAMES.get(value.month, str(value.month))} "
        f"{value.year}"
    )


def clear_monthly_period_guard_cache() -> None:
    is_event_period_approved.clear()