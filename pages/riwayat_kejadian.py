from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
import json
from typing import Any, cast

import pandas as pd
from openpyxl.utils import get_column_letter
import streamlit as st

from st_aggrid import (
    AgGrid,
    DataReturnMode,
    GridOptionsBuilder,
    GridUpdateMode,
    JsCode,
)

from components.sidebar import render_sidebar
from services.access_service import (
    can_edit,
    can_soft_delete,
)
from services.event_service import (
    get_current_user_id,
    soft_delete_event,
)
from services.supabase_client import (
    get_supabase_client,
)


# ==========================================================
# TYPES
# ==========================================================

OperationRow = dict[str, Any]


# ==========================================================
# PAGE STYLE
# ==========================================================


def _apply_page_style() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1480px;
            padding-top: 1.35rem;
            padding-bottom: 3rem;
        }

        div[data-testid="stMetric"] {
            padding-top: 0.05rem;
            padding-bottom: 0.05rem;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 14px;
        }

        .stCaption {
            line-height: 1.35;
        }

        .ag-theme-streamlit {
            --ag-font-size: 13px;
            --ag-row-height: 42px;
            --ag-header-height: 44px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ==========================================================
# DATA
# ==========================================================


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def _load_operation_history(
    user_id: str,
) -> list[OperationRow]:
    """
    Membaca seluruh riwayat non-ONGOING dan attachment
    yang dapat diakses user melalui RLS.
    """

    supabase = get_supabase_client()

    event_response = (
        supabase
        .table(
            "vw_kejadian_penyulang_detail"
        )
        .select("*")
        .neq(
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
        .execute()
    )

    if not event_response.data:
        return []

    rows = cast(
        list[OperationRow],
        event_response.data,
    )

    attachment_response = (
        supabase
        .table(
            "trx_kejadian_attachment"
        )
        .select(
            "attachment_id,event_id,file_name,file_path,"
            "file_type,file_size,attachment_type,description,created_at"
        )
        .order(
            "created_at",
            desc=False,
        )
        .execute()
    )

    attachments_by_event: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    if attachment_response.data:
        attachment_rows = cast(
            list[dict[str, Any]],
            attachment_response.data,
        )

        for attachment in attachment_rows:
            event_id = str(
                attachment.get(
                    "event_id"
                )
                or ""
            ).strip()

            if not event_id:
                continue

            attachments_by_event.setdefault(
                event_id,
                [],
            ).append(
                attachment
            )

    approved_report_response = (
        supabase
        .table(
            "trx_monthly_report"
        )
        .select(
            "scope_functloc_id,report_year,report_month,status"
        )
        .eq(
            "status",
            "APPROVED",
        )
        .execute()
    )

    approved_report_keys: set[
        tuple[str, int, int]
    ] = set()

    if approved_report_response.data:
        approved_rows = cast(
            list[dict[str, Any]],
            approved_report_response.data,
        )

        for report in approved_rows:
            gi_flc = str(
                report.get(
                    "scope_functloc_id"
                )
                or ""
            ).strip()

            report_year_raw = report.get(
                "report_year"
            )

            report_month_raw = report.get(
                "report_month"
            )

            if (
                report_year_raw is None
                or report_month_raw is None
            ):
                continue

            try:
                report_year = int(
                    str(
                        report_year_raw
                    )
                )

                report_month = int(
                    str(
                        report_month_raw
                    )
                )

            except (
                TypeError,
                ValueError,
            ):
                continue

            if gi_flc:
                approved_report_keys.add(
                    (
                        gi_flc,
                        report_year,
                        report_month,
                    )
                )

    for row in rows:
        event_id = str(
            row.get(
                "event_id"
            )
            or ""
        ).strip()

        evidence_files = (
            attachments_by_event.get(
                event_id,
                [],
            )
        )

        row[
            "_evidence_files"
        ] = evidence_files

        row[
            "_evidence_count"
        ] = len(
            evidence_files
        )

        row[
            "_first_evidence_url"
        ] = (
            str(
                evidence_files[0].get(
                    "file_path"
                )
                or ""
            ).strip()
            if evidence_files
            else ""
        )

        event_date = _parse_date(
            row.get(
                "event_date"
            )
        )

        gi_flc = str(
            row.get(
                "gi_flc"
            )
            or ""
        ).strip()

        row[
            "_is_monthly_verified"
        ] = bool(
            event_date is not None
            and gi_flc
            and (
                gi_flc,
                event_date.year,
                event_date.month,
            )
            in approved_report_keys
        )

    return rows


def clear_operation_history_cache() -> None:
    _load_operation_history.clear()


# ==========================================================
# GENERIC HELPERS
# ==========================================================


def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        if value is None:
            return default

        return float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return default


def _safe_int(
    value: Any,
) -> int | None:
    if value is None:
        return None

    try:
        return int(
            float(
                value
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        return None


def _safe_string(
    value: Any,
    default: str = "-",
) -> str:
    if value is None:
        return default

    text = str(
        value
    ).strip()

    return text or default


def _parse_date(
    value: Any,
) -> date | None:
    if value is None:
        return None

    if isinstance(
        value,
        datetime,
    ):
        return value.date()

    if isinstance(
        value,
        date,
    ):
        return value

    text = str(
        value
    ).strip()

    if not text:
        return None

    try:
        return datetime.strptime(
            text[:10],
            "%Y-%m-%d",
        ).date()

    except ValueError:
        return None


def _format_date(
    value: Any,
) -> str:
    parsed = _parse_date(
        value
    )

    if parsed is None:
        return "-"

    return parsed.strftime(
        "%d-%m-%Y"
    )


def _format_time(
    value: Any,
) -> str:
    if value is None:
        return "-"

    text = str(
        value
    ).strip()

    if not text:
        return "-"

    return text[:5]


def _format_datetime_compact(
    date_value: Any,
    time_value: Any,
) -> str:
    formatted_date = _format_date(
        date_value
    )

    formatted_time = _format_time(
        time_value
    )

    if (
        formatted_date == "-"
        and formatted_time == "-"
    ):
        return "-"

    if formatted_date == "-":
        return formatted_time

    if formatted_time == "-":
        return formatted_date

    return (
        f"{formatted_date} "
        f"{formatted_time}"
    )


def _format_number(
    value: Any,
    decimals: int = 2,
) -> str:
    if value is None:
        return "-"

    try:
        return (
            f"{float(value):,.{decimals}f}"
        )

    except (
        TypeError,
        ValueError,
    ):
        return str(
            value
        )


def _format_integer(
    value: Any,
) -> str:
    parsed = _safe_int(
        value
    )

    if parsed is None:
        return "-"

    return (
        f"{parsed:,}"
    )


def _phase_current_value(
    row: OperationRow,
    *,
    phase_field: str,
    legacy_field: str,
) -> float | None:
    """
    Membaca arus per phasa.
    Fallback ke field legacy untuk record lama.
    """

    phase_value = row.get(
        phase_field
    )

    if phase_value is not None:
        return _safe_float(
            phase_value
        )

    legacy_value = row.get(
        legacy_field
    )

    if legacy_value is not None:
        return _safe_float(
            legacy_value
        )

    return None


def _three_phase_average_from_row(
    row: OperationRow,
    *,
    prefix: str,
    legacy_field: str,
) -> float | None:
    """
    Iavg = (IR + IS + IT) / 3.
    """

    current_r = _phase_current_value(
        row,
        phase_field=f"{prefix}_r_a",
        legacy_field=legacy_field,
    )

    current_s = _phase_current_value(
        row,
        phase_field=f"{prefix}_s_a",
        legacy_field=legacy_field,
    )

    current_t = _phase_current_value(
        row,
        phase_field=f"{prefix}_t_a",
        legacy_field=legacy_field,
    )

    if (
        current_r is None
        or current_s is None
        or current_t is None
    ):
        return None

    return (
        current_r
        + current_s
        + current_t
    ) / 3.0


def _format_duration(
    value: Any,
) -> str:
    if value is None:
        return "-"

    try:
        minutes = float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return "-"

    if minutes < 0:
        return "-"

    total_minutes = int(
        round(
            minutes
        )
    )

    if total_minutes < 60:
        return (
            f"{total_minutes} menit"
        )

    hours = (
        total_minutes // 60
    )

    remaining_minutes = (
        total_minutes % 60
    )

    if hours < 24:
        return (
            f"{hours} jam "
            f"{remaining_minutes} menit"
        )

    days = (
        hours // 24
    )

    remaining_hours = (
        hours % 24
    )

    return (
        f"{days} hari "
        f"{remaining_hours} jam "
        f"{remaining_minutes} menit"
    )


def _format_array_values(
    value: Any,
) -> str:
    if value is None:
        return "-"

    if isinstance(
        value,
        list,
    ):
        values = [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

        return (
            ", ".join(
                values
            )
            if values
            else "-"
        )

    text = str(
        value
    ).strip()

    if not text:
        return "-"

    if (
        text.startswith("[")
        and text.endswith("]")
    ):
        text = (
            text
            .replace("[", "")
            .replace("]", "")
            .replace('"', "")
        )

    return (
        text.strip()
        or "-"
    )


def _phase_label(
    row: OperationRow,
) -> str:
    phases: list[str] = []

    if row.get("phase_r"):
        phases.append("R")

    if row.get("phase_s"):
        phases.append("S")

    if row.get("phase_t"):
        phases.append("T")

    if row.get("phase_n"):
        phases.append("N")

    return (
        "/".join(
            phases
        )
        if phases
        else "-"
    )


# ==========================================================
# LABEL HELPERS
# ==========================================================


def _operation_type_label(
    row: OperationRow,
) -> str:
    name = str(
        row.get(
            "event_type_name"
        )
        or ""
    ).strip()

    if name:
        return name

    code = str(
        row.get(
            "event_type_code"
        )
        or ""
    ).strip()

    return {
        "GANGGUAN":
            "Gangguan",

        "MANUVER":
            "Manuver",
    }.get(
        code,
        code or "-",
    )


def _record_status_label(
    row: OperationRow,
) -> str:
    name = str(
        row.get(
            "record_status_name"
        )
        or ""
    ).strip()

    if name:
        return name

    code = str(
        row.get(
            "record_status"
        )
        or ""
    ).strip()

    return {
        "RECOVERED":
            "Sudah Pulih",

        "CLOSED":
            "Selesai",

        "CANCELLED":
            "Dibatalkan",
    }.get(
        code,
        code or "-",
    )


def _supply_status_label(
    row: OperationRow,
) -> str:
    name = str(
        row.get(
            "supply_status_name"
        )
        or ""
    ).strip()

    if name:
        return name

    code = str(
        row.get(
            "supply_status_code"
        )
        or ""
    ).strip()

    return {
        "BELUM":
            "Belum Tersuplai",

        "FEEDER_ASAL":
            "Feeder Asal",

        "MANUVER_PENUH":
            "Manuver Penuh",

        "MANUVER_SEBAGIAN":
            "Manuver Sebagian",
    }.get(
        code,
        code or "-",
    )


def _pmt_recovery_label(
    row: OperationRow,
) -> str:
    name = str(
        row.get(
            "recovery_status_name"
        )
        or ""
    ).strip()

    if name:
        return name

    code = str(
        row.get(
            "recovery_status_code"
        )
        or ""
    ).strip()

    return {
        "MASUK":
            "Masuk",

        "MASUK_TRIP":
            "Masuk - Trip Kembali",
    }.get(
        code,
        code or "Belum Normal",
    )


# ==========================================================
# FILTER
# ==========================================================


def _unique_values(
    rows: list[OperationRow],
    field: str,
) -> list[str]:
    return sorted(
        {
            str(
                row.get(
                    field
                )
                or ""
            ).strip()
            for row in rows
            if str(
                row.get(
                    field
                )
                or ""
            ).strip()
        }
    )


def _reset_filters() -> None:
    keys = [
        "history_date_range",
        "history_operation_type",
        "history_ultg",
        "history_gi",
        "history_record_status",
        "history_search",
    ]

    for key in keys:
        st.session_state.pop(
            key,
            None,
        )


def _format_operation_filter(
    value: Any,
) -> str:
    labels: dict[str, str] = {
        "SEMUA": "Semua",
        "GANGGUAN": "Gangguan",
        "MANUVER": "Manuver",
    }

    text = str(
        value
        or ""
    )

    return labels.get(
        text,
        text,
    )


def _format_status_filter(
    value: Any,
) -> str:
    labels: dict[str, str] = {
        "SEMUA": "Semua",
        "RECOVERED": "Sudah Pulih",
        "CLOSED": "Selesai",
        "CANCELLED": "Dibatalkan",
    }

    text = str(
        value
        or ""
    )

    return labels.get(
        text,
        text,
    )


def _format_ultg_filter(
    value: Any,
) -> str:
    text = str(
        value
        or ""
    )

    if text == "SEMUA":
        return "Semua ULTG"

    return text


def _format_gi_filter(
    value: Any,
) -> str:
    text = str(
        value
        or ""
    )

    if text == "SEMUA":
        return "Semua GI"

    return text


def _render_filters(
    rows: list[OperationRow],
) -> list[OperationRow]:
    today = date.today()

    first_day = today.replace(
        day=1
    )

    with st.container(
        border=True
    ):
        col_title, col_reset = (
            st.columns(
                [6, 1]
            )
        )

        with col_title:
            st.markdown(
                "#### Filter Riwayat"
            )

            st.caption(
                "Default menampilkan data bulan berjalan."
            )

        with col_reset:
            if st.button(
                "Reset",
                icon=":material/restart_alt:",
                use_container_width=True,
                key="history_reset_filter",
            ):
                _reset_filters()
                st.rerun()

        (
            col_period,
            col_type,
            col_status,
        ) = st.columns(
            [2.2, 1, 1]
        )

        with col_period:
            date_range = st.date_input(
                "Periode",
                value=(
                    first_day,
                    today,
                ),
                key="history_date_range",
            )

        if (
            isinstance(
                date_range,
                tuple,
            )
            and len(
                date_range
            ) == 2
        ):
            start_date = date_range[0]
            end_date = date_range[1]

        else:
            start_date = first_day
            end_date = today

        with col_type:
            operation_type = st.selectbox(
                "Jenis Operasi",
                options=[
                    "SEMUA",
                    "GANGGUAN",
                    "MANUVER",
                ],
                format_func=_format_operation_filter,
                key="history_operation_type",
            )

        with col_status:
            selected_status = st.selectbox(
                "Status",
                options=[
                    "SEMUA",
                    "RECOVERED",
                    "CLOSED",
                    "CANCELLED",
                ],
                format_func=_format_status_filter,
                key="history_record_status",
            )

        ultg_options = _unique_values(
            rows,
            "ultg_name",
        )

        (
            col_ultg,
            col_gi,
            col_search,
        ) = st.columns(
            [1, 1.4, 2]
        )

        with col_ultg:
            selected_ultg = st.selectbox(
                "ULTG",
                options=[
                    "SEMUA",
                    *ultg_options,
                ],
                format_func=_format_ultg_filter,
                key="history_ultg",
            )

        if (
            selected_ultg
            == "SEMUA"
        ):
            gi_source_rows = rows

        else:
            gi_source_rows = [
                row
                for row in rows
                if str(
                    row.get(
                        "ultg_name"
                    )
                    or ""
                ).strip()
                == selected_ultg
            ]

        gi_options = _unique_values(
            gi_source_rows,
            "gi_name",
        )

        current_gi = str(
            st.session_state.get(
                "history_gi",
                "SEMUA",
            )
            or "SEMUA"
        )

        if (
            current_gi
            not in {
                "SEMUA",
                *gi_options,
            }
        ):
            st.session_state[
                "history_gi"
            ] = "SEMUA"

        with col_gi:
            selected_gi = st.selectbox(
                "Gardu Induk",
                options=[
                    "SEMUA",
                    *gi_options,
                ],
                format_func=_format_gi_filter,
                key="history_gi",
            )

        with col_search:
            keyword = st.text_input(
                "Cari",
                placeholder=(
                    "Kode / nama penyulang, alias, GI, Bay..."
                ),
                key="history_search",
            )

    if start_date > end_date:
        st.warning(
            "Tanggal awal tidak boleh lebih besar "
            "dari tanggal akhir."
        )

        return []

    keyword_normalized = str(
        keyword
        or ""
    ).strip().lower()

    filtered_rows: list[
        OperationRow
    ] = []

    for row in rows:
        row_date = _parse_date(
            row.get(
                "event_date"
            )
        )

        if row_date is None:
            continue

        if (
            row_date < start_date
            or row_date > end_date
        ):
            continue

        if (
            selected_ultg
            != "SEMUA"
            and str(
                row.get(
                    "ultg_name"
                )
                or ""
            ).strip()
            != selected_ultg
        ):
            continue

        if (
            selected_gi
            != "SEMUA"
            and str(
                row.get(
                    "gi_name"
                )
                or ""
            ).strip()
            != selected_gi
        ):
            continue

        if (
            operation_type
            != "SEMUA"
            and str(
                row.get(
                    "event_type_code"
                )
                or ""
            ).strip()
            != operation_type
        ):
            continue

        if (
            selected_status
            != "SEMUA"
            and str(
                row.get(
                    "record_status"
                )
                or ""
            ).strip()
            != selected_status
        ):
            continue

        if keyword_normalized:
            searchable = " ".join(
                [
                    str(
                        row.get(
                            "penyulang_code"
                        )
                        or ""
                    ),
                    str(
                        row.get(
                            "penyulang_name"
                        )
                        or ""
                    ),
                    str(
                        row.get(
                            "penyulang_alias"
                        )
                        or ""
                    ),
                    str(
                        row.get(
                            "gi_name"
                        )
                        or ""
                    ),
                    str(
                        row.get(
                            "bay_name"
                        )
                        or ""
                    ),
                ]
            ).lower()

            if (
                keyword_normalized
                not in searchable
            ):
                continue

        filtered_rows.append(
            row
        )

    return filtered_rows


# ==========================================================
# SUMMARY
# ==========================================================


def _render_summary(
    rows: list[OperationRow],
) -> None:
    total = len(
        rows
    )

    gangguan = sum(
        1
        for row in rows
        if str(
            row.get(
                "event_type_code"
            )
            or ""
        ).strip()
        == "GANGGUAN"
    )

    manuver = sum(
        1
        for row in rows
        if str(
            row.get(
                "event_type_code"
            )
            or ""
        ).strip()
        == "MANUVER"
    )

    total_ens = sum(
        _safe_float(
            row.get(
                "ens_kwh"
            )
        )
        for row in rows
    )

    (
        col_total,
        col_gangguan,
        col_manuver,
        col_ens,
    ) = st.columns(
        4
    )

    with col_total:
        st.metric(
            "Total Record",
            total,
        )

    with col_gangguan:
        st.metric(
            "Gangguan",
            gangguan,
        )

    with col_manuver:
        st.metric(
            "Manuver",
            manuver,
        )

    with col_ens:
        st.metric(
            "Total ENS",
            f"{total_ens:,.2f} kWh",
        )


# ==========================================================
# AGGRID DATA
# ==========================================================


def _build_grid_dataframe(
    rows: list[OperationRow],
) -> pd.DataFrame:
    """
    Tabel utama Riwayat Operasi dibuat lengkap.

    Urutan kolom:
    1. Identitas
    2. Klasifikasi
    3. Parameter awal
    4. Proteksi
    5. Pemulihan beban
    6. Normalisasi PMT
    7. Durasi / ENS
    8. Evidence
    9. Action
    """

    data: list[
        dict[str, Any]
    ] = []

    for row in rows:
        evidence_count = int(
            row.get(
                "_evidence_count"
            )
            or 0
        )

        first_evidence_url = str(
            row.get(
                "_first_evidence_url"
            )
            or ""
        ).strip()

        evidence_files_raw = row.get(
            "_evidence_files"
        )

        evidence_files = (
            evidence_files_raw
            if isinstance(
                evidence_files_raw,
                list,
            )
            else []
        )

        evidence_links = [
            {
                "name":
                    str(
                        item.get(
                            "file_name"
                        )
                        or f"Evidence {index}"
                    ).strip(),

                "url":
                    str(
                        item.get(
                            "file_path"
                        )
                        or ""
                    ).strip(),
            }
            for index, item in enumerate(
                evidence_files,
                start=1,
            )
            if isinstance(
                item,
                dict,
            )
            and str(
                item.get(
                    "file_path"
                )
                or ""
            ).strip()
        ]

        data.append(
            {
                "_event_id":
                    str(
                        row.get(
                            "event_id"
                        )
                        or ""
                    ),

                "_action":
                    "",

                "_evidence_url":
                    first_evidence_url,

                "_evidence_links":
                    json.dumps(
                        evidence_links,
                        ensure_ascii=False,
                    ),

                "_is_monthly_verified":
                    bool(
                        row.get(
                            "_is_monthly_verified"
                        )
                    ),

                # ==========================================
                # 1. IDENTITAS
                # ==========================================

                "Tanggal":
                    _format_date(
                        row.get(
                            "event_date"
                        )
                    ),

                "Waktu":
                    _format_time(
                        row.get(
                            "event_time"
                        )
                    ),

                "Jenis":
                    _operation_type_label(
                        row
                    ),

                "ULTG":
                    _safe_string(
                        row.get(
                            "ultg_name"
                        )
                    ),

                "Gardu Induk":
                    _safe_string(
                        row.get(
                            "gi_name"
                        )
                    ),

                "Bay":
                    _safe_string(
                        row.get(
                            "bay_name"
                        )
                    ),

                "Penyulang":
                    _safe_string(
                        row.get(
                            "penyulang_code"
                        )
                    ),

                "Nama Penyulang":
                    _safe_string(
                        row.get(
                            "penyulang_name"
                        )
                    ),

                "Alias":
                    _safe_string(
                        row.get(
                            "penyulang_alias"
                        )
                    ),

                # ==========================================
                # 2. KLASIFIKASI
                # ==========================================

                "PMT Awal":
                    _safe_string(
                        row.get(
                            "pmt_status_name"
                        ),
                        _safe_string(
                            row.get(
                                "pmt_status_code"
                            )
                        ),
                    ),

                "PIC":
                    _safe_string(
                        row.get(
                            "pic_name"
                        ),
                        _safe_string(
                            row.get(
                                "pic_code"
                            )
                        ),
                    ),

                "Klasifikasi":
                    _safe_string(
                        row.get(
                            "cause_name"
                        ),
                        _safe_string(
                            row.get(
                                "cause_code"
                            )
                        ),
                    ),

                # ==========================================
                # 3. PARAMETER AWAL
                # ==========================================

                "Arus Sebelum R (A)":
                    _phase_current_value(
                        row,
                        phase_field="load_current_before_r_a",
                        legacy_field="load_current_before_a",
                    ),

                "Arus Sebelum S (A)":
                    _phase_current_value(
                        row,
                        phase_field="load_current_before_s_a",
                        legacy_field="load_current_before_a",
                    ),

                "Arus Sebelum T (A)":
                    _phase_current_value(
                        row,
                        phase_field="load_current_before_t_a",
                        legacy_field="load_current_before_a",
                    ),

                "Tegangan Sebelum (kV)":
                    (
                        _safe_float(
                            row.get(
                                "voltage_before_kv"
                            )
                        )
                        if row.get(
                            "voltage_before_kv"
                        )
                        is not None
                        else None
                    ),

                "PF":
                    (
                        _safe_float(
                            row.get(
                                "power_factor_before"
                            ),
                            0.85,
                        )
                        if row.get(
                            "power_factor_before"
                        )
                        is not None
                        else 0.85
                    ),

                # ==========================================
                # 4. PROTEKSI
                # ==========================================

                "Annunciator":
                    _safe_string(
                        row.get(
                            "annunciator_name"
                        ),
                        _safe_string(
                            row.get(
                                "annunciator_code"
                            )
                        ),
                    ),

                "Indikasi":
                    _format_array_values(
                        row.get(
                            "indikasi_names"
                        )
                    ),

                "Phasa":
                    _phase_label(
                        row
                    ),

                "I-R (A)":
                    (
                        _safe_float(
                            row.get(
                                "fault_current_r_a"
                            )
                        )
                        if row.get(
                            "fault_current_r_a"
                        )
                        is not None
                        else None
                    ),

                "I-S (A)":
                    (
                        _safe_float(
                            row.get(
                                "fault_current_s_a"
                            )
                        )
                        if row.get(
                            "fault_current_s_a"
                        )
                        is not None
                        else None
                    ),

                "I-T (A)":
                    (
                        _safe_float(
                            row.get(
                                "fault_current_t_a"
                            )
                        )
                        if row.get(
                            "fault_current_t_a"
                        )
                        is not None
                        else None
                    ),

                "I-N (A)":
                    (
                        _safe_float(
                            row.get(
                                "fault_current_n_a"
                            )
                        )
                        if row.get(
                            "fault_current_n_a"
                        )
                        is not None
                        else None
                    ),

                # ==========================================
                # 5. PEMULIHAN BEBAN
                # ==========================================

                "Status Suplai":
                    _supply_status_label(
                        row
                    ),

                "Mulai Tersuplai":
                    _format_datetime_compact(
                        row.get(
                            "supply_restored_date"
                        ),
                        row.get(
                            "supply_restored_time"
                        ),
                    ),

                "Termanuver R (A)":
                    _phase_current_value(
                        row,
                        phase_field="maneuvered_current_r_a",
                        legacy_field="maneuvered_current_a",
                    ),

                "Termanuver S (A)":
                    _phase_current_value(
                        row,
                        phase_field="maneuvered_current_s_a",
                        legacy_field="maneuvered_current_a",
                    ),

                "Termanuver T (A)":
                    _phase_current_value(
                        row,
                        phase_field="maneuvered_current_t_a",
                        legacy_field="maneuvered_current_a",
                    ),

                "Sisa R (A)":
                    _phase_current_value(
                        row,
                        phase_field="remaining_current_r_a",
                        legacy_field="remaining_current_a",
                    ),

                "Sisa S (A)":
                    _phase_current_value(
                        row,
                        phase_field="remaining_current_s_a",
                        legacy_field="remaining_current_a",
                    ),

                "Sisa T (A)":
                    _phase_current_value(
                        row,
                        phase_field="remaining_current_t_a",
                        legacy_field="remaining_current_a",
                    ),

                "Beban Normal":
                    (
                        "Ya"
                        if bool(
                            row.get(
                                "final_supply_normalized"
                            )
                        )
                        else "Tidak"
                    ),

                "Normalisasi Beban":
                    _format_datetime_compact(
                        row.get(
                            "final_supply_normalization_date"
                        ),
                        row.get(
                            "final_supply_normalization_time"
                        ),
                    ),

                # ==========================================
                # 6. NORMALISASI PMT
                # ==========================================

                "PMT Akhir":
                    _pmt_recovery_label(
                        row
                    ),

                "Waktu Operasi PMT":
                    _format_datetime_compact(
                        row.get(
                            "recovery_date"
                        ),
                        row.get(
                            "recovery_time"
                        ),
                    ),

                "Counter PMT":
                    _safe_int(
                        row.get(
                            "pmt_counter_after"
                        )
                    ),

                "Arus Setelah R (A)":
                    _phase_current_value(
                        row,
                        phase_field="load_current_after_r_a",
                        legacy_field="load_current_after_a",
                    ),

                "Arus Setelah S (A)":
                    _phase_current_value(
                        row,
                        phase_field="load_current_after_s_a",
                        legacy_field="load_current_after_a",
                    ),

                "Arus Setelah T (A)":
                    _phase_current_value(
                        row,
                        phase_field="load_current_after_t_a",
                        legacy_field="load_current_after_a",
                    ),

                "Tegangan Setelah (kV)":
                    (
                        _safe_float(
                            row.get(
                                "voltage_after_kv"
                            )
                        )
                        if row.get(
                            "voltage_after_kv"
                        )
                        is not None
                        else None
                    ),

                # ==========================================
                # 7. DURASI / ENS
                # ==========================================

                "Durasi Padam (menit)":
                    (
                        _safe_float(
                            row.get(
                                "customer_outage_duration_min"
                            )
                        )
                        if row.get(
                            "customer_outage_duration_min"
                        )
                        is not None
                        else None
                    ),

                "Durasi PMT (menit)":
                    (
                        _safe_float(
                            row.get(
                                "pmt_condition_duration_min"
                            )
                        )
                        if row.get(
                            "pmt_condition_duration_min"
                        )
                        is not None
                        else None
                    ),

                "ENS (kWh)":
                    (
                        _safe_float(
                            row.get(
                                "ens_kwh"
                            )
                        )
                        if row.get(
                            "ens_kwh"
                        )
                        is not None
                        else None
                    ),

                "Status":
                    _record_status_label(
                        row
                    ),

                "Status Laporan":
                    (
                        "Terverifikasi"
                        if bool(
                            row.get(
                                "_is_monthly_verified"
                            )
                        )
                        else "Belum Terverifikasi"
                    ),

                # ==========================================
                # 8. KETERANGAN
                # ==========================================

                "Kronologi":
                    _safe_string(
                        row.get(
                            "event_description"
                        )
                    ),

                "Keterangan Pemulihan":
                    _safe_string(
                        row.get(
                            "recovery_description"
                        )
                    ),

                "Catatan":
                    _safe_string(
                        row.get(
                            "notes"
                        )
                    ),

                # ==========================================
                # 9. EVIDENCE / ACTION
                # ==========================================

                "Evidence":
                    (
                        (
                            f"📎 {evidence_count}"
                            if evidence_count > 1
                            else "📎"
                        )
                        if first_evidence_url
                        else "-"
                    ),

                "File":
                    (
                        evidence_count
                        if evidence_count > 0
                        else None
                    ),

                "Detail":
                    "DETAIL",

                "Edit":
                    "EDIT",

                "Delete":
                    "DELETE",
            }
        )

    return pd.DataFrame(
        data
    )


def _action_renderer(
    *,
    icon: str,
    title: str,
    action: str,
) -> JsCode:
    """
    Renderer icon action.

    Klik icon:
    1. isi hidden field _action
    2. pilih row
    3. trigger selection change agar Streamlit rerun
    """

    return JsCode(
        f"""
        class ActionRenderer {{
            init(params) {{
                this.eGui = document.createElement('div');
                this.eGui.style.display = 'flex';
                this.eGui.style.alignItems = 'center';
                this.eGui.style.justifyContent = 'center';
                this.eGui.style.height = '100%';

                const locked = Boolean(
                    params.data
                    && params.data._is_monthly_verified
                );

                const btn = document.createElement('button');

                if (
                    locked
                    && (
                        '{action}' === 'EDIT'
                        || '{action}' === 'DELETE'
                    )
                ) {{
                    btn.innerHTML = '🔒';
                    btn.title = 'Terkunci — laporan bulanan sudah terverifikasi';
                    btn.style.opacity = '0.45';
                    btn.style.cursor = 'not-allowed';
                    btn.disabled = true;
                }} else {{
                    btn.innerHTML = '{icon}';
                    btn.title = '{title}';
                    btn.style.cursor = 'pointer';
                }}

                btn.style.border = 'none';
                btn.style.background = 'transparent';
                btn.style.fontSize = '18px';
                btn.style.padding = '4px 8px';

                btn.addEventListener('click', (event) => {{
                    if (locked && ('{action}' === 'EDIT' || '{action}' === 'DELETE')) {{
                        event.stopPropagation();
                        return;
                    }}
                    event.stopPropagation();

                    params.node.setDataValue(
                        '_action',
                        '{action}'
                    );

                    params.api.deselectAll();

                    params.node.setSelected(
                        true,
                        true
                    );

                    params.api.dispatchEvent({{
                        type: 'selectionChanged'
                    }});
                }});

                this.eGui.appendChild(btn);
            }}

            getGui() {{
                return this.eGui;
            }}
        }}
        """
    )


def _evidence_renderer() -> JsCode:
    return JsCode(
        """
        class EvidenceRenderer {
            init(params) {
                this.eGui = document.createElement('div');
                this.eGui.style.display = 'flex';
                this.eGui.style.alignItems = 'center';
                this.eGui.style.justifyContent = 'center';
                this.eGui.style.height = '100%';

                const url = (
                    params.data
                    ? params.data._evidence_url
                    : ''
                );

                const count = Number(
                    params.data && params.data.File
                    ? params.data.File
                    : 0
                );

                if (!url || count <= 0) {
                    this.eGui.innerHTML = '-';
                    return;
                }

                const btn = document.createElement('button');
                btn.style.border = 'none';
                btn.style.background = 'transparent';
                btn.style.cursor = 'pointer';
                btn.style.fontSize = '16px';
                btn.style.padding = '4px 8px';
                btn.style.whiteSpace = 'nowrap';
                btn.title = (
                    count > 1
                    ? 'Buka daftar Evidence'
                    : 'Buka Evidence'
                );
                btn.innerHTML = (
                    count > 1
                    ? `📎 ${count}`
                    : '📎'
                );

                btn.addEventListener('click', (event) => {
                    event.stopPropagation();

                    if (count === 1) {
                        window.open(
                            url,
                            '_blank',
                            'noopener,noreferrer'
                        );
                        return;
                    }

                    params.node.setDataValue(
                        '_action',
                        'EVIDENCE'
                    );

                    params.api.deselectAll();

                    params.node.setSelected(
                        true,
                        true
                    );

                    params.api.dispatchEvent({
                        type: 'selectionChanged'
                    });
                });

                this.eGui.appendChild(btn);
            }

            getGui() {
                return this.eGui;
            }
        }
        """
    )


def _render_history_grid(
    rows: list[OperationRow],
) -> tuple[
    OperationRow | None,
    str | None,
]:
    dataframe = _build_grid_dataframe(
        rows
    )

    gb = GridOptionsBuilder.from_dataframe(
        dataframe
    )

    gb.configure_default_column(
        sortable=True,
        filter=True,
        resizable=True,
        suppressMovable=False,
    )

    gb.configure_selection(
        selection_mode="single",
        use_checkbox=False,
    )

    gb.configure_grid_options(
        suppressRowClickSelection=True,
        rowHeight=42,
        headerHeight=44,
        animateRows=False,
        onFirstDataRendered=JsCode(
            """
            function(params) {
                const excluded = new Set([
                    '_event_id',
                    '_action',
                    '_evidence_url',
                    '_evidence_links',
                    '_is_monthly_verified',
                    'Evidence',
                    'File',
                    'Detail',
                    'Edit',
                    'Delete'
                ]);

                const columnIds = params.api
                    .getColumns()
                    .map(col => col.getColId())
                    .filter(colId => !excluded.has(colId));

                params.api.autoSizeColumns(
                    columnIds,
                    false
                );
            }
            """
        ),
    )

    # ======================================================
    # INTERNAL
    # ======================================================

    gb.configure_column(
        "_event_id",
        hide=True,
    )

    gb.configure_column(
        "_action",
        hide=True,
    )

    gb.configure_column(
        "_evidence_url",
        hide=True,
    )

    gb.configure_column(
        "_evidence_links",
        hide=True,
    )

    gb.configure_column(
        "_is_monthly_verified",
        hide=True,
    )

    # ======================================================
    # IDENTITAS
    # ======================================================

    gb.configure_column(
        "Tanggal",
        pinned="left",
    )

    gb.configure_column(
        "Waktu",
        pinned="left",
    )

    gb.configure_column(
        "Jenis",
        pinned="left",
    )

    gb.configure_column(
        "ULTG",
    )

    gb.configure_column(
        "Gardu Induk",
        minWidth=170,
    )

    gb.configure_column(
        "Bay",
        minWidth=190,
    )

    gb.configure_column(
        "Penyulang",
        minWidth=115,
    )

    gb.configure_column(
        "Nama Penyulang",
        minWidth=180,
    )

    gb.configure_column(
        "Alias",
        minWidth=110,
    )

    # ======================================================
    # KLASIFIKASI
    # ======================================================

    gb.configure_column(
        "PMT Awal",
        minWidth=105,
    )

    gb.configure_column(
        "PIC",
        minWidth=90,
    )

    gb.configure_column(
        "Klasifikasi",
        minWidth=190,
    )

    # ======================================================
    # PARAMETER AWAL
    # ======================================================

    for column_name in (
        "Arus Sebelum R (A)",
        "Arus Sebelum S (A)",
        "Arus Sebelum T (A)",
        "Tegangan Sebelum (kV)",
        "PF",
        "I-R (A)",
        "I-S (A)",
        "I-T (A)",
        "I-N (A)",
        "Beban Termanuver (A)",
        "Sisa Beban (A)",
        "Counter PMT",
        "Arus Setelah R (A)",
        "Arus Setelah S (A)",
        "Arus Setelah T (A)",
        "Tegangan Setelah (kV)",
        "Durasi Padam (menit)",
        "Durasi PMT (menit)",
        "ENS (kWh)",
        "File",
    ):
        gb.configure_column(
            column_name,
            type=[
                "numericColumn",
            ],
            minWidth=110,
        )

    gb.configure_column(
        "PF",
        width=78,
        minWidth=78,
        maxWidth=90,
    )


    for column_name in (
        "Arus Sebelum R (A)",
        "Arus Sebelum S (A)",
        "Arus Sebelum T (A)",
        "Arus Setelah R (A)",
        "Arus Setelah S (A)",
        "Arus Setelah T (A)",
    ):
        gb.configure_column(
            column_name,
            width=125,
            minWidth=120,
            maxWidth=145,
        )

    # ======================================================
    # PROTEKSI
    # ======================================================

    gb.configure_column(
        "Annunciator",
        minWidth=170,
    )

    gb.configure_column(
        "Indikasi",
        minWidth=180,
    )

    gb.configure_column(
        "Phasa",
        minWidth=85,
    )

    # ======================================================
    # PEMULIHAN / NORMALISASI
    # ======================================================

    gb.configure_column(
        "Status Suplai",
        minWidth=155,
    )

    gb.configure_column(
        "Mulai Tersuplai",
        minWidth=155,
    )

    gb.configure_column(
        "Beban Normal",
        minWidth=105,
    )

    gb.configure_column(
        "Normalisasi Beban",
        minWidth=160,
    )

    gb.configure_column(
        "PMT Akhir",
        minWidth=155,
    )

    gb.configure_column(
        "Waktu Operasi PMT",
        minWidth=155,
    )

    gb.configure_column(
        "Status",
        minWidth=115,
    )

    gb.configure_column(
        "Status Laporan",
        minWidth=150,
    )

    # ======================================================
    # TEXT DETAIL
    # ======================================================

    gb.configure_column(
        "Kronologi",
        minWidth=240,
    )

    gb.configure_column(
        "Keterangan Pemulihan",
        minWidth=240,
    )

    gb.configure_column(
        "Catatan",
        minWidth=180,
    )

    # ======================================================
    # EVIDENCE
    # ======================================================

    gb.configure_column(
        "Evidence",
        header_name="Evidence",
        width=86,
        minWidth=86,
        maxWidth=96,
        sortable=False,
        filter=False,
        cellRenderer=_evidence_renderer(),
    )

    gb.configure_column(
        "File",
        width=72,
        minWidth=72,
        maxWidth=80,
    )

    # ======================================================
    # ACTION
    # ======================================================

    gb.configure_column(
        "Detail",
        header_name="",
        width=58,
        minWidth=58,
        maxWidth=58,
        sortable=False,
        filter=False,
        pinned="right",
        cellRenderer=_action_renderer(
            icon="🔎",
            title="Detail",
            action="DETAIL",
        ),
    )

    gb.configure_column(
        "Edit",
        header_name="",
        width=58,
        minWidth=58,
        maxWidth=58,
        sortable=False,
        filter=False,
        pinned="right",
        cellRenderer=_action_renderer(
            icon="✏️",
            title="Edit",
            action="EDIT",
        ),
    )

    gb.configure_column(
        "Delete",
        header_name="",
        width=58,
        minWidth=58,
        maxWidth=58,
        sortable=False,
        filter=False,
        pinned="right",
        cellRenderer=_action_renderer(
            icon="🗑️",
            title="Delete",
            action="DELETE",
        ),
    )

    grid_options = gb.build()

    response = AgGrid(
        dataframe,
        gridOptions=grid_options,
        height=600,
        width="100%",
        theme="streamlit",
        data_return_mode=(
            DataReturnMode.AS_INPUT
        ),
        update_mode=(
            GridUpdateMode.SELECTION_CHANGED
            | GridUpdateMode.VALUE_CHANGED
        ),
        allow_unsafe_jscode=True,
        fit_columns_on_grid_load=False,
        reload_data=False,
        key="history_aggrid",
    )

    selected_raw = response.get(
        "selected_rows"
    )

    selected_data: (
        dict[str, Any] | None
    ) = None

    if isinstance(
        selected_raw,
        pd.DataFrame,
    ):
        if not selected_raw.empty:
            selected_data = cast(
                dict[str, Any],
                selected_raw.iloc[
                    0
                ].to_dict(),
            )

    elif isinstance(
        selected_raw,
        list,
    ):
        if selected_raw:
            first = selected_raw[0]

            if isinstance(
                first,
                dict,
            ):
                selected_data = cast(
                    dict[str, Any],
                    first,
                )

    if selected_data is None:
        return None, None

    event_id = str(
        selected_data.get(
            "_event_id"
        )
        or ""
    ).strip()

    action = str(
        selected_data.get(
            "_action"
        )
        or ""
    ).strip().upper()

    if not event_id:
        return None, None

    selected_row: (
        OperationRow | None
    ) = next(
        (
            row
            for row in rows
            if str(
                row.get(
                    "event_id"
                )
                or ""
            ).strip()
            == event_id
        ),
        None,
    )

    if action not in {
        "DETAIL",
        "EDIT",
        "DELETE",
        "EVIDENCE",
    }:
        action = ""

    return (
        selected_row,
        action or None,
    )


# ==========================================================
# EDIT / DELETE ACTIONS
# ==========================================================


def _open_history_for_edit(
    row: OperationRow,
) -> None:
    event_id = str(
        row.get(
            "event_id"
        )
        or ""
    ).strip()

    if not event_id:
        st.error(
            "Event ID tidak valid."
        )
        return

    removable_prefixes = (
        "update_gangguan_",
        "history_gangguan_",
        "history_manuver_",
        "prepared_update_gangguan_",
        "prepared_history_gangguan_",
        "prepared_history_manuver_",
    )

    for key in list(
        st.session_state.keys()
    ):
        key_text = str(
            key
        )

        if any(
            key_text.startswith(
                prefix
            )
            for prefix
            in removable_prefixes
        ):
            st.session_state.pop(
                key,
                None,
            )

    st.session_state[
        "input_mode"
    ] = "UPDATE_HISTORY"

    st.session_state[
        "edit_event_id"
    ] = event_id

    st.session_state[
        "edit_event_source"
    ] = "RIWAYAT_OPERASI"

    st.switch_page(
        "pages/input_kejadian.py"
    )


@st.dialog(
    "Konfirmasi Hapus",
    width="small",
)
def _render_delete_dialog(
    row: OperationRow,
) -> None:
    event_id = str(
        row.get(
            "event_id"
        )
        or ""
    ).strip()

    st.warning(
        "Record akan dihapus dari data aktif."
    )

    st.caption(
        "Penghapusan bersifat soft delete dan "
        "masih dapat dipulihkan administrator."
    )

    st.write(
        f"**{_safe_string(row.get('penyulang_code'))} — "
        f"{_safe_string(row.get('penyulang_name'))}**"
    )

    st.caption(
        _format_datetime_compact(
            row.get(
                "event_date"
            ),
            row.get(
                "event_time"
            ),
        )
    )

    reason_key = (
        f"history_delete_reason_{event_id}"
    )

    delete_reason = st.text_area(
        "Alasan Penghapusan",
        placeholder=(
            "Contoh: Salah input, data duplikat, "
            "atau data tidak sesuai."
        ),
        key=reason_key,
        height=90,
    )

    col_cancel, col_delete = (
        st.columns(2)
    )

    with col_cancel:
        if st.button(
            "Batal",
            use_container_width=True,
            key=(
                f"history_delete_cancel_{event_id}"
            ),
        ):
            st.session_state.pop(
                "pending_delete_event_id",
                None,
            )

            st.session_state.pop(
                reason_key,
                None,
            )

            st.rerun()

    with col_delete:
        confirm = st.button(
            "Hapus",
            type="primary",
            icon=":material/delete:",
            use_container_width=True,
            disabled=(
                not bool(
                    str(
                        delete_reason
                        or ""
                    ).strip()
                )
            ),
            key=(
                f"history_delete_confirm_{event_id}"
            ),
        )

    if not confirm:
        return

    try:
        with st.spinner(
            "Menghapus record..."
        ):
            soft_delete_event(
                event_id=event_id,
                delete_reason=str(
                    delete_reason
                ).strip(),
            )

        clear_operation_history_cache()

        st.session_state.pop(
            "pending_delete_event_id",
            None,
        )

        st.session_state.pop(
            reason_key,
            None,
        )

        st.session_state[
            "history_flash_message"
        ] = (
            "Record berhasil dihapus dari data aktif."
        )

        st.rerun()

    except Exception as exc:
        st.error(
            "Record gagal dihapus."
        )

        st.exception(
            exc
        )


# ==========================================================
# EVIDENCE DETAIL
# ==========================================================


def _render_evidence_detail(
    row: OperationRow,
) -> None:
    evidence_raw = row.get(
        "_evidence_files"
    )

    evidence_files: list[
        dict[str, Any]
    ] = (
        evidence_raw
        if isinstance(
            evidence_raw,
            list,
        )
        else []
    )

    if not evidence_files:
        st.info(
            "Belum ada evidence untuk record ini."
        )

        return

    st.caption(
        f"{len(evidence_files)} file tersimpan di Google Drive."
    )

    for index, attachment in enumerate(
        evidence_files,
        start=1,
    ):
        file_name = _safe_string(
            attachment.get(
                "file_name"
            )
        )

        file_url = str(
            attachment.get(
                "file_path"
            )
            or ""
        ).strip()

        file_type = _safe_string(
            attachment.get(
                "file_type"
            )
        )

        with st.container(
            border=True
        ):
            col_file, col_open = (
                st.columns(
                    [5, 1]
                )
            )

            with col_file:
                st.write(
                    f"**{index}. {file_name}**"
                )

                st.caption(
                    file_type
                )

            with col_open:
                if file_url:
                    st.link_button(
                        "Buka",
                        file_url,
                        icon=":material/open_in_new:",
                        use_container_width=True,
                    )


@st.dialog(
    "Evidence",
    width="large",
)
def _render_evidence_dialog(
    row: OperationRow,
) -> None:
    st.markdown(
        f"**{_safe_string(row.get('penyulang_code'))} — "
        f"{_safe_string(row.get('penyulang_name'))}**"
    )

    st.caption(
        _format_datetime_compact(
            row.get(
                "event_date"
            ),
            row.get(
                "event_time"
            ),
        )
    )

    _render_evidence_detail(
        row
    )


# ==========================================================
# DETAIL
# ==========================================================


def _render_identity_detail(
    row: OperationRow,
) -> None:
    with st.container(
        border=True
    ):
        col_title, col_status = (
            st.columns(
                [5, 1]
            )
        )

        with col_title:
            st.markdown(
                f"### {_safe_string(row.get('penyulang_code'))} — "
                f"{_safe_string(row.get('penyulang_name'))}"
            )

            st.caption(
                f"{_safe_string(row.get('ultg_name'))} • "
                f"{_safe_string(row.get('gi_name'))} • "
                f"{_safe_string(row.get('bay_name'))}"
            )

        with col_status:
            st.caption(
                "Status"
            )

            st.write(
                f"**{_record_status_label(row)}**"
            )

            if bool(
                row.get(
                    "_is_monthly_verified"
                )
            ):
                st.caption(
                    "🔒 Terkunci oleh Laporan Bulanan Terverifikasi"
                )

        st.divider()

        col_a, col_b, col_c, col_d = (
            st.columns(4)
        )

        with col_a:
            st.caption(
                "Jenis Operasi"
            )

            st.write(
                f"**{_operation_type_label(row)}**"
            )

        with col_b:
            st.caption(
                "Waktu Operasi"
            )

            st.write(
                f"**{_format_datetime_compact(row.get('event_date'), row.get('event_time'))}**"
            )

        with col_c:
            st.caption(
                "PIC"
            )

            st.write(
                f"**{_safe_string(row.get('pic_name'), _safe_string(row.get('pic_code')))}**"
            )

        with col_d:
            st.caption(
                "Klasifikasi"
            )

            st.write(
                f"**{_safe_string(row.get('cause_name'), _safe_string(row.get('cause_code')))}**"
            )


def _render_parameter_detail(
    row: OperationRow,
) -> None:
    with st.container(
        border=True
    ):
        st.caption(
            "Arus Beban Sebelum Operasi"
        )

        col_r, col_s, col_t = (
            st.columns(3)
        )

        with col_r:
            st.metric(
                "Phasa R",
                f"{_format_number(_phase_current_value(row, phase_field='load_current_before_r_a', legacy_field='load_current_before_a'))} A",
            )

        with col_s:
            st.metric(
                "Phasa S",
                f"{_format_number(_phase_current_value(row, phase_field='load_current_before_s_a', legacy_field='load_current_before_a'))} A",
            )

        with col_t:
            st.metric(
                "Phasa T",
                f"{_format_number(_phase_current_value(row, phase_field='load_current_before_t_a', legacy_field='load_current_before_a'))} A",
            )

        st.divider()

        col_v, col_pf, col_pmt = (
            st.columns(3)
        )

        with col_v:
            st.metric(
                "Tegangan Sebelum",
                f"{_format_number(row.get('voltage_before_kv'))} kV",
            )

        with col_pf:
            pf_value = row.get(
                "power_factor_before"
            )

            if pf_value is None:
                pf_value = 0.85

            st.metric(
                "PF",
                _format_number(
                    pf_value,
                ),
            )

        with col_pmt:
            st.metric(
                "PMT Awal",
                _safe_string(
                    row.get(
                        "pmt_status_name"
                    ),
                    _safe_string(
                        row.get(
                            "pmt_status_code"
                        )
                    ),
                ),
            )

        average_before = (
            _three_phase_average_from_row(
                row,
                prefix="load_current_before",
                legacy_field="load_current_before_a",
            )
        )

        if average_before is not None:
            st.caption(
                "Arus rata-rata 3 phasa untuk kalkulasi ENS: "
                f"**{average_before:,.2f} A**"
            )


def _render_protection_detail(
    row: OperationRow,
) -> None:
    if str(
        row.get(
            "event_type_code"
        )
        or ""
    ).strip() != "GANGGUAN":
        st.info(
            "Parameter proteksi tidak digunakan pada Manuver."
        )

        return

    with st.container(
        border=True
    ):
        col_ann, col_ind, col_phase = (
            st.columns(
                [1, 1.8, 0.8]
            )
        )

        with col_ann:
            st.caption(
                "Annunciator"
            )

            st.write(
                f"**{_safe_string(row.get('annunciator_name'), _safe_string(row.get('annunciator_code')))}**"
            )

        with col_ind:
            st.caption(
                "Indikasi Relay"
            )

            st.write(
                f"**{_format_array_values(row.get('indikasi_names'))}**"
            )

        with col_phase:
            st.caption(
                "Phasa"
            )

            st.write(
                f"**{_phase_label(row)}**"
            )

        st.divider()

        values = [
            (
                "I-R",
                row.get(
                    "fault_current_r_a"
                ),
            ),
            (
                "I-S",
                row.get(
                    "fault_current_s_a"
                ),
            ),
            (
                "I-T",
                row.get(
                    "fault_current_t_a"
                ),
            ),
            (
                "I-N / Residual",
                row.get(
                    "fault_current_n_a"
                ),
            ),
        ]

        cols = st.columns(4)

        for col, (
            label,
            value,
        ) in zip(
            cols,
            values,
            strict=False,
        ):
            with col:
                st.metric(
                    label,
                    (
                        f"{_format_number(value)} A"
                    ),
                )


def _render_recovery_detail(
    row: OperationRow,
) -> None:
    with st.container(
        border=True
    ):
        col_supply, col_pmt, col_outage, col_ens = (
            st.columns(4)
        )

        with col_supply:
            st.caption(
                "Status Suplai"
            )

            st.write(
                f"**{_supply_status_label(row)}**"
            )

        with col_pmt:
            st.caption(
                "PMT Akhir"
            )

            st.write(
                f"**{_pmt_recovery_label(row)}**"
            )

        with col_outage:
            st.caption(
                "Durasi Padam"
            )

            st.write(
                f"**{_format_duration(row.get('customer_outage_duration_min'))}**"
            )

        with col_ens:
            st.caption(
                "ENS"
            )

            st.write(
                f"**{_format_number(row.get('ens_kwh'))} kWh**"
            )

        st.divider()

        col_a, col_b, col_c = (
            st.columns(3)
        )

        with col_a:
            st.caption(
                "Mulai Tersuplai"
            )

            st.write(
                f"**{_format_datetime_compact(row.get('supply_restored_date'), row.get('supply_restored_time'))}**"
            )

        with col_b:
            st.caption(
                "Operasi PMT"
            )

            st.write(
                f"**{_format_datetime_compact(row.get('recovery_date'), row.get('recovery_time'))}**"
            )

        with col_c:
            st.caption(
                "Durasi Kondisi PMT"
            )

            st.write(
                f"**{_format_duration(row.get('pmt_condition_duration_min'))}**"
            )

        st.divider()

        supply_status_code = str(
            row.get(
                "supply_status_code"
            )
            or ""
        ).strip().upper()

        if supply_status_code in {
            "MANUVER_PENUH",
            "MANUVER_SEBAGIAN",
        }:
            st.caption(
                "Beban Termanuver"
            )

            col_mr, col_ms, col_mt = (
                st.columns(3)
            )

            with col_mr:
                st.metric(
                    "Phasa R",
                    (
                        f"{_format_number(_phase_current_value(row, phase_field='maneuvered_current_r_a', legacy_field='maneuvered_current_a'))} A"
                    ),
                )

            with col_ms:
                st.metric(
                    "Phasa S",
                    (
                        f"{_format_number(_phase_current_value(row, phase_field='maneuvered_current_s_a', legacy_field='maneuvered_current_a'))} A"
                    ),
                )

            with col_mt:
                st.metric(
                    "Phasa T",
                    (
                        f"{_format_number(_phase_current_value(row, phase_field='maneuvered_current_t_a', legacy_field='maneuvered_current_a'))} A"
                    ),
                )

            maneuver_avg = (
                _three_phase_average_from_row(
                    row,
                    prefix="maneuvered_current",
                    legacy_field="maneuvered_current_a",
                )
            )

            if maneuver_avg is not None:
                st.caption(
                    "Rata-rata beban termanuver: "
                    f"**{maneuver_avg:,.2f} A**"
                )

        if (
            supply_status_code
            == "MANUVER_SEBAGIAN"
        ):
            st.caption(
                "Sisa Beban Belum Tersuplai"
            )

            col_rr, col_rs, col_rt = (
                st.columns(3)
            )

            with col_rr:
                st.metric(
                    "Sisa R",
                    (
                        f"{_format_number(_phase_current_value(row, phase_field='remaining_current_r_a', legacy_field='remaining_current_a'))} A"
                    ),
                )

            with col_rs:
                st.metric(
                    "Sisa S",
                    (
                        f"{_format_number(_phase_current_value(row, phase_field='remaining_current_s_a', legacy_field='remaining_current_a'))} A"
                    ),
                )

            with col_rt:
                st.metric(
                    "Sisa T",
                    (
                        f"{_format_number(_phase_current_value(row, phase_field='remaining_current_t_a', legacy_field='remaining_current_a'))} A"
                    ),
                )

            remaining_avg = (
                _three_phase_average_from_row(
                    row,
                    prefix="remaining_current",
                    legacy_field="remaining_current_a",
                )
            )

            if remaining_avg is not None:
                st.caption(
                    "Rata-rata sisa beban: "
                    f"**{remaining_avg:,.2f} A**"
                )

        st.caption(
            "Counter PMT"
        )

        st.write(
            f"**{_format_integer(row.get('pmt_counter_after'))}**"
        )

        if row.get(
            "recovery_status_code"
        ):
            st.divider()

            st.caption(
                "Arus Beban Setelah Operasi"
            )

            col_r, col_s, col_t = (
                st.columns(3)
            )

            with col_r:
                st.metric(
                    "Phasa R",
                    f"{_format_number(_phase_current_value(row, phase_field='load_current_after_r_a', legacy_field='load_current_after_a'))} A",
                )

            with col_s:
                st.metric(
                    "Phasa S",
                    f"{_format_number(_phase_current_value(row, phase_field='load_current_after_s_a', legacy_field='load_current_after_a'))} A",
                )

            with col_t:
                st.metric(
                    "Phasa T",
                    f"{_format_number(_phase_current_value(row, phase_field='load_current_after_t_a', legacy_field='load_current_after_a'))} A",
                )

            st.divider()

            col_v, col_normal = (
                st.columns(2)
            )

            with col_v:
                voltage_after = row.get(
                    "voltage_after_kv"
                )

                st.metric(
                    "Tegangan Setelah",
                    (
                        f"{_format_number(voltage_after)} kV"
                        if voltage_after
                        is not None
                        else "-"
                    ),
                )

            with col_normal:
                st.caption(
                    "Normalisasi Beban"
                )

                if bool(
                    row.get(
                        "final_supply_normalized"
                    )
                ):
                    final_text = (
                        _format_datetime_compact(
                            row.get(
                                "final_supply_normalization_date"
                            ),
                            row.get(
                                "final_supply_normalization_time"
                            ),
                        )
                    )

                    if final_text == "-":
                        final_text = (
                            "Sudah Normal"
                        )

                else:
                    final_text = (
                        "Belum"
                    )

                st.write(
                    f"**{final_text}**"
                )

            average_after = (
                _three_phase_average_from_row(
                    row,
                    prefix="load_current_after",
                    legacy_field="load_current_after_a",
                )
            )

            if average_after is not None:
                st.caption(
                    "Arus rata-rata setelah operasi: "
                    f"**{average_after:,.2f} A**"
                )


def _render_notes_detail(
    row: OperationRow,
) -> None:
    event_description = str(
        row.get(
            "event_description"
        )
        or ""
    ).strip()

    recovery_description = str(
        row.get(
            "recovery_description"
        )
        or ""
    ).strip()

    notes = str(
        row.get(
            "notes"
        )
        or ""
    ).strip()

    if not any(
        [
            event_description,
            recovery_description,
            notes,
        ]
    ):
        st.info(
            "Tidak ada kronologi atau catatan tambahan."
        )

        return

    with st.container(
        border=True
    ):
        if event_description:
            st.caption(
                "Kronologi / Keterangan Operasi"
            )

            st.write(
                event_description
            )

        if recovery_description:
            st.divider()

            st.caption(
                "Pemulihan / Normalisasi"
            )

            st.write(
                recovery_description
            )

        if notes:
            st.divider()

            st.caption(
                "Catatan"
            )

            st.write(
                notes
            )


def _render_operation_detail(
    row: OperationRow,
) -> None:
    st.markdown(
        "### Detail Operasi"
    )

    _render_identity_detail(
        row
    )

    (
        tab_parameter,
        tab_protection,
        tab_recovery,
        tab_evidence,
        tab_notes,
    ) = st.tabs(
        [
            "Ringkasan",
            "Proteksi",
            "Pemulihan",
            "Evidence",
            "Kronologi",
        ]
    )

    with tab_parameter:
        _render_parameter_detail(
            row
        )

    with tab_protection:
        _render_protection_detail(
            row
        )

    with tab_recovery:
        _render_recovery_detail(
            row
        )

    with tab_evidence:
        _render_evidence_detail(
            row
        )

    with tab_notes:
        _render_notes_detail(
            row
        )


# ==========================================================
# EXPORT EXCEL
# ==========================================================


def _build_export_dataframe(
    rows: list[OperationRow],
) -> pd.DataFrame:
    """
    Data export mengikuti struktur tabel Riwayat Operasi,
    termasuk arus sebelum/setelah, termanuver, dan sisa beban
    per phasa R/S/T; tanpa kolom internal dan tanpa icon action.
    """

    dataframe = _build_grid_dataframe(
        rows
    ).copy()

    removable_columns = [
        "_event_id",
        "_action",
        "_evidence_url",
        "_evidence_links",
        "_is_monthly_verified",
        "Detail",
        "Edit",
        "Delete",
    ]

    existing_removable = [
        column
        for column in removable_columns
        if column in dataframe.columns
    ]

    if existing_removable:
        dataframe = dataframe.drop(
            columns=existing_removable
        )

    if "Evidence" in dataframe.columns:
        dataframe["Evidence"] = [
            str(
                row.get(
                    "_first_evidence_url"
                )
                or ""
            ).strip()
            for row in rows
        ]

    return dataframe


def _build_excel_export(
    rows: list[OperationRow],
) -> bytes:
    """
    Membuat workbook Excel dari hasil filter aktif.
    """

    dataframe = _build_export_dataframe(
        rows
    )

    output = BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl",
    ) as writer:
        dataframe.to_excel(
            writer,
            index=False,
            sheet_name="Riwayat Operasi",
        )

        worksheet = writer.book[
            "Riwayat Operasi"
        ]

        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = (
            worksheet.dimensions
        )

        for column_index, column_cells in enumerate(
            worksheet.columns,
            start=1,
        ):
            max_length = 0

            for cell in column_cells:
                value = (
                    ""
                    if cell.value is None
                    else str(
                        cell.value
                    )
                )

                max_length = max(
                    max_length,
                    len(
                        value
                    ),
                )

            max_width = (
                22
                if column_index <= 4
                else 42
            )

            adjusted_width = min(
                max(
                    max_length + 2,
                    10,
                ),
                max_width,
            )

            column_letter = get_column_letter(
                column_index
            )

            worksheet.column_dimensions[
                column_letter
            ].width = adjusted_width

    output.seek(
        0
    )

    return output.getvalue()


def _build_export_filename(
    rows: list[OperationRow],
) -> str:
    event_dates = [
        parsed
        for parsed in (
            _parse_date(
                row.get(
                    "event_date"
                )
            )
            for row in rows
        )
        if parsed is not None
    ]

    if not event_dates:
        today = date.today()

        return (
            "riwayat_operasi_"
            f"{today:%Y_%m}.xlsx"
        )

    min_date = min(
        event_dates
    )

    max_date = max(
        event_dates
    )

    if (
        min_date.year == max_date.year
        and min_date.month == max_date.month
    ):
        return (
            "riwayat_operasi_"
            f"{min_date:%Y_%m}.xlsx"
        )

    return (
        "riwayat_operasi_"
        f"{min_date:%Y%m%d}_"
        "sampai_"
        f"{max_date:%Y%m%d}.xlsx"
    )


def _render_export_action(
    rows: list[OperationRow],
) -> None:
    try:
        excel_bytes = (
            _build_excel_export(
                rows
            )
        )

    except Exception as exc:
        st.warning(
            "File Excel belum dapat dibuat."
        )

        st.caption(
            str(
                exc
            )
        )

        return

    file_name = (
        _build_export_filename(
            rows
        )
    )

    st.download_button(
        "Export Excel",
        data=excel_bytes,
        file_name=file_name,
        mime=(
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        ),
        icon=":material/download:",
        use_container_width=True,
        key="history_export_excel",
    )


# ==========================================================
# PAGE
# ==========================================================


def render_page() -> None:
    render_sidebar()
    _apply_page_style()

    st.title(
        "Riwayat Operasi"
    )

    st.caption(
        "Riwayat Gangguan dan Manuver Penyulang 20 kV "
        "dengan parameter operasi lengkap dalam satu tabel."
    )

    flash_message = (
        st.session_state.pop(
            "history_flash_message",
            None,
        )
    )

    if flash_message:
        st.success(
            str(
                flash_message
            )
        )

    user_id = get_current_user_id()

    if user_id is None:
        st.error(
            "Session login tidak valid. "
            "Silakan login kembali."
        )

        return

    try:
        rows = (
            _load_operation_history(
                user_id
            )
        )

    except Exception as exc:
        st.error(
            "Riwayat Operasi tidak dapat dibaca."
        )

        st.exception(
            exc
        )

        return

    if not rows:
        st.info(
            "Belum terdapat riwayat operasi "
            "yang sudah selesai."
        )

        return

    filtered_rows = _render_filters(
        rows
    )

    _render_summary(
        filtered_rows
    )

    if not filtered_rows:
        st.info(
            "Tidak ada data yang sesuai dengan filter."
        )

        return

    selected_row: (
        OperationRow | None
    ) = None

    selected_action: (
        str | None
    ) = None

    with st.container(
        border=True
    ):
        col_title, col_export, col_count = (
            st.columns(
                [4.8, 1.2, 1]
            )
        )

        with col_title:
            st.markdown(
                "#### Riwayat Operasi"
            )

            st.caption(
                "Tabel utama menampilkan parameter operasi termasuk "
                "arus beban R/S/T sebelum dan setelah operasi. "
                "Gunakan horizontal scroll untuk melihat detail teknis. "
                "🔎 Detail   •   ✏️ Edit   •   🗑️ Delete   •   📎 Evidence"
            )

        with col_export:
            _render_export_action(
                filtered_rows
            )

        with col_count:
            st.metric(
                "Record",
                len(
                    filtered_rows
                ),
            )

        (
            selected_row,
            selected_action,
        ) = _render_history_grid(
            filtered_rows
        )

    if (
        selected_row is not None
        and selected_action
        == "EVIDENCE"
    ):
        _render_evidence_dialog(
            selected_row
        )

    if (
        selected_row is not None
        and selected_action
        == "EDIT"
    ):
        if bool(
            selected_row.get(
                "_is_monthly_verified"
            )
        ):
            st.warning(
                "Data tidak dapat diedit karena Laporan Bulanan "
                "pada periode ini sudah Terverifikasi."
            )

        elif can_edit():
            _open_history_for_edit(
                selected_row
            )

        else:
            st.warning(
                "Role Anda tidak memiliki akses Edit."
            )

    if (
        selected_row is not None
        and selected_action
        == "DELETE"
    ):
        if bool(
            selected_row.get(
                "_is_monthly_verified"
            )
        ):
            st.warning(
                "Data tidak dapat dihapus karena Laporan Bulanan "
                "pada periode ini sudah Terverifikasi."
            )

        elif can_soft_delete():
            st.session_state[
                "pending_delete_event_id"
            ] = str(
                selected_row.get(
                    "event_id"
                )
                or ""
            )

        else:
            st.warning(
                "Role Anda tidak memiliki akses Delete."
            )

    pending_delete_id = str(
        st.session_state.get(
            "pending_delete_event_id"
        )
        or ""
    )

    if pending_delete_id:
        delete_row = next(
            (
                row
                for row in filtered_rows
                if str(
                    row.get(
                        "event_id"
                    )
                    or ""
                )
                == pending_delete_id
            ),
            None,
        )

        if delete_row is not None:
            if bool(
                delete_row.get(
                    "_is_monthly_verified"
                )
            ):
                st.session_state.pop(
                    "pending_delete_event_id",
                    None,
                )

                st.warning(
                    "Data tidak dapat dihapus karena Laporan Bulanan "
                    "pada periode ini sudah Terverifikasi."
                )

            else:
                _render_delete_dialog(
                    delete_row
                )

    if (
        selected_row is not None
        and selected_action
        == "DETAIL"
    ):
        st.divider()

        _render_operation_detail(
            selected_row
        )


render_page()