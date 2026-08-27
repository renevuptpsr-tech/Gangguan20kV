from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
import streamlit as st

from components.sidebar import render_sidebar
from services.access_service import can_view
from services.monthly_report_monitoring_service import (
    build_monitoring_summary,
    load_monthly_monitoring_snapshot,
)


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

STATUS_LABELS: dict[str, str] = {
    "NOT_CREATED": "Belum Dibuat",
    "DRAFT": "Draft",
    "SUBMITTED": "Menunggu Verifikasi",
    "REJECTED": "Perlu Perbaikan",
    "APPROVED": "Terverifikasi",
}


def _safe_string(
    value: Any,
    default: str = "-",
) -> str:
    if value is None:
        return default

    text = str(value).strip()
    return text or default


def _format_datetime(
    value: Any,
) -> str:
    text = _safe_string(
        value,
        "",
    )

    if not text:
        return "-"

    try:
        parsed = datetime.fromisoformat(
            text.replace(
                "Z",
                "+00:00",
            )
        )

        return parsed.strftime(
            "%d-%m-%Y %H:%M"
        )

    except ValueError:
        return text


def _period_label(
    year: int,
    month: int,
) -> str:
    return (
        f"{MONTH_NAMES.get(month, str(month))} "
        f"{year}"
    )


def _apply_style() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1550px;
            padding-top: 1.15rem;
            padding-bottom: 3rem;
        }

        div[data-testid="stMetric"] {
            border: 1px solid rgba(128,128,128,.14);
            border-radius: 14px;
            padding: .8rem .9rem;
            background: rgba(128,128,128,.025);
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 15px;
        }

        .monitor-progress {
            height: 8px;
            border-radius: 999px;
            background: rgba(128,128,128,.15);
            overflow: hidden;
            margin-top: .35rem;
        }

        .monitor-progress > div {
            height: 100%;
            border-radius: 999px;
            background: #00a2d9;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_filters(
    rows: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    str,
    str,
]:
    ultg_options = sorted(
        {
            _safe_string(
                row.get(
                    "ultg_name"
                )
            )
            for row in rows
            if _safe_string(
                row.get(
                    "ultg_name"
                ),
                "",
            )
        }
    )

    status_options = [
        "Semua Status",
        "Belum Dibuat",
        "Draft",
        "Menunggu Verifikasi",
        "Perlu Perbaikan",
        "Terverifikasi",
    ]

    col_ultg, col_status, col_search = st.columns(
        [1.5, 1.6, 2.4]
    )

    with col_ultg:
        selected_ultg = st.selectbox(
            "ULTG",
            options=[
                "Semua ULTG",
                *ultg_options,
            ],
            key="monitor_monthly_ultg",
        )

    with col_status:
        selected_status_label = st.selectbox(
            "Status",
            options=status_options,
            key="monitor_monthly_status",
        )

    with col_search:
        search_text = st.text_input(
            "Cari Gardu Induk",
            placeholder="Nama Gardu Induk...",
            key="monitor_monthly_search",
        )

    label_to_code = {
        label: code
        for code, label in STATUS_LABELS.items()
    }

    selected_status = label_to_code.get(
        selected_status_label
    )

    filtered: list[
        dict[str, Any]
    ] = []

    for row in rows:
        if (
            selected_ultg
            != "Semua ULTG"
            and _safe_string(
                row.get(
                    "ultg_name"
                )
            )
            != selected_ultg
        ):
            continue

        if (
            selected_status
            and _safe_string(
                row.get(
                    "status"
                ),
                "NOT_CREATED",
            ).upper()
            != selected_status
        ):
            continue

        if search_text.strip():
            haystack = (
                f"{_safe_string(row.get('gi_name'), '')} "
                f"{_safe_string(row.get('gi_flc'), '')}"
            ).lower()

            if (
                search_text.strip().lower()
                not in haystack
            ):
                continue

        filtered.append(
            row
        )

    return (
        filtered,
        selected_ultg,
        selected_status_label,
    )


