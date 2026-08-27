from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
import streamlit as st

from components.sidebar import render_sidebar
from services.access_service import (
    can_input,
    can_manage_access,
    can_verify,
    can_view,
    get_role_labels,
)
from services.report_export_service import (
    generate_and_archive_official_report,
)
from services.report_service import (
    build_monthly_report_bundle,
    clear_report_cache,
    get_accessible_feeders,
    load_monthly_report_list,
    review_monthly_report,
    return_monthly_report_to_draft,
    submit_monthly_report,
)


# ==========================================================
# TYPES
# ==========================================================

ReportRow = dict[str, Any]


# ==========================================================
# CONSTANTS
# ==========================================================

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
    "DRAFT": "Draft",
    "SUBMITTED": "Menunggu Verifikasi",
    "APPROVED": "Terverifikasi",
    "REJECTED": "Perlu Perbaikan",
}

STATUS_TONES: dict[str, str] = {
    "DRAFT": "neutral",
    "SUBMITTED": "warning",
    "APPROVED": "success",
    "REJECTED": "danger",
}


# ==========================================================
# STYLE
# ==========================================================


def _apply_page_style() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1480px;
            padding-top: 1.15rem;
            padding-bottom: 2.5rem;
        }

        h1 {
            letter-spacing: -0.02em;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 16px;
            border-color: rgba(128,128,128,.20);
        }

        .report-topbar {
            border: 1px solid rgba(128,128,128,.18);
            border-radius: 16px;
            padding: 1rem 1.1rem;
            margin-bottom: .75rem;
            background: rgba(128,128,128,.035);
        }

        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: .4rem;
            padding: .34rem .75rem;
            border-radius: 999px;
            font-size: .83rem;
            font-weight: 700;
            border: 1px solid transparent;
            white-space: nowrap;
        }

        .status-neutral {
            background: rgba(128,128,128,.10);
            border-color: rgba(128,128,128,.18);
        }

        .status-warning {
            background: rgba(245,158,11,.12);
            border-color: rgba(245,158,11,.25);
        }

        .status-success {
            background: rgba(16,185,129,.12);
            border-color: rgba(16,185,129,.25);
        }

        .status-danger {
            background: rgba(239,68,68,.10);
            border-color: rgba(239,68,68,.22);
        }

        .workflow-step {
            font-size: .84rem;
            opacity: .76;
        }

        .official-card {
            border: 1px solid rgba(16,185,129,.25);
            background: rgba(16,185,129,.055);
            border-radius: 14px;
            padding: .9rem 1rem;
        }

        div[data-testid="stMetric"] {
            border: 1px solid rgba(128,128,128,.14);
            border-radius: 12px;
            padding: .72rem .8rem;
            background: rgba(128,128,128,.025);
        }

        div[data-testid="stMetricLabel"] {
            font-size: .82rem;
        }

        .archive-row {
            padding: .15rem 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ==========================================================
# GENERIC HELPERS
# ==========================================================


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
    if value is None:
        return "-"

    text = str(value).strip()

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


def _format_number(
    value: Any,
    decimals: int = 2,
) -> str:
    try:
        return f"{float(value):,.{decimals}f}"

    except (TypeError, ValueError):
        return "0"


def _period_label(
    year: int,
    month: int,
) -> str:
    return (
        f"{MONTH_NAMES.get(month, str(month))} "
        f"{year}"
    )


def _status_code(
    report: dict[str, Any],
) -> str:
    return _safe_string(
        report.get(
            "status"
        ),
        "DRAFT",
    ).upper()


def _can_return_approved_to_draft() -> bool:
    """
    User yang dapat mengembalikan laporan APPROVED ke DRAFT:
    - EVALUATOR
    - ADMIN
    - SUPER_ADMIN

    Scope final tetap divalidasi oleh RPC Supabase.
    """

    roles = {
        str(
            role
        ).strip().upper()
        for role in get_role_labels()
        if str(
            role
        ).strip()
    }

    return bool(
        roles.intersection(
            {
                "EVALUATOR",
                "ADMIN",
                "SUPER_ADMIN",
            }
        )
    )


def _status_html(
    status: str,
) -> str:
    tone = STATUS_TONES.get(
        status,
        "neutral",
    )

    label = STATUS_LABELS.get(
        status,
        status,
    )

    return (
        f'<span class="status-pill status-{tone}">'
        f'{label}'
        '</span>'
    )


def _history_action_label(
    action: Any,
) -> str:
    code = _safe_string(
        action,
        "",
    ).upper()

    labels = {
        "SUBMIT":
            "Diajukan",

        "RESUBMIT":
            "Diajukan Kembali",

        "APPROVE":
            "Verifikasi & e-Sign",

        "REJECT":
            "Dikembalikan untuk Perbaikan",

        "RETURN_DRAFT":
            "Dikembalikan ke Draft",
    }

    return labels.get(
        code,
        code or "-",
    )


# ==========================================================
# SELECTOR - GI ONLY
# ==========================================================


def _render_report_selector(
    feeders: list[ReportRow],
) -> tuple[int, int, str, str] | None:
    today = date.today()

    gi_rows: dict[str, dict[str, str]] = {}

    for row in feeders:
        gi_flc = _safe_string(
            row.get(
                "gi_flc"
            ),
            "",
        )

        if not gi_flc:
            continue

        gi_rows.setdefault(
            gi_flc,
            {
                "gi_name":
                    _safe_string(
                        row.get(
                            "gi_name"
                        ),
                        gi_flc,
                    ),
                "ultg_name":
                    _safe_string(
                        row.get(
                            "ultg_name"
                        ),
                        "",
                    ),
            },
        )

    gi_options = sorted(
        gi_rows,
        key=lambda code: (
            gi_rows[
                code
            ][
                "ultg_name"
            ].upper(),
            gi_rows[
                code
            ][
                "gi_name"
            ].upper(),
        ),
    )

    if not gi_options:
        st.info(
            "Belum ada Gardu Induk yang dapat diakses."
        )
        return None

    current_gi = _safe_string(
        st.session_state.get(
            "monthly_report_gi_only",
            gi_options[0],
        ),
        gi_options[0],
    )

    if current_gi not in gi_options:
        st.session_state[
            "monthly_report_gi_only"
        ] = gi_options[0]

    def _format_gi(
        code: Any,
    ) -> str:
        code_text = str(
            code
        )

        info = gi_rows.get(
            code_text,
            {},
        )

        gi_name = _safe_string(
            info.get(
                "gi_name"
            ),
            code_text,
        )

        ultg_name = _safe_string(
            info.get(
                "ultg_name"
            ),
            "",
        )

        return (
            f"{gi_name} — {ultg_name}"
            if ultg_name
            else gi_name
        )

    with st.container(
        border=True
    ):
        col_period, col_year, col_gi = st.columns(
            [1, 1, 2.8]
        )

        with col_period:
            selected_month = st.selectbox(
                "Bulan",
                options=list(
                    MONTH_NAMES.keys()
                ),
                index=today.month - 1,
                format_func=lambda month:
                    MONTH_NAMES[
                        int(month)
                    ],
                key="monthly_report_month",
            )

        with col_year:
            selected_year = st.selectbox(
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
                index=0,
                key="monthly_report_year",
            )

        with col_gi:
            selected_gi = st.selectbox(
                "Gardu Induk",
                options=gi_options,
                format_func=_format_gi,
                key="monthly_report_gi_only",
            )

    gi_name = gi_rows[
        selected_gi
    ][
        "gi_name"
    ]

    return (
        int(
            selected_year
        ),
        int(
            selected_month
        ),
        selected_gi,
        gi_name,
    )


# ==========================================================
# SUMMARY
# ==========================================================


def _render_summary(
    bundle: dict[str, Any],
) -> None:
    summary = bundle[
        "summary"
    ]

    (
        col_trip,
        col_lepas,
        col_duration,
        col_ens,
        col_feeder,
    ) = st.columns(
        5
    )

    with col_trip:
        st.metric(
            "Trip",
            int(
                summary.get(
                    "total_trip",
                    0,
                )
            ),
        )

    with col_lepas:
        st.metric(
            "Lepas",
            int(
                summary.get(
                    "total_lepas",
                    0,
                )
            ),
        )

    with col_duration:
        st.metric(
            "Menit Padam",
            _format_number(
                summary.get(
                    "total_menit_padam"
                ),
                0,
            ),
        )

    with col_ens:
        st.metric(
            "ENS",
            (
                f"{_format_number(summary.get('total_ens_kwh'))} kWh"
            ),
        )

    with col_feeder:
        st.metric(
            "Penyulang Terdampak",
            int(
                summary.get(
                    "penyulang_terdampak",
                    0,
                )
            ),
        )


# ==========================================================
# DATAFRAME VIEWS
# ==========================================================


def _display_dataframe(
    dataframe: pd.DataFrame,
    *,
    height: int = 390,
) -> None:
    if dataframe.empty:
        st.info(
            "Tidak ada kejadian pada bagian ini."
        )
        return

    st.dataframe(
        dataframe,
        use_container_width=True,
        hide_index=True,
        height=height,
    )


def _trip_recap_view(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    columns = {
        "feeder": "Feeder",
        "feeder_name": "Nama",
        "ocr_inst": "OCR INST",
        "ocr_td": "OCR TD",
        "gfr_inst": "GFR INST",
        "gfr_td": "GFR TD",
        "ufr_uvls_relay": "UFR/UVLS",
        "ols_relay": "OLS",
        "rtn_relay": "RTN",
        "trip_ocr_gfr": "Trip OCR&GFR",
        "trip_ufr_uvls": "Trip UFR/UVLS",
        "trip_ols": "Trip OLS",
        "trip_rtn": "Trip RTN",
        "total_trip_event": "Total Trip",
        "menit_ocr_gfr": "Menit OCR&GFR",
        "menit_ufr_uvls": "Menit UFR/UVLS",
        "menit_ols": "Menit OLS",
        "menit_rtn": "Menit RTN",
        "total_menit": "Total Menit",
        "total_kwh": "Total kWh",
    }

    existing = [
        column
        for column in columns
        if column in dataframe.columns
    ]

    return dataframe[
        existing
    ].rename(
        columns=columns
    )


def _lepas_recap_view(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    columns = {
        "feeder": "Feeder",
        "feeder_name": "Nama",
        "lepas_har": "HAR",
        "lepas_defisit": "Defisit",
        "lepas_ulp": "ULP",
        "lepas_emergency_upt": "Emergency UPT",
        "lepas_emergency_ulp": "Emergency ULP",
        "lepas_blackout": "Blackout",
        "lepas_lainnya": "Lainnya",
        "jumlah_lepas": "Jumlah Lepas",
        "total_menit": "Total Menit",
        "total_kwh": "Total kWh",
    }

    existing = [
        column
        for column in columns
        if column in dataframe.columns
    ]

    return dataframe[
        existing
    ].rename(
        columns=columns
    )


def _detail_trip_view(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """
    Preview Detail Trip.

    Arus beban sebelum dan setelah pemulihan ditampilkan
    per phasa R/S/T. Arus gangguan tetap dipisahkan karena
    memiliki makna yang berbeda.
    """

    columns = {
        "no": "No",
        "nama_penyulang": "Penyulang",
        "kondisi": "Kondisi",
        "tanggal": "Tanggal",
        "pkl": "Pukul",

        # Arus beban sebelum gangguan
        "amp_r": "Arus Sebelum R (A)",
        "amp_s": "Arus Sebelum S (A)",
        "amp_t": "Arus Sebelum T (A)",

        "kv": "kV",

        # Arus gangguan
        "r": "Arus Ggn R (A)",
        "s": "Arus Ggn S (A)",
        "t": "Arus Ggn T (A)",
        "n": "Arus Ggn N (A)",

        "pemulihan_kondisi": "Pemulihan",
        "pemulihan_tanggal": "Tanggal Pulih",
        "pemulihan_pkl": "Pukul Pulih",

        # Arus beban setelah pemulihan
        "amp_after_r": "Arus Setelah R (A)",
        "amp_after_s": "Arus Setelah S (A)",
        "amp_after_t": "Arus Setelah T (A)",

        # Pemulihan beban / manuver
        "supply_status_name": "Status Suplai",
        "supply_restored_date": "Tanggal Mulai Tersuplai",
        "supply_restored_time": "Pukul Mulai Tersuplai",

        "maneuvered_r": "Termanuver R (A)",
        "maneuvered_s": "Termanuver S (A)",
        "maneuvered_t": "Termanuver T (A)",

        "remaining_r": "Sisa R (A)",
        "remaining_s": "Sisa S (A)",
        "remaining_t": "Sisa T (A)",

        "final_supply_normalized": "Beban Normal",
        "final_supply_normalization_date": "Tanggal Normalisasi",
        "final_supply_normalization_time": "Pukul Normalisasi",

        "menit": "Menit",
        "jlh_kwh": "kWh",
        "annunciator": "Annunciator",
        "indikasi_name": "Indikasi",
        "phasa": "Phasa",
        "penyebab_kejadian": "Penyebab",
        "keterangan": "Keterangan",
    }

    # Reindex menjaga struktur preview meskipun dataframe kosong.
    return (
        dataframe
        .reindex(
            columns=list(
                columns.keys()
            )
        )
        .rename(
            columns=columns
        )
    )


def _detail_lepas_view(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """
    Preview Detail Lepas / Manuver dengan arus beban
    sebelum dan setelah operasi per phasa R/S/T.
    """

    columns = {
        "no": "No",
        "nama_penyulang": "Penyulang",
        "kondisi": "Kondisi",
        "tanggal": "Tanggal",
        "pkl": "Pukul",

        # Arus beban sebelum manuver / lepas
        "amp_r": "Arus Sebelum R (A)",
        "amp_s": "Arus Sebelum S (A)",
        "amp_t": "Arus Sebelum T (A)",

        "kv": "kV",

        "pemulihan_kondisi": "Pemulihan",
        "pemulihan_tanggal": "Tanggal Pulih",
        "pemulihan_pkl": "Pukul Pulih",

        # Arus beban setelah normalisasi
        "amp_after_r": "Arus Setelah R (A)",
        "amp_after_s": "Arus Setelah S (A)",
        "amp_after_t": "Arus Setelah T (A)",

        # Pemulihan beban / manuver
        "supply_status_name": "Status Suplai",
        "supply_restored_date": "Tanggal Mulai Tersuplai",
        "supply_restored_time": "Pukul Mulai Tersuplai",

        "maneuvered_r": "Termanuver R (A)",
        "maneuvered_s": "Termanuver S (A)",
        "maneuvered_t": "Termanuver T (A)",

        "remaining_r": "Sisa R (A)",
        "remaining_s": "Sisa S (A)",
        "remaining_t": "Sisa T (A)",

        "final_supply_normalized": "Beban Normal",
        "final_supply_normalization_date": "Tanggal Normalisasi",
        "final_supply_normalization_time": "Pukul Normalisasi",

        "menit": "Menit",
        "jlh_kwh": "kWh",
        "penyebab_kejadian": "Penyebab",
        "kategori_lepas": "Kategori",
        "keterangan": "Keterangan",
    }

    # Reindex menjaga struktur preview meskipun dataframe kosong.
    return (
        dataframe
        .reindex(
            columns=list(
                columns.keys()
            )
        )
        .rename(
            columns=columns
        )
    )


# ==========================================================
# VALIDATION
# ==========================================================


def _has_ongoing_trip(
    bundle: dict[str, Any],
) -> bool:
    detail_trip = bundle[
        "detail_trip"
    ]

    if (
        detail_trip.empty
        or "pemulihan_kondisi"
        not in detail_trip.columns
    ):
        return False

    return bool(
        detail_trip[
            "pemulihan_kondisi"
        ]
        .fillna(
            ""
        )
        .astype(
            str
        )
        .str.strip()
        .eq(
            ""
        )
        .any()
    )


# ==========================================================
# REPORT STATUS / ACTION BAR
# ==========================================================


def _render_report_header(
    bundle: dict[str, Any],
    *,
    report_year: int,
    report_month: int,
    gi_name: str,
) -> None:
    report = bundle[
        "monthly_report"
    ]

    status = _status_code(
        report
    )

    col_title, col_status = st.columns(
        [5, 1.25],
        vertical_alignment="center",
    )

    with col_title:
        st.markdown(
            f"## {_period_label(report_year, report_month)} · {gi_name}"
        )

        if status == "SUBMITTED":
            st.caption(
                "Laporan siap direview dan menunggu verifikasi."
            )

        elif status == "APPROVED":
            signer = _safe_string(
                report.get(
                    "signer_name"
                )
            )

            verified_at = _format_datetime(
                report.get(
                    "verified_at"
                )
            )

            st.caption(
                f"Terverifikasi oleh {signer} · {verified_at}"
            )

        elif status == "REJECTED":
            st.caption(
                "Laporan perlu diperbaiki sebelum diajukan kembali."
            )

        else:
            st.caption(
                "Review data lalu ajukan untuk verifikasi."
            )

    with col_status:
        st.markdown(
            _status_html(
                status
            ),
            unsafe_allow_html=True,
        )

    if status == "REJECTED":
        notes = _safe_string(
            report.get(
                "verification_notes"
            ),
            "",
        )

        if notes:
            st.warning(
                f"Catatan perbaikan: {notes}"
            )


# ==========================================================
# DIALOG - SUBMIT
# ==========================================================


@st.dialog(
    "Ajukan Laporan",
    width="small",
)
def _render_submit_dialog(
    *,
    monthly_report_id: str,
    period_label: str,
    gi_name: str,
) -> None:
    st.write(
        f"**{period_label} · {gi_name}**"
    )

    st.caption(
        "Setelah diajukan, laporan masuk ke antrean verifikasi."
    )

    col_cancel, col_submit = st.columns(
        2
    )

    with col_cancel:
        cancel = st.button(
            "Batal",
            use_container_width=True,
            key="monthly_submit_cancel",
        )

    with col_submit:
        confirm = st.button(
            "Ajukan",
            type="primary",
            icon=":material/send:",
            use_container_width=True,
            key="monthly_submit_confirm",
        )

    if cancel:
        st.rerun()

    if not confirm:
        return

    try:
        with st.spinner(
            "Mengajukan laporan..."
        ):
            submit_monthly_report(
                monthly_report_id
            )

        clear_report_cache()

        st.session_state[
            "monthly_report_flash_success"
        ] = (
            "Laporan berhasil diajukan untuk verifikasi."
        )

        st.rerun()

    except Exception as exc:
        st.error(
            "Laporan gagal diajukan."
        )
        st.exception(
            exc
        )


# ==========================================================
# DIALOG - VERIFY + AUTO GENERATE
# ==========================================================


@st.dialog(
    "Verifikasi & e-Sign",
    width="small",
)
def _render_verify_dialog(
    *,
    monthly_report_id: str,
    report_year: int,
    report_month: int,
    gi_flc: str,
    gi_name: str,
) -> None:
    period_label = _period_label(
        report_year,
        report_month,
    )

    st.write(
        f"**{period_label} · {gi_name}**"
    )

    st.caption(
        "Setelah diverifikasi, PDF dan Excel resmi akan "
        "langsung dibuat dan diarsipkan ke Google Drive."
    )

    notes = st.text_area(
        "Catatan verifikasi",
        placeholder="Opsional",
        height=84,
        key="monthly_verify_notes",
    )

    acknowledge = st.checkbox(
        "Saya telah memeriksa isi laporan dan menyetujui data ini.",
        key="monthly_verify_acknowledge",
    )

    col_cancel, col_verify = st.columns(
        2
    )

    with col_cancel:
        cancel = st.button(
            "Batal",
            use_container_width=True,
            key="monthly_verify_cancel",
        )

    with col_verify:
        verify = st.button(
            "Verifikasi & e-Sign",
            type="primary",
            icon=":material/verified:",
            use_container_width=True,
            disabled=(
                not acknowledge
            ),
            key="monthly_verify_confirm",
        )

    if cancel:
        st.rerun()

    if not verify:
        return

    approval_done = False

    try:
        with st.status(
            "Memproses laporan resmi...",
            expanded=True,
        ) as process:
            st.write(
                "1. Menyimpan verifikasi & e-Sign"
            )

            review_monthly_report(
                monthly_report_id=(
                    monthly_report_id
                ),
                action="APPROVE",
                notes=(
                    str(
                        notes
                        or ""
                    ).strip()
                    or None
                ),
            )

            approval_done = True

            clear_report_cache()

            st.write(
                "2. Membuat PDF dan Excel resmi"
            )

            approved_bundle = (
                build_monthly_report_bundle(
                    report_year=(
                        report_year
                    ),
                    report_month=(
                        report_month
                    ),
                    scope_functloc_id=(
                        gi_flc
                    ),
                )
            )

            st.write(
                "3. Mengarsipkan ke Google Drive"
            )

            generate_and_archive_official_report(
                bundle=(
                    approved_bundle
                ),
                report_year=(
                    report_year
                ),
                report_month=(
                    report_month
                ),
                gi_flc=(
                    gi_flc
                ),
                gi_name=(
                    gi_name
                ),
            )

            clear_report_cache()

            process.update(
                label=(
                    "Laporan terverifikasi dan dokumen resmi "
                    "berhasil diarsipkan."
                ),
                state="complete",
                expanded=False,
            )

        st.session_state[
            "monthly_report_flash_success"
        ] = (
            "Verifikasi selesai. PDF dan Excel resmi sudah "
            "tersedia di Google Drive."
        )

        st.rerun()

    except Exception as exc:
        clear_report_cache()

        if approval_done:
            st.session_state[
                "monthly_report_flash_warning"
            ] = (
                "e-Sign berhasil disimpan, tetapi pembuatan/arsip "
                "dokumen belum selesai. Gunakan tombol Coba Generate "
                "Ulang pada Dokumen Resmi."
            )

            st.rerun()

        st.error(
            "Verifikasi laporan gagal."
        )

        st.exception(
            exc
        )


# ==========================================================
# DIALOG - REJECT
# ==========================================================


@st.dialog(
    "Kembalikan Laporan",
    width="small",
)
def _render_reject_dialog(
    *,
    monthly_report_id: str,
    report_year: int,
    report_month: int,
    gi_name: str,
) -> None:
    st.write(
        f"**{_period_label(report_year, report_month)} · {gi_name}**"
    )

    notes = st.text_area(
        "Catatan perbaikan *",
        placeholder="Jelaskan data yang perlu diperbaiki.",
        height=100,
        key="monthly_reject_notes",
    )

    valid = bool(
        str(
            notes
            or ""
        ).strip()
    )

    col_cancel, col_reject = st.columns(
        2
    )

    with col_cancel:
        cancel = st.button(
            "Batal",
            use_container_width=True,
            key="monthly_reject_cancel",
        )

    with col_reject:
        reject = st.button(
            "Kembalikan",
            type="primary",
            icon=":material/reply:",
            use_container_width=True,
            disabled=(
                not valid
            ),
            key="monthly_reject_confirm",
        )

    if cancel:
        st.rerun()

    if not reject:
        return

    try:
        with st.spinner(
            "Mengembalikan laporan..."
        ):
            review_monthly_report(
                monthly_report_id=(
                    monthly_report_id
                ),
                action="REJECT",
                notes=str(
                    notes
                ).strip(),
            )

        clear_report_cache()

        st.session_state[
            "monthly_report_flash_success"
        ] = (
            "Laporan dikembalikan untuk perbaikan."
        )

        st.rerun()

    except Exception as exc:
        st.error(
            "Laporan gagal dikembalikan."
        )
        st.exception(
            exc
        )


# ==========================================================
# DIALOG - ADMIN RETURN APPROVED TO DRAFT
# ==========================================================


@st.dialog(
    "Kembalikan Laporan ke Draft",
    width="small",
)
def _render_return_to_draft_dialog(
    *,
    monthly_report_id: str,
    report_year: int,
    report_month: int,
    gi_name: str,
) -> None:
    st.write(
        f"**{_period_label(report_year, report_month)} · {gi_name}**"
    )

    st.warning(
        "Laporan yang sudah terverifikasi akan dikembalikan "
        "menjadi Draft. e-Sign aktif akan dibatalkan dan dokumen "
        "resmi current tidak lagi ditampilkan sebagai laporan aktif. "
        "Aksi ini hanya tersedia untuk Evaluator, Admin, atau Super Admin."
    )

    st.caption(
        "Riwayat verifikasi sebelumnya tetap tersimpan permanen "
        "sebagai audit trail dan tidak dapat diedit atau dihapus."
    )

    notes = st.text_area(
        "Alasan pengembalian ke Draft *",
        placeholder=(
            "Contoh: terdapat koreksi data kejadian / laporan "
            "perlu diperbarui."
        ),
        height=105,
        key="monthly_return_draft_notes",
    )

    notes_valid = bool(
        str(
            notes
            or ""
        ).strip()
    )

    confirm = st.checkbox(
        "Saya memahami bahwa laporan harus diajukan dan "
        "diverifikasi ulang setelah diperbaiki.",
        key="monthly_return_draft_confirm",
    )

    col_cancel, col_return = st.columns(
        2
    )

    with col_cancel:
        cancel = st.button(
            "Batal",
            use_container_width=True,
            key="monthly_return_draft_cancel",
        )

    with col_return:
        do_return = st.button(
            "Kembalikan ke Draft",
            type="primary",
            icon=":material/undo:",
            use_container_width=True,
            disabled=(
                not notes_valid
                or not confirm
            ),
            key="monthly_return_draft_submit",
        )

    if cancel:
        st.rerun()

    if not do_return:
        return

    try:
        with st.spinner(
            "Mengembalikan laporan ke Draft..."
        ):
            return_monthly_report_to_draft(
                monthly_report_id=(
                    monthly_report_id
                ),
                notes=str(
                    notes
                ).strip(),
            )

        clear_report_cache()

        st.session_state[
            "monthly_report_flash_success"
        ] = (
            "Laporan berhasil dikembalikan ke Draft. "
            "Riwayat verifikasi sebelumnya tetap tersimpan."
        )

        st.rerun()

    except Exception as exc:
        st.error(
            "Laporan gagal dikembalikan ke Draft."
        )

        st.exception(
            exc
        )


# ==========================================================
# CONTEXTUAL ACTION BAR
# ==========================================================


def _render_primary_action(
    bundle: dict[str, Any],
    *,
    report_year: int,
    report_month: int,
    gi_flc: str,
    gi_name: str,
) -> None:
    report = bundle[
        "monthly_report"
    ]

    status = _status_code(
        report
    )

    monthly_report_id = _safe_string(
        report.get(
            "monthly_report_id"
        ),
        "",
    )

    with st.container(
        border=True
    ):
        if status in {
            "DRAFT",
            "REJECTED",
        }:
            ongoing_trip = _has_ongoing_trip(
                bundle
            )

            col_info, col_action = st.columns(
                [4, 1.7],
                vertical_alignment="center",
            )

            with col_info:
                if ongoing_trip:
                    st.warning(
                        "Masih ada Trip yang belum memiliki data pemulihan."
                    )
                else:
                    st.markdown(
                        "**Siap diajukan**"
                    )

                    st.caption(
                        "Pastikan preview laporan sudah sesuai."
                    )

            with col_action:
                label = (
                    "Ajukan Kembali"
                    if status
                    == "REJECTED"
                    else "Ajukan untuk Verifikasi"
                )

                if st.button(
                    label,
                    type="primary",
                    icon=":material/send:",
                    use_container_width=True,
                    disabled=(
                        not can_input()
                        or ongoing_trip
                        or not monthly_report_id
                    ),
                    key="monthly_primary_submit",
                ):
                    _render_submit_dialog(
                        monthly_report_id=(
                            monthly_report_id
                        ),
                        period_label=(
                            _period_label(
                                report_year,
                                report_month,
                            )
                        ),
                        gi_name=(
                            gi_name
                        ),
                    )

        elif status == "SUBMITTED":
            if can_verify():
                col_info, col_reject, col_verify = st.columns(
                    [3.5, 1.35, 1.8],
                    vertical_alignment="center",
                )

                with col_info:
                    st.markdown(
                        "**Menunggu keputusan Anda**"
                    )

                    st.caption(
                        "Review preview laporan lalu verifikasi atau "
                        "kembalikan untuk perbaikan."
                    )

                with col_reject:
                    if st.button(
                        "Kembalikan",
                        icon=":material/reply:",
                        use_container_width=True,
                        key="monthly_primary_reject",
                    ):
                        _render_reject_dialog(
                            monthly_report_id=(
                                monthly_report_id
                            ),
                            report_year=(
                                report_year
                            ),
                            report_month=(
                                report_month
                            ),
                            gi_name=(
                                gi_name
                            ),
                        )

                with col_verify:
                    if st.button(
                        "Verifikasi & e-Sign",
                        type="primary",
                        icon=":material/verified:",
                        use_container_width=True,
                        key="monthly_primary_verify",
                    ):
                        _render_verify_dialog(
                            monthly_report_id=(
                                monthly_report_id
                            ),
                            report_year=(
                                report_year
                            ),
                            report_month=(
                                report_month
                            ),
                            gi_flc=(
                                gi_flc
                            ),
                            gi_name=(
                                gi_name
                            ),
                        )

            else:
                st.info(
                    "Laporan sudah diajukan dan sedang menunggu Verifikator."
                )

        elif status == "APPROVED":
            col_info, col_admin_action = st.columns(
                [4, 1.8],
                vertical_alignment="center",
            )

            with col_info:
                st.markdown(
                    "**Laporan selesai**"
                )

                st.caption(
                    "e-Sign sudah tercatat dan laporan menjadi "
                    "dokumen resmi."
                )

            with col_admin_action:
                if _can_return_approved_to_draft():
                    if st.button(
                        "Kembalikan ke Draft",
                        icon=":material/undo:",
                        use_container_width=True,
                        key="monthly_primary_return_draft",
                    ):
                        _render_return_to_draft_dialog(
                            monthly_report_id=(
                                monthly_report_id
                            ),
                            report_year=(
                                report_year
                            ),
                            report_month=(
                                report_month
                            ),
                            gi_name=(
                                gi_name
                            ),
                        )


# ==========================================================
# PREVIEW
# ==========================================================


def _render_report_preview(
    bundle: dict[str, Any],
) -> None:
    with st.expander(
        "Review Isi Laporan",
        expanded=True,
    ):
        (
            tab_rekap_trip,
            tab_rekap_lepas,
            tab_detail_trip,
            tab_detail_lepas,
        ) = st.tabs(
            [
                "Rekap Trip",
                "Rekap Lepas",
                "Detail Trip",
                "Detail Lepas",
            ]
        )

        with tab_rekap_trip:
            _display_dataframe(
                _trip_recap_view(
                    bundle[
                        "rekap_trip"
                    ]
                ),
            )

        with tab_rekap_lepas:
            _display_dataframe(
                _lepas_recap_view(
                    bundle[
                        "rekap_lepas"
                    ]
                ),
            )

        with tab_detail_trip:
            st.caption(
                "Arus Sebelum/Setelah adalah arus beban per phasa. "
                "Jika pemulihan melalui manuver, Termanuver dan Sisa Beban "
                "juga ditampilkan per phasa R/S/T. "
                "Arus Ggn R/S/T/N adalah arus gangguan proteksi."
            )

            _display_dataframe(
                _detail_trip_view(
                    bundle[
                        "detail_trip"
                    ]
                ),
                height=440,
            )

        with tab_detail_lepas:
            st.caption(
                "Arus Sebelum/Setelah, Beban Termanuver, dan Sisa Beban "
                "ditampilkan per phasa R/S/T sesuai status pemulihan."
            )

            _display_dataframe(
                _detail_lepas_view(
                    bundle[
                        "detail_lepas"
                    ]
                ),
                height=440,
            )


# ==========================================================
# OFFICIAL FILES
# ==========================================================


def _render_official_files(
    bundle: dict[str, Any],
    *,
    report_year: int,
    report_month: int,
    gi_flc: str,
    gi_name: str,
) -> None:
    if not bool(
        bundle.get(
            "official_available"
        )
    ):
        return

    official_files = bundle.get(
        "official_files"
    )

    if not isinstance(
        official_files,
        list,
    ):
        official_files = []

    pdf_file = next(
        (
            item
            for item in official_files
            if _safe_string(
                item.get(
                    "file_format"
                ),
                "",
            ).upper()
            == "PDF"
        ),
        None,
    )

    xlsx_file = next(
        (
            item
            for item in official_files
            if _safe_string(
                item.get(
                    "file_format"
                ),
                "",
            ).upper()
            == "XLSX"
        ),
        None,
    )

    st.markdown(
        "### Dokumen Resmi"
    )

    with st.container(
        border=True
    ):
        if (
            pdf_file
            and xlsx_file
        ):
            col_info, col_pdf, col_excel = st.columns(
                [3.4, 1.35, 1.35],
                vertical_alignment="center",
            )

            with col_info:
                st.markdown(
                    "**Dokumen sudah diarsipkan**"
                )

                st.caption(
                    "PDF dan Excel tersimpan di Google Drive."
                )

            with col_pdf:
                st.link_button(
                    "Buka PDF",
                    _safe_string(
                        pdf_file.get(
                            "drive_file_url"
                        ),
                        "",
                    ),
                    icon=":material/picture_as_pdf:",
                    use_container_width=True,
                )

            with col_excel:
                st.link_button(
                    "Buka Excel",
                    _safe_string(
                        xlsx_file.get(
                            "drive_file_url"
                        ),
                        "",
                    ),
                    icon=":material/table_view:",
                    use_container_width=True,
                )

            return

        col_info, col_retry = st.columns(
            [4, 1.8],
            vertical_alignment="center",
        )

        with col_info:
            st.warning(
                "Laporan sudah terverifikasi, tetapi file resmi "
                "belum lengkap di Google Drive."
            )

        with col_retry:
            if st.button(
                "Coba Generate Ulang",
                type="primary",
                icon=":material/refresh:",
                use_container_width=True,
                key="monthly_retry_archive",
            ):
                try:
                    with st.status(
                        "Membuat dan mengarsipkan dokumen...",
                        expanded=True,
                    ) as process:
                        generate_and_archive_official_report(
                            bundle=(
                                bundle
                            ),
                            report_year=(
                                report_year
                            ),
                            report_month=(
                                report_month
                            ),
                            gi_flc=(
                                gi_flc
                            ),
                            gi_name=(
                                gi_name
                            ),
                        )

                        clear_report_cache()

                        process.update(
                            label="Dokumen berhasil diarsipkan.",
                            state="complete",
                            expanded=False,
                        )

                    st.session_state[
                        "monthly_report_flash_success"
                    ] = (
                        "PDF dan Excel berhasil dibuat dan "
                        "diarsipkan ke Google Drive."
                    )

                    st.rerun()

                except Exception as exc:
                    st.error(
                        "Generate ulang dokumen gagal."
                    )
                    st.exception(
                        exc
                    )


# ==========================================================
# HISTORY
# ==========================================================


def _render_history(
    bundle: dict[str, Any],
) -> None:
    history = bundle.get(
        "approval_history"
    )

    if not isinstance(
        history,
        list,
    ):
        history = []

    if not history:
        return

    with st.expander(
        "Riwayat Verifikasi & Audit",
        expanded=False,
    ):
        st.caption(
            "Riwayat ini bersifat read-only. Data verifikasi / e-Sign "
            "tidak dapat diedit atau dihapus."
        )

        rows: list[dict[str, Any]] = []

        for item in history:
            rows.append(
                {
                    "Waktu":
                        _format_datetime(
                            item.get(
                                "acted_at"
                            )
                        ),
                    "Proses":
                        _history_action_label(
                            item.get(
                                "action"
                            )
                        ),
                    "Role":
                        _safe_string(
                            item.get(
                                "actor_role"
                            )
                        ),
                    "Nama":
                        _safe_string(
                            item.get(
                                "signer_name"
                            )
                        ),
                    "Catatan":
                        _safe_string(
                            item.get(
                                "notes"
                            )
                        ),
                }
            )

        st.dataframe(
            pd.DataFrame(
                rows
            ),
            use_container_width=True,
            hide_index=True,
        )


# ==========================================================
# ARCHIVE LIST
# ==========================================================


def _render_archive_list() -> None:
    st.markdown(
        "## Arsip Laporan Bulanan"
    )

    st.caption(
        "Dokumen resmi yang sudah diverifikasi dan disimpan "
        "di Google Drive."
    )

    try:
        rows = load_monthly_report_list()

    except Exception as exc:
        st.warning(
            "Arsip laporan belum dapat dibaca."
        )

        st.caption(
            str(
                exc
            )
        )
        return

    approved_rows = [
        row
        for row in rows
        if _safe_string(
            row.get(
                "status"
            ),
            "",
        ).upper()
        == "APPROVED"
        and (
            isinstance(
                row.get(
                    "pdf_file"
                ),
                dict,
            )
            or isinstance(
                row.get(
                    "xlsx_file"
                ),
                dict,
            )
        )
    ]

    if not approved_rows:
        st.info(
            "Belum ada dokumen resmi di arsip."
        )
        return

    for row in approved_rows:
        report_year = int(
            row.get(
                "report_year"
            )
            or 0
        )

        report_month = int(
            row.get(
                "report_month"
            )
            or 0
        )

        pdf_file = row.get(
            "pdf_file"
        )

        xlsx_file = row.get(
            "xlsx_file"
        )

        with st.container(
            border=True
        ):
            col_info, col_pdf, col_excel = st.columns(
                [4, 1.1, 1.1],
                vertical_alignment="center",
            )

            with col_info:
                st.markdown(
                    (
                        f"**{_period_label(report_year, report_month)}"
                        f" · {_safe_string(row.get('gi_name'))}**"
                    )
                )

                st.caption(
                    (
                        f"Diverifikasi oleh "
                        f"{_safe_string(row.get('signer_name'))} · "
                        f"{_format_datetime(row.get('verified_at'))}"
                    )
                )

            with col_pdf:
                if isinstance(
                    pdf_file,
                    dict,
                ):
                    st.link_button(
                        "PDF",
                        _safe_string(
                            pdf_file.get(
                                "drive_file_url"
                            ),
                            "",
                        ),
                        icon=":material/picture_as_pdf:",
                        use_container_width=True,
                    )

            with col_excel:
                if isinstance(
                    xlsx_file,
                    dict,
                ):
                    st.link_button(
                        "Excel",
                        _safe_string(
                            xlsx_file.get(
                                "drive_file_url"
                            ),
                            "",
                        ),
                        icon=":material/table_view:",
                        use_container_width=True,
                    )


# ==========================================================
# ACTIVE REPORT
# ==========================================================


def _render_active_report() -> None:
    try:
        feeders = get_accessible_feeders()

    except Exception as exc:
        st.error(
            "Hierarki Penyulang tidak dapat dibaca."
        )
        st.exception(
            exc
        )
        return

    if not feeders:
        st.info(
            "Tidak ada Penyulang yang dapat diakses."
        )
        return

    selector = _render_report_selector(
        feeders
    )

    if selector is None:
        return

    (
        report_year,
        report_month,
        gi_flc,
        gi_name,
    ) = selector

    try:
        with st.spinner(
            "Menyiapkan laporan..."
        ):
            bundle = build_monthly_report_bundle(
                report_year=(
                    report_year
                ),
                report_month=(
                    report_month
                ),
                scope_functloc_id=(
                    gi_flc
                ),
            )

    except Exception as exc:
        st.error(
            "Laporan bulanan tidak dapat disiapkan."
        )
        st.exception(
            exc
        )
        return

    _render_report_header(
        bundle,
        report_year=report_year,
        report_month=report_month,
        gi_name=gi_name,
    )

    _render_summary(
        bundle
    )

    st.write(
        ""
    )

    _render_primary_action(
        bundle,
        report_year=report_year,
        report_month=report_month,
        gi_flc=gi_flc,
        gi_name=gi_name,
    )

    _render_report_preview(
        bundle
    )

    _render_official_files(
        bundle,
        report_year=report_year,
        report_month=report_month,
        gi_flc=gi_flc,
        gi_name=gi_name,
    )

    _render_history(
        bundle
    )


# ==========================================================
# PAGE
# ==========================================================


def render_page() -> None:
    render_sidebar()
    _apply_page_style()

    st.title(
        "Laporan Bulanan"
    )

    st.caption(
        "Review, verifikasi, e-Sign, dan arsip laporan penyulang "
        "20 kV dalam satu alur."
    )

    if not can_view():
        st.error(
            "Anda tidak memiliki akses untuk melihat Laporan Bulanan."
        )
        return

    success_message = st.session_state.pop(
        "monthly_report_flash_success",
        None,
    )

    warning_message = st.session_state.pop(
        "monthly_report_flash_warning",
        None,
    )

    if success_message:
        st.success(
            str(
                success_message
            )
        )

    if warning_message:
        st.warning(
            str(
                warning_message
            )
        )

    tab_active, tab_archive = st.tabs(
        [
            "Laporan Aktif",
            "Arsip Laporan",
        ]
    )

    with tab_active:
        _render_active_report()

    with tab_archive:
        _render_archive_list()


render_page()