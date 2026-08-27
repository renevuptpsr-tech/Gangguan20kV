from datetime import date, datetime, time
from math import sqrt
from typing import Any, cast

import streamlit as st

from components.sidebar import render_sidebar
from services.event_service import get_current_user_id
from services.supabase_client import get_supabase_client


GangguanRow = dict[str, Any]


# ==========================================================
# DATA
# ==========================================================


@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def _load_active_gangguan(
    user_id: str,
) -> list[GangguanRow]:
    """
    Membaca seluruh gangguan penyulang
    yang masih berstatus ONGOING.
    """

    supabase = get_supabase_client()

    response = (
        supabase
        .table("vw_kejadian_penyulang_detail")
        .select("*")
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
        .execute()
    )

    if not response.data:
        return []

    return cast(
        list[GangguanRow],
        response.data,
    )


def clear_active_gangguan_cache() -> None:
    """
    Membersihkan cache Gangguan Aktif.
    """

    _load_active_gangguan.clear()


# ==========================================================
# FORMATTERS
# ==========================================================


def _format_date(
    value: Any,
) -> str:
    if value is None:
        return "-"

    text = str(value).strip()

    if not text:
        return "-"

    try:
        year, month, day = (
            text[:10].split("-")
        )

        return (
            f"{day}-{month}-{year}"
        )

    except Exception:
        return text


def _format_time(
    value: Any,
) -> str:
    if value is None:
        return "-"

    text = str(value).strip()

    if not text:
        return "-"

    return text[:5]


def _format_number(
    value: Any,
    decimals: int = 2,
) -> str:
    if value is None:
        return "-"

    try:
        number = float(value)

        return (
            f"{number:,.{decimals}f}"
        )

    except (
        TypeError,
        ValueError,
    ):
        return str(value)


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