def _render_overview(
    rows: list[dict[str, Any]],
) -> None:
    summary = build_monitoring_summary(
        rows
    )

    (
        col_total,
        col_pending,
        col_approved,
        col_rejected,
        col_missing,
    ) = st.columns(
        5
    )

    with col_total:
        st.metric(
            "Total GI",
            int(
                summary[
                    "total_gi"
                ]
            ),
        )

    with col_pending:
        st.metric(
            "Menunggu Verifikasi",
            int(
                summary[
                    "submitted"
                ]
            ),
        )

    with col_approved:
        st.metric(
            "Terverifikasi",
            int(
                summary[
                    "approved"
                ]
            ),
        )

    with col_rejected:
        st.metric(
            "Perlu Perbaikan",
            int(
                summary[
                    "rejected"
                ]
            ),
        )

    with col_missing:
        st.metric(
            "Belum Dibuat",
            int(
                summary[
                    "not_created"
                ]
            ),
        )

    completion = float(
        summary[
            "completion_pct"
        ]
    )

    st.markdown(
        (
            f"**Progress Laporan Bulanan — "
            f"{completion:.1f}% selesai**"
        )
    )

    st.markdown(
        (
            '<div class="monitor-progress">'
            f'<div style="width:{max(0.0, min(completion, 100.0))}%"></div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )

    st.caption(
        (
            f"{int(summary['approved'])} dari "
            f"{int(summary['total_gi'])} Gardu Induk "
            "sudah terverifikasi."
        )
    )


def _render_monitoring_table(
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        st.info(
            "Tidak ada data sesuai filter."
        )
        return

    table_rows: list[
        dict[str, Any]
    ] = []

    for row in rows:
        status_code = _safe_string(
            row.get(
                "status"
            ),
            "NOT_CREATED",
        ).upper()

        file_status = _safe_string(
            row.get(
                "file_status"
            ),
            "NONE",
        ).upper()

        table_rows.append(
            {
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

                "Status":
                    STATUS_LABELS.get(
                        status_code,
                        status_code,
                    ),

                "Diajukan":
                    _format_datetime(
                        row.get(
                            "submitted_at"
                        )
                    ),

                "Diverifikasi":
                    _format_datetime(
                        row.get(
                            "verified_at"
                        )
                    ),

                "Verifikator":
                    _safe_string(
                        row.get(
                            "signer_name"
                        )
                    ),

                "Dokumen":
                    (
                        "PDF + Excel"
                        if file_status
                        == "COMPLETE"
                        else (
                            "Sebagian"
                            if file_status
                            == "PARTIAL"
                            else "-"
                        )
                    ),
            }
        )

    dataframe = pd.DataFrame(
        table_rows
    )

    st.dataframe(
        dataframe,
        use_container_width=True,
        hide_index=True,
        height=min(
            620,
            74
            + len(
                dataframe
            )
            * 35,
        ),
    )


def _render_download_cards(
    rows: list[dict[str, Any]],
) -> None:
    available_rows = [
        row
        for row in rows
        if (
            _safe_string(
                row.get(
                    "status"
                ),
                "",
            ).upper()
            == "APPROVED"
            and (
                _safe_string(
                    row.get(
                        "pdf_url"
                    ),
                    "",
                )
                or _safe_string(
                    row.get(
                        "xlsx_url"
                    ),
                    "",
                )
            )
        )
    ]

    if not available_rows:
        return

    with st.expander(
        "Dokumen Resmi",
        expanded=False,
    ):
        for row in available_rows:
            with st.container(
                border=True
            ):
                (
                    col_info,
                    col_pdf,
                    col_excel,
                ) = st.columns(
                    [4, 1.15, 1.15],
                    vertical_alignment="center",
                )

                with col_info:
                    st.markdown(
                        f"**{_safe_string(row.get('gi_name'))}**"
                    )

                    st.caption(
                        (
                            f"{_safe_string(row.get('ultg_name'))} · "
                            f"Diverifikasi oleh "
                            f"{_safe_string(row.get('signer_name'))}"
                        )
                    )

                pdf_url = _safe_string(
                    row.get(
                        "pdf_url"
                    ),
                    "",
                )

                xlsx_url = _safe_string(
                    row.get(
                        "xlsx_url"
                    ),
                    "",
                )

                with col_pdf:
                    if pdf_url:
                        st.link_button(
                            "PDF",
                            pdf_url,
                            icon=":material/picture_as_pdf:",
                            use_container_width=True,
                        )

                with col_excel:
                    if xlsx_url:
                        st.link_button(
                            "Excel",
                            xlsx_url,
                            icon=":material/table_view:",
                            use_container_width=True,
                        )


def render_page() -> None:
    render_sidebar()
    _apply_style()

    st.title(
        "Monitoring Laporan Bulanan"
    )

    st.caption(
        "Monitoring status penyelesaian laporan bulanan "
        "seluruh Gardu Induk dalam satu tampilan."
    )

    if not can_view():
        st.error(
            "Anda tidak memiliki akses Monitoring."
        )
        return

    today = date.today()

    with st.container(
        border=True
    ):
        col_month, col_year, col_refresh = st.columns(
            [1.2, 1.0, 3.8],
            vertical_alignment="bottom",
        )

        with col_month:
            report_month = st.selectbox(
                "Bulan",
                options=list(
                    MONTH_NAMES.keys()
                ),
                index=today.month - 1,
                format_func=lambda month:
                    MONTH_NAMES[
                        int(month)
                    ],
                key="monitor_monthly_month",
            )

        with col_year:
            report_year = st.selectbox(
                "Tahun",
                options=list(
                    range(
                        today.year,
                        max(
                            2017,
                            today.year - 5,
                        )
                        - 1,
                        -1,
                    )
                ),
                key="monitor_monthly_year",
            )

        with col_refresh:
            if st.button(
                "Refresh Data",
                icon=":material/refresh:",
                use_container_width=False,
            ):
                load_monthly_monitoring_snapshot.clear()
                st.rerun()

    try:
        with st.spinner(
            "Memuat monitoring laporan..."
        ):
            rows = load_monthly_monitoring_snapshot(
                int(
                    report_year
                ),
                int(
                    report_month
                ),
            )

    except Exception as exc:
        st.error(
            "Data monitoring tidak dapat dimuat."
        )
        st.exception(
            exc
        )
        return

    st.markdown(
        f"## {_period_label(int(report_year), int(report_month))}"
    )

    _render_overview(
        rows
    )

    st.write(
        ""
    )

    filtered_rows, _, _ = _render_filters(
        rows
    )

    st.markdown(
        "### Status Gardu Induk"
    )

    _render_monitoring_table(
        filtered_rows
    )

    _render_download_cards(
        filtered_rows
    )


render_page()