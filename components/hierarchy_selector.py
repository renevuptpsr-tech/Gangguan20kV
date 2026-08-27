from typing import Any, Iterable

import streamlit as st

from services.hierarchy_service import get_penyulang_hierarchy


HierarchySelection = dict[str, Any]


def _unique_sorted(values: Iterable[Any]) -> list[str]:
    cleaned: set[str] = set()

    for value in values:
        if value is None:
            continue

        text = str(value).strip()

        if text:
            cleaned.add(text)

    return sorted(cleaned)


def render_hierarchy_selector(
    key_prefix: str = "event",
) -> HierarchySelection | None:
    """
    Cascading selector:
    ULTG -> GI -> BAY -> Penyulang

    Seluruh field selalu terlihat.
    Field berikutnya disabled sampai pilihan sebelumnya tersedia.
    """

    hierarchy = get_penyulang_hierarchy()

    if not hierarchy:
        st.warning("Master hierarchy penyulang belum tersedia.")
        return None

    col_ultg, col_gi, col_bay, col_penyulang = st.columns(
        [1.1, 1.4, 1.8, 1.7]
    )

    # ======================================================
    # ULTG
    # ======================================================

    ultg_names = _unique_sorted(
        row.get("ultg_name")
        for row in hierarchy
    )

    with col_ultg:
        selected_ultg = st.selectbox(
            "ULTG",
            options=[""] + ultg_names,
            index=0,
            key=f"{key_prefix}_ultg",
            format_func=lambda value: (
                "Pilih ULTG"
                if value == ""
                else str(value)
            ),
        )

    # ======================================================
    # GI
    # ======================================================

    rows_ultg = [
        row
        for row in hierarchy
        if selected_ultg
        and str(row.get("ultg_name") or "")
        == str(selected_ultg)
    ]

    gi_names = _unique_sorted(
        row.get("gi_name")
        for row in rows_ultg
    )

    with col_gi:
        selected_gi = st.selectbox(
            "Gardu Induk",
            options=[""] + gi_names,
            index=0,
            key=f"{key_prefix}_gi",
            format_func=lambda value: (
                "Pilih Gardu Induk"
                if value == ""
                else str(value)
            ),
            disabled=not bool(selected_ultg),
        )

    # ======================================================
    # BAY
    # ======================================================

    rows_gi = [
        row
        for row in rows_ultg
        if selected_gi
        and str(row.get("gi_name") or "")
        == str(selected_gi)
    ]

    bay_names = _unique_sorted(
        row.get("bay_name")
        for row in rows_gi
    )

    with col_bay:
        selected_bay = st.selectbox(
            "Bay",
            options=[""] + bay_names,
            index=0,
            key=f"{key_prefix}_bay",
            format_func=lambda value: (
                "Pilih Bay"
                if value == ""
                else str(value)
            ),
            disabled=not bool(
                selected_ultg
                and selected_gi
            ),
        )

    # ======================================================
    # PENYULANG
    # ======================================================

    rows_bay = [
        row
        for row in rows_gi
        if selected_bay
        and str(row.get("bay_name") or "")
        == str(selected_bay)
    ]

    penyulang_options: dict[str, str] = {}

    for row in rows_bay:
        penyulang_id_raw = row.get("penyulang_id")

        if penyulang_id_raw is None:
            continue

        penyulang_id = str(penyulang_id_raw)

        penyulang_code = str(
            row.get("penyulang_code") or ""
        ).strip()

        penyulang_name = str(
            row.get("penyulang_name") or ""
        ).strip()

        if penyulang_code and penyulang_name:
            label = f"{penyulang_code} — {penyulang_name}"
        elif penyulang_code:
            label = penyulang_code
        elif penyulang_name:
            label = penyulang_name
        else:
            label = penyulang_id

        penyulang_options[penyulang_id] = label

    penyulang_ids = sorted(
        penyulang_options.keys(),
        key=lambda item: penyulang_options[item],
    )

    def format_penyulang(value: str) -> str:
        if value == "":
            return "Pilih Penyulang"

        return penyulang_options.get(
            value,
            value,
        )

    with col_penyulang:
        selected_penyulang_id = st.selectbox(
            "Penyulang",
            options=[""] + penyulang_ids,
            index=0,
            key=f"{key_prefix}_penyulang",
            format_func=format_penyulang,
            disabled=not bool(
                selected_ultg
                and selected_gi
                and selected_bay
            ),
        )

    # ======================================================
    # BELUM LENGKAP
    # ======================================================

    if not (
        selected_ultg
        and selected_gi
        and selected_bay
        and selected_penyulang_id
    ):
        return None

    # ======================================================
    # CARI ROW TERPILIH
    # ======================================================

    selected_row: dict[str, Any] | None = None

    for row in rows_bay:
        row_penyulang_id = row.get("penyulang_id")

        if row_penyulang_id is None:
            continue

        if str(row_penyulang_id) == selected_penyulang_id:
            selected_row = row
            break

    if selected_row is None:
        return None

    return {
        "ultg_flc": selected_row.get("ultg_flc"),
        "ultg_name": selected_row.get("ultg_name"),
        "gi_flc": selected_row.get("gi_flc"),
        "gi_name": selected_row.get("gi_name"),
        "bay_flc": selected_row.get("bay_flc"),
        "bay_name": selected_row.get("bay_name"),
        "penyulang_id": selected_row.get("penyulang_id"),
        "penyulang_code": selected_row.get("penyulang_code"),
        "penyulang_name": selected_row.get("penyulang_name"),
    }