def _phase_current_value(
    row: GangguanRow,
    *,
    phase_field: str,
    legacy_field: str,
) -> float | None:
    """
    Membaca arus per phasa.

    Untuk record lama yang belum memiliki field R/S/T,
    fallback ke field legacy single-current.
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
    row: GangguanRow,
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
    minutes: float | None,
) -> str:
    """
    Format durasi menjadi:
    - menit
    - jam + menit
    - hari + jam + menit
    """

    if minutes is None:
        return "-"

    if minutes < 0:
        return "-"

    total_minutes = int(
        round(minutes)
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


# ==========================================================
# DATE / TIME HELPERS
# ==========================================================


def _parse_date(
    value: Any,
) -> date | None:
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    try:
        return datetime.strptime(
            text[:10],
            "%Y-%m-%d",
        ).date()

    except Exception:
        return None


def _parse_time(
    value: Any,
) -> time | None:
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    text = text[:8]

    for fmt in (
        "%H:%M:%S",
        "%H:%M",
    ):
        try:
            return datetime.strptime(
                text,
                fmt,
            ).time()

        except Exception:
            continue

    return None


def _combine_datetime(
    date_value: Any,
    time_value: Any,
) -> datetime | None:
    input_date = _parse_date(
        date_value
    )

    input_time = _parse_time(
        time_value
    )

    if (
        input_date is None
        or input_time is None
    ):
        return None

    return datetime.combine(
        input_date,
        input_time,
    )


# ==========================================================
# ELECTRICAL CALCULATIONS
# ==========================================================


def _calculate_power_kw(
    voltage_kv: float,
    current_a: float,
    power_factor: float,
) -> float:
    """
    Daya aktif 3 fasa.

    P (kW)
    = √3 × V (kV) × I (A) × PF
    """

    if (
        voltage_kv <= 0
        or current_a <= 0
        or power_factor <= 0
    ):
        return 0.0

    return (
        sqrt(3)
        * voltage_kv
        * current_a
        * power_factor
    )


def _calculate_live_metrics(
    row: GangguanRow,
) -> dict[str, float | None]:
    """
    Menghitung estimasi realtime untuk
    gangguan yang masih ONGOING.

    Nilai ini hanya digunakan untuk display.

    Nilai final ENS dan durasi tetap dihitung
    oleh trigger PostgreSQL ketika data
    pemulihan / normalisasi disimpan.
    """

    result: dict[
        str,
        float | None
    ] = {
        "live_outage_min": None,
        "live_ens_kwh": None,
    }

    event_dt = _combine_datetime(
        row.get("event_date"),
        row.get("event_time"),
    )

    if event_dt is None:
        return result

    now_dt = datetime.now()

    if now_dt < event_dt:
        return result

    load_current = (
        _three_phase_average_from_row(
            row,
            prefix="load_current_before",
            legacy_field="load_current_before_a",
        )
        or 0.0
    )

    voltage_kv = float(
        row.get(
            "voltage_before_kv"
        )
        or 0.0
    )

    power_factor = float(
        row.get(
            "power_factor_before"
        )
        or 0.0
    )

    supply_status = str(
        row.get(
            "supply_status_code"
        )
        or ""
    ).strip()

    # ======================================================
    # BELUM TERSUPLAI
    # ======================================================

    if supply_status == "BELUM":
        outage_minutes = (
            now_dt - event_dt
        ).total_seconds() / 60.0

        power_kw = (
            _calculate_power_kw(
                voltage_kv=voltage_kv,
                current_a=load_current,
                power_factor=power_factor,
            )
        )

        ens_kwh = (
            power_kw
            * outage_minutes
            / 60.0
        )

        result[
            "live_outage_min"
        ] = outage_minutes

        result[
            "live_ens_kwh"
        ] = ens_kwh

        return result

    # ======================================================
    # SELURUH BEBAN SUDAH TERSUPLAI
    # ======================================================

    if supply_status in {
        "FEEDER_ASAL",
        "MANUVER_PENUH",
    }:
        outage_value = row.get(
            "customer_outage_duration_min"
        )

        ens_value = row.get(
            "ens_kwh"
        )

        if outage_value is not None:
            result[
                "live_outage_min"
            ] = float(
                outage_value
            )

        if ens_value is not None:
            result[
                "live_ens_kwh"
            ] = float(
                ens_value
            )

        return result

    # ======================================================
    # MANUVER SEBAGIAN
    # ======================================================

    if (
        supply_status
        == "MANUVER_SEBAGIAN"
    ):
        supply_dt = _combine_datetime(
            row.get(
                "supply_restored_date"
            ),
            row.get(
                "supply_restored_time"
            ),
        )

        if (
            supply_dt is None
            or supply_dt < event_dt
        ):
            return result

        maneuvered_current = (
            _three_phase_average_from_row(
                row,
                prefix="maneuvered_current",
                legacy_field="maneuvered_current_a",
            )
            or 0.0
        )

        remaining_current = (
            _three_phase_average_from_row(
                row,
                prefix="remaining_current",
                legacy_field="remaining_current_a",
            )
        )

        if remaining_current is None:
            remaining_current = max(
                load_current
                - maneuvered_current,
                0.0,
            )

        # ==================================================
        # INTERVAL 1
        # Seluruh beban padam
        # ==================================================

        interval_1_min = (
            supply_dt - event_dt
        ).total_seconds() / 60.0

        full_power_kw = (
            _calculate_power_kw(
                voltage_kv=voltage_kv,
                current_a=load_current,
                power_factor=power_factor,
            )
        )

        ens_interval_1 = (
            full_power_kw
            * interval_1_min
            / 60.0
        )

        # ==================================================
        # INTERVAL 2
        # Hanya sisa beban masih padam
        # ==================================================

        final_dt = _combine_datetime(
            row.get(
                "final_supply_normalization_date"
            ),
            row.get(
                "final_supply_normalization_time"
            ),
        )

        if final_dt is not None:
            interval_2_end = final_dt

        else:
            interval_2_end = now_dt

        if interval_2_end < supply_dt:
            return result

        interval_2_min = (
            interval_2_end
            - supply_dt
        ).total_seconds() / 60.0

        remaining_power_kw = (
            _calculate_power_kw(
                voltage_kv=voltage_kv,
                current_a=remaining_current,
                power_factor=power_factor,
            )
        )

        ens_interval_2 = (
            remaining_power_kw
            * interval_2_min
            / 60.0
        )

        result[
            "live_outage_min"
        ] = (
            interval_1_min
            + interval_2_min
        )

        result[
            "live_ens_kwh"
        ] = (
            ens_interval_1
            + ens_interval_2
        )

        return result

    return result


def _render_supply_current_detail(
    row: GangguanRow,
) -> None:
    """
    Menampilkan arus termanuver / sisa beban R/S/T
    sesuai status suplai.
    """

    supply_status = str(
        row.get(
            "supply_status_code"
        )
        or ""
    ).strip().upper()

    if supply_status not in {
        "MANUVER_PENUH",
        "MANUVER_SEBAGIAN",
    }:
        return

    st.markdown(
        "##### Pemulihan Beban"
    )

    st.caption(
        "Beban Berhasil Dimanuver"
    )

    col_mr, col_ms, col_mt = (
        st.columns(3)
    )

    with col_mr:
        st.metric(
            "Phasa R",
            (
                _format_number(
                    _phase_current_value(
                        row,
                        phase_field="maneuvered_current_r_a",
                        legacy_field="maneuvered_current_a",
                    )
                )
                + " A"
            ),
        )

    with col_ms:
        st.metric(
            "Phasa S",
            (
                _format_number(
                    _phase_current_value(
                        row,
                        phase_field="maneuvered_current_s_a",
                        legacy_field="maneuvered_current_a",
                    )
                )
                + " A"
            ),
        )

    with col_mt:
        st.metric(
            "Phasa T",
            (
                _format_number(
                    _phase_current_value(
                        row,
                        phase_field="maneuvered_current_t_a",
                        legacy_field="maneuvered_current_a",
                    )
                )
                + " A"
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
        supply_status
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
                    _format_number(
                        _phase_current_value(
                            row,
                            phase_field="remaining_current_r_a",
                            legacy_field="remaining_current_a",
                        )
                    )
                    + " A"
                ),
            )

        with col_rs:
            st.metric(
                "Sisa S",
                (
                    _format_number(
                        _phase_current_value(
                            row,
                            phase_field="remaining_current_s_a",
                            legacy_field="remaining_current_a",
                        )
                    )
                    + " A"
                ),
            )

        with col_rt:
            st.metric(
                "Sisa T",
                (
                    _format_number(
                        _phase_current_value(
                            row,
                            phase_field="remaining_current_t_a",
                            legacy_field="remaining_current_a",
                        )
                    )
                    + " A"
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


# ==========================================================
# LABELS
# ==========================================================


def _supply_status_label(
    row: GangguanRow,
) -> str:
    description = str(
        row.get(
            "supply_status_name"
        )
        or ""
    ).strip()

    if description:
        return description

    code = str(
        row.get(
            "supply_status_code"
        )
        or ""
    ).strip()

    labels: dict[str, str] = {
        "BELUM":
            "Belum Tersuplai",

        "FEEDER_ASAL":
            "Tersuplai dari Feeder Asal",

        "MANUVER_PENUH":
            "Manuver Seluruh Beban",

        "MANUVER_SEBAGIAN":
            "Manuver Sebagian Beban",
    }

    return labels.get(
        code,
        code or "-",
    )


def _pmt_status_label(
    row: GangguanRow,
) -> str:
    recovery_code = str(
        row.get(
            "recovery_status_code"
        )
        or ""
    ).strip()

    if not recovery_code:
        return (
            "Belum Normal"
        )

    labels: dict[str, str] = {
        "MASUK":
            "PMT Masuk",

        "MASUK_TRIP":
            "Masuk - Trip Kembali",
    }

    return labels.get(
        recovery_code,
        recovery_code,
    )


# ==========================================================
# SUMMARY
# ==========================================================


def _render_summary_metrics(
    rows: list[GangguanRow],
) -> None:
    total_active = len(
        rows
    )

    not_supplied = sum(
        1
        for row in rows
        if str(
            row.get(
                "supply_status_code"
            )
            or ""
        ).strip()
        == "BELUM"
    )

    partial_transfer = sum(
        1
        for row in rows
        if str(
            row.get(
                "supply_status_code"
            )
            or ""
        ).strip()
        == "MANUVER_SEBAGIAN"
    )

    full_transfer = sum(
        1
        for row in rows
        if str(
            row.get(
                "supply_status_code"
            )
            or ""
        ).strip()
        == "MANUVER_PENUH"
    )

    col_1, col_2, col_3, col_4 = (
        st.columns(4)
    )

    with col_1:
        st.metric(
            "Gangguan Aktif",
            total_active,
        )

    with col_2:
        st.metric(
            "Belum Tersuplai",
            not_supplied,
        )

    with col_3:
        st.metric(
            "Manuver Sebagian",
            partial_transfer,
        )

    with col_4:
        st.metric(
            "Manuver Penuh",
            full_transfer,
        )


# ==========================================================
# FILTER
# ==========================================================


def _render_filters(
    rows: list[GangguanRow],
) -> list[GangguanRow]:
    """
    Filter berdasarkan:
    - Gardu Induk
    - Status Suplai
    - Penyulang
    """

    if not rows:
        return rows

    # ======================================================
    # GI OPTIONS
    # ======================================================

    gi_values: list[str] = sorted(
        {
            str(
                row.get(
                    "gi_name"
                )
                or ""
            ).strip()
            for row in rows
            if str(
                row.get(
                    "gi_name"
                )
                or ""
            ).strip()
        }
    )

    gi_options: list[str] = [
        "SEMUA",
        *gi_values,
    ]

    # ======================================================
    # SUPPLY OPTIONS
    # ======================================================

    supply_labels: dict[str, str] = {
        "SEMUA":
            "Semua Status",

        "BELUM":
            "Belum Tersuplai",

        "MANUVER_SEBAGIAN":
            "Manuver Sebagian",

        "MANUVER_PENUH":
            "Manuver Seluruh Beban",

        "FEEDER_ASAL":
            "Tersuplai Feeder Asal",
    }

    supply_options: list[str] = list(
        supply_labels.keys()
    )

    # ======================================================
    # FORMATTERS
    # ======================================================

    def format_gi(
        value: str,
    ) -> str:
        if value == "SEMUA":
            return (
                "Semua Gardu Induk"
            )

        return value

    def format_supply(
        value: str,
    ) -> str:
        return supply_labels.get(
            value,
            value,
        )

    # ======================================================
    # UI
    # ======================================================

    col_gi, col_supply, col_search = (
        st.columns(
            [1.2, 1.3, 1.8]
        )
    )

    with col_gi:
        selected_gi_raw = (
            st.selectbox(
                "Filter Gardu Induk",
                options=gi_options,
                index=0,
                format_func=format_gi,
                key="active_filter_gi",
            )
        )

    with col_supply:
        selected_supply_raw = (
            st.selectbox(
                "Status Suplai",
                options=supply_options,
                index=0,
                format_func=format_supply,
                key=(
                    "active_filter_supply"
                ),
            )
        )

    with col_search:
        keyword = st.text_input(
            "Cari Penyulang",
            placeholder=(
                "Contoh: RB-01"
            ),
            key=(
                "active_search_penyulang"
            ),
        )

    selected_gi = (
        str(selected_gi_raw)
        if selected_gi_raw
        is not None
        else "SEMUA"
    )

    selected_supply = (
        str(selected_supply_raw)
        if selected_supply_raw
        is not None
        else "SEMUA"
    )

    keyword_normalized = (
        keyword
        .strip()
        .lower()
    )

    # ======================================================
    # APPLY FILTER
    # ======================================================

    filtered_rows: list[
        GangguanRow
    ] = []

    for row in rows:
        row_gi = str(
            row.get(
                "gi_name"
            )
            or ""
        ).strip()

        row_supply = str(
            row.get(
                "supply_status_code"
            )
            or ""
        ).strip()

        penyulang_code = str(
            row.get(
                "penyulang_code"
            )
            or ""
        ).strip()

        penyulang_name = str(
            row.get(
                "penyulang_name"
            )
            or ""
        ).strip()

        if (
            selected_gi != "SEMUA"
            and row_gi != selected_gi
        ):
            continue

        if (
            selected_supply
            != "SEMUA"
            and row_supply
            != selected_supply
        ):
            continue

        if keyword_normalized:
            searchable = (
                f"{penyulang_code} "
                f"{penyulang_name}"
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
# OPEN EVENT IN MAIN FORM
# ==========================================================


def _open_event_for_recovery(
    event_id: str,
) -> None:
    """
    Mengarahkan Gangguan Aktif ke form utama
    input_kejadian.py dalam mode UPDATE.
    """

    if not event_id:
        st.error(
            "Event ID tidak valid."
        )
        return

    # Mode form
    st.session_state[
        "input_mode"
    ] = "UPDATE"

    # Record yang akan dibuka
    st.session_state[
        "edit_event_id"
    ] = event_id

    # Penanda sumber navigasi
    st.session_state[
        "edit_event_source"
    ] = "GANGGUAN_AKTIF"

    st.switch_page(
        "pages/input_kejadian.py"
    )


# ==========================================================
# TECHNICAL DETAIL
# ==========================================================


def _render_technical_detail(
    row: GangguanRow,
) -> None:
    indication_names = (
        row.get(
            "indikasi_names"
        )
        or []
    )

    # ======================================================
    # PROTEKSI
    # ======================================================

    st.markdown(
        "##### Proteksi & Indikasi"
    )

    col_ann, col_ind = (
        st.columns(2)
    )

    with col_ann:
        st.caption(
            "Annunciator"
        )

        st.write(
            str(
                row.get(
                    "annunciator_name"
                )
                or "-"
            )
        )

    with col_ind:
        st.caption(
            "Indikasi Relay / Proteksi"
        )

        if indication_names:
            st.write(
                ", ".join(
                    str(value)
                    for value
                    in indication_names
                )
            )

        else:
            st.write(
                "-"
            )

    # ======================================================
    # LOAD CURRENT BEFORE EVENT
    # ======================================================

    st.markdown(
        "##### Arus Beban Sebelum Gangguan"
    )

    col_lr, col_ls, col_lt = (
        st.columns(3)
    )

    with col_lr:
        st.metric(
            "Phasa R",
            (
                _format_number(
                    _phase_current_value(
                        row,
                        phase_field="load_current_before_r_a",
                        legacy_field="load_current_before_a",
                    )
                )
                + " A"
            ),
        )

    with col_ls:
        st.metric(
            "Phasa S",
            (
                _format_number(
                    _phase_current_value(
                        row,
                        phase_field="load_current_before_s_a",
                        legacy_field="load_current_before_a",
                    )
                )
                + " A"
            ),
        )

    with col_lt:
        st.metric(
            "Phasa T",
            (
                _format_number(
                    _phase_current_value(
                        row,
                        phase_field="load_current_before_t_a",
                        legacy_field="load_current_before_a",
                    )
                )
                + " A"
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
            "Arus rata-rata 3 phasa untuk estimasi ENS berjalan: "
            f"**{average_before:,.2f} A**"
        )

    _render_supply_current_detail(
        row
    )

    # ======================================================
    # FAULT CURRENT
    # ======================================================

    st.markdown(
        "##### Arus Gangguan"
    )

    col_r, col_s, col_t, col_n = (
        st.columns(4)
    )

    with col_r:
        st.metric(
            "I-R",
            (
                _format_number(
                    row.get(
                        "fault_current_r_a"
                    )
                )
                + " A"
            ),
        )

    with col_s:
        st.metric(
            "I-S",
            (
                _format_number(
                    row.get(
                        "fault_current_s_a"
                    )
                )
                + " A"
            ),
        )

    with col_t:
        st.metric(
            "I-T",
            (
                _format_number(
                    row.get(
                        "fault_current_t_a"
                    )
                )
                + " A"
            ),
        )

    with col_n:
        st.metric(
            "I-N / Residual",
            (
                _format_number(
                    row.get(
                        "fault_current_n_a"
                    )
                )
                + " A"
            ),
        )

    # ======================================================
    # PHASES
    # ======================================================

    phases: list[str] = []

    if row.get(
        "phase_r"
    ):
        phases.append(
            "R"
        )

    if row.get(
        "phase_s"
    ):
        phases.append(
            "S"
        )

    if row.get(
        "phase_t"
    ):
        phases.append(
            "T"
        )

    if row.get(
        "phase_n"
    ):
        phases.append(
            "N"
        )

    st.write(
        "**Phasa Terganggu:** "
        + (
            ", ".join(
                phases
            )
            if phases
            else "-"
        )
    )

    # ======================================================
    # KRONOLOGI
    # ======================================================

    st.markdown(
        "##### Kronologi Gangguan"
    )

    st.write(
        str(
            row.get(
                "event_description"
            )
            or "-"
        )
    )

    recovery_description = str(
        row.get(
            "recovery_description"
        )
        or ""
    ).strip()

    if recovery_description:
        st.markdown(
            "##### Update Pemulihan Terakhir"
        )

        st.write(
            recovery_description
        )


# ==========================================================
# CARD
# ==========================================================


def _render_gangguan_card(
    row: GangguanRow,
) -> None:
    event_id = str(
        row.get(
            "event_id"
        )
        or ""
    )

    penyulang_code = str(
        row.get(
            "penyulang_code"
        )
        or "-"
    )

    penyulang_name = str(
        row.get(
            "penyulang_name"
        )
        or "-"
    )

    ultg_name = str(
        row.get(
            "ultg_name"
        )
        or "-"
    )

    gi_name = str(
        row.get(
            "gi_name"
        )
        or "-"
    )

    bay_name = str(
        row.get(
            "bay_name"
        )
        or "-"
    )

    event_date = _format_date(
        row.get(
            "event_date"
        )
    )

    event_time = _format_time(
        row.get(
            "event_time"
        )
    )

    supply_status = (
        _supply_status_label(
            row
        )
    )

    pmt_status = (
        _pmt_status_label(
            row
        )
    )

    pic_name = str(
        row.get(
            "pic_name"
        )
        or row.get(
            "pic_code"
        )
        or "-"
    )

    cause_name = str(
        row.get(
            "cause_name"
        )
        or "-"
    )

    live_metrics = (
        _calculate_live_metrics(
            row
        )
    )

    live_outage = (
        live_metrics.get(
            "live_outage_min"
        )
    )

    live_ens = (
        live_metrics.get(
            "live_ens_kwh"
        )
    )

    # ======================================================
    # CARD
    # ======================================================

    with st.container(
        border=True
    ):
        # ==================================================
        # HEADER
        # ==================================================

        col_title, col_status = (
            st.columns(
                [4, 1]
            )
        )

        with col_title:
            st.markdown(
                f"### {penyulang_code} — "
                f"{penyulang_name}"
            )

            st.caption(
                f"{ultg_name} • "
                f"{gi_name} • "
                f"{bay_name}"
            )

        with col_status:
            st.caption(
                "Status"
            )

            st.markdown(
                "**ONGOING**"
            )

        # ==================================================
        # MAIN METRICS
        # ==================================================

        col_trip, col_duration, col_ens = (
            st.columns(3)
        )

        with col_trip:
            st.metric(
                "Trip PMT",
                (
                    f"{event_date} "
                    f"{event_time}"
                ),
            )

        with col_duration:
            st.metric(
                "Durasi Padam Berjalan",
                _format_duration(
                    live_outage
                ),
            )

        with col_ens:
            st.metric(
                "ENS Berjalan",
                (
                    f"{live_ens:,.2f} kWh"
                    if live_ens
                    is not None
                    else "-"
                ),
            )

        st.caption(
            "Arus Beban Sebelum Gangguan"
        )

        col_current_r, col_current_s, col_current_t = (
            st.columns(3)
        )

        with col_current_r:
            st.metric(
                "Phasa R",
                (
                    _format_number(
                        _phase_current_value(
                            row,
                            phase_field="load_current_before_r_a",
                            legacy_field="load_current_before_a",
                        )
                    )
                    + " A"
                ),
            )

        with col_current_s:
            st.metric(
                "Phasa S",
                (
                    _format_number(
                        _phase_current_value(
                            row,
                            phase_field="load_current_before_s_a",
                            legacy_field="load_current_before_a",
                        )
                    )
                    + " A"
                ),
            )

        with col_current_t:
            st.metric(
                "Phasa T",
                (
                    _format_number(
                        _phase_current_value(
                            row,
                            phase_field="load_current_before_t_a",
                            legacy_field="load_current_before_a",
                        )
                    )
                    + " A"
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
                "Arus rata-rata 3 phasa untuk kalkulasi ENS berjalan: "
                f"**{average_before:,.2f} A**"
            )

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
                    "R",
                    (
                        _format_number(
                            _phase_current_value(
                                row,
                                phase_field="maneuvered_current_r_a",
                                legacy_field="maneuvered_current_a",
                            )
                        )
                        + " A"
                    ),
                )

            with col_ms:
                st.metric(
                    "S",
                    (
                        _format_number(
                            _phase_current_value(
                                row,
                                phase_field="maneuvered_current_s_a",
                                legacy_field="maneuvered_current_a",
                            )
                        )
                        + " A"
                    ),
                )

            with col_mt:
                st.metric(
                    "T",
                    (
                        _format_number(
                            _phase_current_value(
                                row,
                                phase_field="maneuvered_current_t_a",
                                legacy_field="maneuvered_current_a",
                            )
                        )
                        + " A"
                    ),
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
                        _format_number(
                            _phase_current_value(
                                row,
                                phase_field="remaining_current_r_a",
                                legacy_field="remaining_current_a",
                            )
                        )
                        + " A"
                    ),
                )

            with col_rs:
                st.metric(
                    "Sisa S",
                    (
                        _format_number(
                            _phase_current_value(
                                row,
                                phase_field="remaining_current_s_a",
                                legacy_field="remaining_current_a",
                            )
                        )
                        + " A"
                    ),
                )

            with col_rt:
                st.metric(
                    "Sisa T",
                    (
                        _format_number(
                            _phase_current_value(
                                row,
                                phase_field="remaining_current_t_a",
                                legacy_field="remaining_current_a",
                            )
                        )
                        + " A"
                    ),
                )

        st.caption(
            "Durasi padam dan ENS adalah estimasi berjalan "
            "selama gangguan masih aktif. "
            "Nilai final dihitung setelah data "
            "pemulihan / normalisasi disimpan."
        )

        st.divider()

        # ==================================================
        # COMPACT SUMMARY
        # ==================================================

        col_operation, col_system = (
            st.columns(2)
        )

        with col_operation:
            st.markdown(
                "**Gangguan**"
            )

            st.write(
                f"PIC: **{pic_name}**"
            )

            st.write(
                "Klasifikasi: "
                f"**{cause_name}**"
            )

        with col_system:
            st.markdown(
                "**Kondisi Sistem**"
            )

            st.write(
                "Status Suplai: "
                f"**{supply_status}**"
            )

            st.write(
                "Status PMT: "
                f"**{pmt_status}**"
            )

        # ==================================================
        # TECHNICAL DETAIL
        # ==================================================

        with st.expander(
            "Detail Teknis Gangguan"
        ):
            _render_technical_detail(
                row
            )

        # ==================================================
        # ACTION
        # ==================================================

        st.divider()

        if st.button(
            "Pemulihan & Normalisasi",
            key=(
                f"recovery_"
                f"{event_id}"
            ),
            type="primary",
            use_container_width=True,
        ):
            _open_event_for_recovery(
                event_id
            )


# ==========================================================
# PAGE
# ==========================================================


def render_page() -> None:
    render_sidebar()

    st.title(
        "Gangguan Aktif"
    )

    st.caption(
        "Monitoring gangguan penyulang yang masih "
        "memerlukan pemulihan beban atau normalisasi PMT."
    )

    # ======================================================
    # AUTH
    # ======================================================

    user_id = (
        get_current_user_id()
    )

    if user_id is None:
        st.error(
            "Session login tidak valid. "
            "Silakan login kembali."
        )

        return

    # ======================================================
    # LOAD DATA
    # ======================================================

    try:
        rows = (
            _load_active_gangguan(
                user_id
            )
        )

    except Exception as exc:
        st.error(
            "Data Gangguan Aktif "
            "tidak dapat dibaca."
        )

        st.exception(
            exc
        )

        return

    # ======================================================
    # SUMMARY
    # ======================================================

    _render_summary_metrics(
        rows
    )

    st.divider()

    # ======================================================
    # EMPTY
    # ======================================================

    if not rows:
        st.success(
            "Tidak terdapat gangguan penyulang "
            "yang masih aktif."
        )

        return

    # ======================================================
    # FILTER
    # ======================================================

    filtered_rows = (
        _render_filters(
            rows
        )
    )

    st.divider()

    if not filtered_rows:
        st.info(
            "Tidak ada gangguan aktif "
            "yang sesuai dengan filter."
        )

        return

    st.caption(
        f"Menampilkan "
        f"{len(filtered_rows)} dari "
        f"{len(rows)} gangguan aktif."
    )

    # ======================================================
    # CARDS
    # ======================================================

    for row in filtered_rows:
        _render_gangguan_card(
            row
        )


render_page()