from __future__ import annotations

import json
from datetime import date, datetime, time
from math import sqrt
from typing import Any

import streamlit as st

from components.hierarchy_selector import (
    render_hierarchy_selector,
)
from components.monthly_period_guard import (
    render_monthly_period_guard,
)
from components.sidebar import render_sidebar
from services.access_service import (
    can_edit,
    can_input,
)
from services.event_service import (
    create_event,
    create_event_indications,
    get_current_user_id,
    get_event_by_id,
    update_event,
    update_event_recovery,
)
from services.reference_service import (
    get_annunciators,
    get_causes,
    get_cause_rules,
    get_indications,
    get_pics,
)
from services.supabase_client import (
    get_supabase_client,
)
from services.profile_service import (
    get_my_profile,
)
from services import telegram_service
from services import drive_service


# ==========================================================
# TYPES
# ==========================================================

HierarchySelection = dict[str, Any]
EventRow = dict[str, Any]


# ==========================================================
# PAGE STYLE
# ==========================================================


def _apply_page_style() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1120px;
            padding-top: 2rem;
            padding-bottom: 3rem;
        }

        div[data-testid="stMetric"] {
            padding-top: 0.15rem;
            padding-bottom: 0.15rem;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 12px;
        }

        .stCaption {
            line-height: 1.35;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ==========================================================
# GENERIC HELPERS
# ==========================================================


def _build_reference_options(
    rows: list[dict[str, Any]],
    code_field: str,
) -> dict[str, str]:
    options: dict[str, str] = {}

    for row in rows:
        code_raw = row.get(
            code_field
        )

        if code_raw is None:
            continue

        code = str(
            code_raw
        ).strip()

        if not code:
            continue

        description = str(
            row.get(
                "description"
            )
            or code
        ).strip()

        options[
            code
        ] = description

    return options


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



def _optional_float(
    value: Any,
) -> float | None:
    """
    Konversi nilai numerik opsional.

    None / string kosong -> None.
    Nilai numerik valid -> float.
    """

    if value is None:
        return None

    if isinstance(
        value,
        bool,
    ):
        return float(
            int(
                value
            )
        )

    if isinstance(
        value,
        (int, float),
    ):
        return float(
            value
        )

    text_value = str(
        value
    ).strip()

    if not text_value:
        return None

    try:
        return float(
            text_value
        )

    except ValueError:
        return None



def _numeric_text_input_optional(
    label: str,
    *,
    key: str,
    placeholder: str = "Masukkan nilai",
    disabled: bool = False,
    help_text: str | None = None,
) -> float | None:
    """
    Input numerik opsional yang benar-benar kosong.

    Sengaja memakai st.text_input, bukan st.number_input,
    agar user tidak pernah melihat angka dummy 0,00.

    Return:
    - kosong -> None
    - "0" -> 0.0
    - "12,5" -> 12.5
    """

    if key in st.session_state:
        existing = st.session_state.get(
            key
        )

        if existing is None:
            st.session_state[
                key
            ] = ""

        elif not isinstance(
            existing,
            str,
        ):
            numeric = _optional_float(
                existing
            )

            if numeric is None:
                st.session_state[
                    key
                ] = ""

            elif numeric.is_integer():
                st.session_state[
                    key
                ] = str(
                    int(
                        numeric
                    )
                )

            else:
                st.session_state[
                    key
                ] = str(
                    numeric
                )

    raw_value = st.text_input(
        label,
        key=key,
        placeholder=placeholder,
        disabled=disabled,
        help=help_text,
    )

    text_value = str(
        raw_value
        or ""
    ).strip()

    if not text_value:
        return None

    normalized = (
        text_value
        .replace(
            " ",
            "",
        )
        .replace(
            ",",
            ".",
        )
    )

    try:
        parsed = float(
            normalized
        )

    except ValueError:
        return None

    if parsed < 0:
        return None

    return parsed


def _three_phase_average(
    current_r: float | None,
    current_s: float | None,
    current_t: float | None,
) -> float | None:
    """
    Nilai rata-rata arus tiga phasa untuk kalkulasi existing:

        Iavg = (IR + IS + IT) / 3

    Hanya dihitung jika R, S, dan T seluruhnya tersedia.
    """

    if (
        current_r is None
        or current_s is None
        or current_t is None
    ):
        return None

    return (
        float(current_r)
        + float(current_s)
        + float(current_t)
    ) / 3.0


def _three_phase_fallback(
    *,
    row: EventRow,
    phase_field: str,
    legacy_field: str,
) -> float | None:
    """
    Membaca kolom phasa baru. Untuk record lama, fallback ke
    kolom legacy tunggal agar data lama tetap dapat diedit.
    """

    phase_value = _optional_float(
        row.get(
            phase_field
        )
    )

    if phase_value is not None:
        return phase_value

    return _optional_float(
        row.get(
            legacy_field
        )
    )


def _validate_three_phase_current(
    *,
    current_r: float | None,
    current_s: float | None,
    current_t: float | None,
    label: str,
    required: bool = False,
) -> list[str]:
    """
    - Ketiganya boleh kosong jika required=False.
    - Jika salah satu diisi, R/S/T harus diisi lengkap.
    - Jika required=True, seluruh phasa wajib diisi.
    """

    values = (
        current_r,
        current_s,
        current_t,
    )

    filled_count = sum(
        value is not None
        for value in values
    )

    if filled_count == 0:
        if required:
            return [
                f"{label} phasa R, S, dan T wajib diisi."
            ]

        return []

    if filled_count != 3:
        return [
            f"{label} harus diisi lengkap untuk phasa R, S, dan T."
        ]

    return []


def _render_three_phase_current_input(
    *,
    title: str,
    key_prefix: str,
    disabled: bool,
    help_text: str | None = None,
) -> tuple[
    float | None,
    float | None,
    float | None,
]:
    """
    Komponen input arus tiga phasa R | S | T.
    """

    st.caption(
        title
    )

    col_r, col_s, col_t = st.columns(
        3
    )

    with col_r:
        current_r = _numeric_text_input_optional(
            "Phasa R (A)",
            key=f"{key_prefix}_r",
            placeholder="R",
            disabled=disabled,
            help_text=help_text,
        )

    with col_s:
        current_s = _numeric_text_input_optional(
            "Phasa S (A)",
            key=f"{key_prefix}_s",
            placeholder="S",
            disabled=disabled,
            help_text=help_text,
        )

    with col_t:
        current_t = _numeric_text_input_optional(
            "Phasa T (A)",
            key=f"{key_prefix}_t",
            placeholder="T",
            disabled=disabled,
            help_text=help_text,
        )

    return (
        current_r,
        current_s,
        current_t,
    )


def _fixed_pf_display(
    *,
    key: str,
) -> float:
    """
    PF standar = 0,85 dan read-only.
    """

    display_key = (
        f"{key}_display"
    )

    st.text_input(
        "Faktor Daya / PF",
        value="0.85",
        key=display_key,
        disabled=True,
        help=(
            "Faktor daya ditetapkan otomatis 0,85 "
            "dan tidak perlu diinput user."
        ),
    )

    return 0.85


def _optional_int_text(
    value: Any,
) -> str:
    """
    Nilai integer database -> text untuk widget.

    NULL ditampilkan sebagai kosong,
    bukan 0.
    """

    if value is None:
        return ""

    try:
        return str(
            int(
                float(
                    value
                )
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        return ""


def _parse_optional_nonnegative_int(
    value: Any,
) -> tuple[int | None, str | None]:
    """
    Mengubah input text menjadi integer opsional.

    Return:
    (nilai, pesan_error)
    """

    if value is None:
        return None, None

    text = str(
        value
    ).strip()

    if not text:
        return None, None

    try:
        parsed = int(
            text
        )

    except ValueError:
        return (
            None,
            "Counter PMT harus berupa bilangan bulat.",
        )

    if parsed < 0:
        return (
            None,
            "Counter PMT tidak boleh bernilai negatif.",
        )

    return parsed, None


def _normalize_string_list(
    value: Any,
) -> list[str]:
    """
    Normalisasi array dari Supabase / PostgreSQL
    menjadi list[str].

    Mendukung:
    - Python list
    - tuple
    - JSON array
    - PostgreSQL array:
      {GFR_TD,OCR_TD}
    - comma-separated text
    """

    if value is None:
        return []

    if isinstance(
        value,
        list,
    ):
        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    if isinstance(
        value,
        tuple,
    ):
        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    text = str(
        value
    ).strip()

    if not text:
        return []

    # ======================================================
    # JSON ARRAY
    # ======================================================

    try:
        parsed = json.loads(
            text
        )

        if isinstance(
            parsed,
            list,
        ):
            return [
                str(item).strip()
                for item in parsed
                if str(item).strip()
            ]

    except (
        json.JSONDecodeError,
        TypeError,
    ):
        pass

    # ======================================================
    # POSTGRES ARRAY
    #
    # Contoh:
    # {GFR_TD,OCR_TD}
    # ======================================================

    if (
        text.startswith("{")
        and text.endswith("}")
    ):
        text = text[
            1:-1
        ]

    values = [
        item
        .strip()
        .strip('"')
        .strip("'")
        for item in text.split(",")
        if (
            item
            .strip()
            .strip('"')
            .strip("'")
        )
    ]

    return values


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


def _parse_time(
    value: Any,
) -> time | None:
    if value is None:
        return None

    if isinstance(
        value,
        datetime,
    ):
        return value.time()

    if isinstance(
        value,
        time,
    ):
        return value

    text = str(
        value
    ).strip()

    if not text:
        return None

    text = text[:8]

    for format_value in (
        "%H:%M:%S",
        "%H:%M",
    ):
        try:
            return datetime.strptime(
                text,
                format_value,
            ).time()

        except ValueError:
            continue

    return None


def _combine_datetime(
    input_date: date | None,
    input_time: time | None,
) -> datetime | None:
    if (
        input_date is None
        or input_time is None
    ):
        return None

    return datetime.combine(
        input_date,
        input_time,
    )


def _date_value(
    value: date | None,
) -> str | None:
    if value is None:
        return None

    return value.isoformat()


def _time_value(
    value: time | None,
) -> str | None:
    if value is None:
        return None

    return value.isoformat()


def _now_time() -> time:
    return (
        datetime.now()
        .time()
        .replace(
            second=0,
            microsecond=0,
        )
    )


def _calculate_power_kw(
    voltage_kv: float,
    current_a: float,
    power_factor: float,
) -> float:
    """
    P(kW) = √3 × V(kV) × I(A) × PF
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


def _duration_minutes(
    start_date: date | None,
    start_time: time | None,
    end_date: date | None,
    end_time: time | None,
) -> float | None:
    start_dt = _combine_datetime(
        start_date,
        start_time,
    )

    end_dt = _combine_datetime(
        end_date,
        end_time,
    )

    if (
        start_dt is None
        or end_dt is None
    ):
        return None

    if end_dt < start_dt:
        return None

    return (
        end_dt
        - start_dt
    ).total_seconds() / 60.0


def _calculate_ens_kwh(
    voltage_kv: float,
    current_a: float,
    power_factor: float,
    duration_minutes: float,
) -> float:
    if duration_minutes <= 0:
        return 0.0

    power_kw = (
        _calculate_power_kw(
            voltage_kv=voltage_kv,
            current_a=current_a,
            power_factor=power_factor,
        )
    )

    return (
        power_kw
        * duration_minutes
        / 60.0
    )


def _format_duration(
    value: float | None,
) -> str:
    if value is None:
        return "-"

    total_minutes = int(
        round(
            max(
                value,
                0.0,
            )
        )
    )

    if total_minutes < 60:
        return (
            f"{total_minutes} menit"
        )

    hours = (
        total_minutes // 60
    )

    minutes = (
        total_minutes % 60
    )

    if hours < 24:
        return (
            f"{hours} jam "
            f"{minutes} menit"
        )

    days = (
        hours // 24
    )

    hours = (
        hours % 24
    )

    return (
        f"{days} hari "
        f"{hours} jam "
        f"{minutes} menit"
    )


# ==========================================================
# CREATE FORM STATE VERSION
# ==========================================================

_CREATE_FORM_STATE_VERSION = 6


def _migrate_create_form_state() -> None:
    """
    Bersihkan state numerik lama yang pernah otomatis terisi 0,00.

    Hanya berjalan sekali per session ketika versi form berubah.
    """

    version_key = (
        "_input_create_form_state_version"
    )

    current_version = st.session_state.get(
        version_key
    )

    if current_version == _CREATE_FORM_STATE_VERSION:
        return

    prefixes = (
        "create_gangguan_",
        "create_manuver_",
        "input_event_",
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
            in prefixes
        ):
            st.session_state.pop(
                key,
                None,
            )

    st.session_state.pop(
        "input_event_type",
        None,
    )

    st.session_state[
        version_key
    ] = _CREATE_FORM_STATE_VERSION


# ==========================================================
# SESSION STATE
# ==========================================================


def _set_state_default(
    key: str,
    value: Any,
) -> None:
    if key not in st.session_state:
        st.session_state[
            key
        ] = value


def _prepare_create_state() -> None:
    today = date.today()
    now = _now_time()

    defaults: dict[str, Any] = {
        # ==================================================
        # GANGGUAN
        # ==================================================

        "create_gangguan_date":
            today,

        "create_gangguan_time":
            now,

        "create_gangguan_annunciator":
            "",

        "create_gangguan_indications":
            [],

        "create_gangguan_phases":
            [],

        "create_gangguan_cause":
            "",

        "create_gangguan_description":
            "",

        "create_gangguan_operator_name":
            "",

        "create_gangguan_dispatcher_up2d_name":
            "",

        "create_gangguan_supply_status":
            "BELUM",

        "create_gangguan_supply_date":
            today,

        "create_gangguan_supply_time":
            now,

        "create_gangguan_final_supply_normalized":
            False,

        "create_gangguan_final_supply_date":
            today,

        "create_gangguan_final_supply_time":
            now,

        "create_gangguan_pmt_recovery_status":
            "BELUM",

        "create_gangguan_pmt_recovery_date":
            today,

        "create_gangguan_pmt_recovery_time":
            now,

        "create_gangguan_pmt_counter_after":
            "",

        "create_gangguan_recovery_description":
            "",

        # ==================================================
        # MANUVER
        # ==================================================

        "create_manuver_date":
            today,

        "create_manuver_time":
            now,

        "create_manuver_pic":
            "",

        "create_manuver_cause":
            "",

        "create_manuver_description":
            "",

        "create_manuver_operator_name":
            "",

        "create_manuver_dispatcher_up2d_name":
            "",

        "create_manuver_supply_status":
            "BELUM",

        "create_manuver_supply_date":
            today,

        "create_manuver_supply_time":
            now,

        "create_manuver_final_supply_normalized":
            False,

        "create_manuver_final_supply_date":
            today,

        "create_manuver_final_supply_time":
            now,

        "create_manuver_pmt_recovery_status":
            "BELUM",

        "create_manuver_pmt_recovery_date":
            today,

        "create_manuver_pmt_recovery_time":
            now,

        "create_manuver_pmt_counter_after":
            "",

        "create_manuver_recovery_description":
            "",
    }

    for key, value in defaults.items():
        _set_state_default(
            key,
            value,
        )


# ==========================================================
# PREPARE EXISTING - GANGGUAN
# ==========================================================


def _prepare_gangguan_existing_state(
    *,
    event_id: str,
    row: EventRow,
    prefix: str,
) -> None:
    prepared_key = (
        f"prepared_{prefix}_event_id"
    )

    if (
        st.session_state.get(
            prepared_key
        )
        == event_id
    ):
        return

    today = date.today()
    now = _now_time()

    event_date = (
        _parse_date(
            row.get(
                "event_date"
            )
        )
        or today
    )

    event_time = (
        _parse_time(
            row.get(
                "event_time"
            )
        )
        or now
    )

    supply_date = (
        _parse_date(
            row.get(
                "supply_restored_date"
            )
        )
        or today
    )

    supply_time = (
        _parse_time(
            row.get(
                "supply_restored_time"
            )
        )
        or now
    )

    final_date = (
        _parse_date(
            row.get(
                "final_supply_normalization_date"
            )
        )
        or today
    )

    final_time = (
        _parse_time(
            row.get(
                "final_supply_normalization_time"
            )
        )
        or now
    )

    recovery_date = (
        _parse_date(
            row.get(
                "recovery_date"
            )
        )
        or today
    )

    recovery_time = (
        _parse_time(
            row.get(
                "recovery_time"
            )
        )
        or now
    )

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

    indication_codes = (
        _normalize_string_list(
            row.get(
                "indikasi_codes"
            )
        )
    )

    values: dict[str, Any] = {
        f"{prefix}_date":
            event_date,

        f"{prefix}_time":
            event_time,

        f"{prefix}_load_current_before_r":
            _three_phase_fallback(
                row=row,
                phase_field="load_current_before_r_a",
                legacy_field="load_current_before_a",
            ),

        f"{prefix}_load_current_before_s":
            _three_phase_fallback(
                row=row,
                phase_field="load_current_before_s_a",
                legacy_field="load_current_before_a",
            ),

        f"{prefix}_load_current_before_t":
            _three_phase_fallback(
                row=row,
                phase_field="load_current_before_t_a",
                legacy_field="load_current_before_a",
            ),

        f"{prefix}_voltage_before":
            (
                _optional_float(row.get("voltage_before_kv"))
            ),

        f"{prefix}_power_factor":
            0.85,

        f"{prefix}_annunciator":
            str(
                row.get(
                    "annunciator_code"
                )
                or ""
            ),

        f"{prefix}_indications":
            indication_codes,

        f"{prefix}_fault_current_r":
            (
                _optional_float(row.get("fault_current_r_a"))
            ),

        f"{prefix}_fault_current_s":
            (
                _optional_float(row.get("fault_current_s_a"))
            ),

        f"{prefix}_fault_current_t":
            (
                _optional_float(row.get("fault_current_t_a"))
            ),

        f"{prefix}_fault_current_n":
            (
                _optional_float(row.get("fault_current_n_a"))
            ),

        f"{prefix}_phases":
            phases,

        f"{prefix}_cause":
            str(
                row.get(
                    "cause_code"
                )
                or ""
            ),

        f"{prefix}_description":
            str(
                row.get(
                    "event_description"
                )
                or ""
            ),

        f"{prefix}_operator_name":
            str(
                row.get(
                    "operator_name"
                )
                or ""
            ),

        f"{prefix}_dispatcher_up2d_name":
            str(
                row.get(
                    "dispatcher_up2d_name"
                )
                or ""
            ),

        f"{prefix}_supply_status":
            str(
                row.get(
                    "supply_status_code"
                )
                or "BELUM"
            ),

        f"{prefix}_supply_date":
            supply_date,

        f"{prefix}_supply_time":
            supply_time,

        f"{prefix}_maneuvered_current_r":
            _three_phase_fallback(
                row=row,
                phase_field="maneuvered_current_r_a",
                legacy_field="maneuvered_current_a",
            ),

        f"{prefix}_maneuvered_current_s":
            _three_phase_fallback(
                row=row,
                phase_field="maneuvered_current_s_a",
                legacy_field="maneuvered_current_a",
            ),

        f"{prefix}_maneuvered_current_t":
            _three_phase_fallback(
                row=row,
                phase_field="maneuvered_current_t_a",
                legacy_field="maneuvered_current_a",
            ),

        f"{prefix}_final_supply_normalized":
            bool(
                row.get(
                    "final_supply_normalized"
                )
            ),

        f"{prefix}_final_supply_date":
            final_date,

        f"{prefix}_final_supply_time":
            final_time,

        f"{prefix}_pmt_recovery_status":
            str(
                row.get(
                    "recovery_status_code"
                )
                or "BELUM"
            ),

        f"{prefix}_pmt_recovery_date":
            recovery_date,

        f"{prefix}_pmt_recovery_time":
            recovery_time,

        f"{prefix}_pmt_counter_after":
            _optional_int_text(
                row.get(
                    "pmt_counter_after"
                )
            ),

        f"{prefix}_load_current_after_r":
            _three_phase_fallback(
                row=row,
                phase_field="load_current_after_r_a",
                legacy_field="load_current_after_a",
            ),

        f"{prefix}_load_current_after_s":
            _three_phase_fallback(
                row=row,
                phase_field="load_current_after_s_a",
                legacy_field="load_current_after_a",
            ),

        f"{prefix}_load_current_after_t":
            _three_phase_fallback(
                row=row,
                phase_field="load_current_after_t_a",
                legacy_field="load_current_after_a",
            ),

        f"{prefix}_voltage_after":
            (
                _optional_float(row.get("voltage_after_kv"))
            ),

        f"{prefix}_recovery_description":
            str(
                row.get(
                    "recovery_description"
                )
                or ""
            ),
    }

    for key, value in values.items():
        st.session_state[
            key
        ] = value

    st.session_state[
        prepared_key
    ] = event_id


# ==========================================================
# PREPARE EXISTING - MANUVER
# ==========================================================


def _prepare_manuver_existing_state(
    *,
    event_id: str,
    row: EventRow,
    prefix: str,
) -> None:
    prepared_key = (
        f"prepared_{prefix}_event_id"
    )

    if (
        st.session_state.get(
            prepared_key
        )
        == event_id
    ):
        return

    today = date.today()
    now = _now_time()

    values: dict[str, Any] = {
        f"{prefix}_date":
            (
                _parse_date(
                    row.get(
                        "event_date"
                    )
                )
                or today
            ),

        f"{prefix}_time":
            (
                _parse_time(
                    row.get(
                        "event_time"
                    )
                )
                or now
            ),

        f"{prefix}_load_current_before_r":
            _three_phase_fallback(
                row=row,
                phase_field="load_current_before_r_a",
                legacy_field="load_current_before_a",
            ),

        f"{prefix}_load_current_before_s":
            _three_phase_fallback(
                row=row,
                phase_field="load_current_before_s_a",
                legacy_field="load_current_before_a",
            ),

        f"{prefix}_load_current_before_t":
            _three_phase_fallback(
                row=row,
                phase_field="load_current_before_t_a",
                legacy_field="load_current_before_a",
            ),

        f"{prefix}_voltage_before":
            (
                _optional_float(row.get("voltage_before_kv"))
            ),

        f"{prefix}_power_factor":
            0.85,

        f"{prefix}_pic":
            str(
                row.get(
                    "pic_code"
                )
                or ""
            ),

        f"{prefix}_cause":
            str(
                row.get(
                    "cause_code"
                )
                or ""
            ),

        f"{prefix}_description":
            str(
                row.get(
                    "event_description"
                )
                or ""
            ),

        f"{prefix}_operator_name":
            str(
                row.get(
                    "operator_name"
                )
                or ""
            ),

        f"{prefix}_dispatcher_up2d_name":
            str(
                row.get(
                    "dispatcher_up2d_name"
                )
                or ""
            ),

        f"{prefix}_supply_status":
            str(
                row.get(
                    "supply_status_code"
                )
                or "BELUM"
            ),

        f"{prefix}_supply_date":
            (
                _parse_date(
                    row.get(
                        "supply_restored_date"
                    )
                )
                or today
            ),

        f"{prefix}_supply_time":
            (
                _parse_time(
                    row.get(
                        "supply_restored_time"
                    )
                )
                or now
            ),

        f"{prefix}_maneuvered_current_r":
            _three_phase_fallback(
                row=row,
                phase_field="maneuvered_current_r_a",
                legacy_field="maneuvered_current_a",
            ),

        f"{prefix}_maneuvered_current_s":
            _three_phase_fallback(
                row=row,
                phase_field="maneuvered_current_s_a",
                legacy_field="maneuvered_current_a",
            ),

        f"{prefix}_maneuvered_current_t":
            _three_phase_fallback(
                row=row,
                phase_field="maneuvered_current_t_a",
                legacy_field="maneuvered_current_a",
            ),

        f"{prefix}_final_supply_normalized":
            bool(
                row.get(
                    "final_supply_normalized"
                )
            ),

        f"{prefix}_final_supply_date":
            (
                _parse_date(
                    row.get(
                        "final_supply_normalization_date"
                    )
                )
                or today
            ),

        f"{prefix}_final_supply_time":
            (
                _parse_time(
                    row.get(
                        "final_supply_normalization_time"
                    )
                )
                or now
            ),

        f"{prefix}_pmt_recovery_status":
            str(
                row.get(
                    "recovery_status_code"
                )
                or "BELUM"
            ),

        f"{prefix}_pmt_recovery_date":
            (
                _parse_date(
                    row.get(
                        "recovery_date"
                    )
                )
                or today
            ),

        f"{prefix}_pmt_recovery_time":
            (
                _parse_time(
                    row.get(
                        "recovery_time"
                    )
                )
                or now
            ),

        f"{prefix}_pmt_counter_after":
            _optional_int_text(
                row.get(
                    "pmt_counter_after"
                )
            ),

        f"{prefix}_load_current_after_r":
            _three_phase_fallback(
                row=row,
                phase_field="load_current_after_r_a",
                legacy_field="load_current_after_a",
            ),

        f"{prefix}_load_current_after_s":
            _three_phase_fallback(
                row=row,
                phase_field="load_current_after_s_a",
                legacy_field="load_current_after_a",
            ),

        f"{prefix}_load_current_after_t":
            _three_phase_fallback(
                row=row,
                phase_field="load_current_after_t_a",
                legacy_field="load_current_after_a",
            ),

        f"{prefix}_voltage_after":
            (
                _optional_float(row.get("voltage_after_kv"))
            ),

        f"{prefix}_recovery_description":
            str(
                row.get(
                    "recovery_description"
                )
                or ""
            ),
    }

    for key, value in values.items():
        st.session_state[
            key
        ] = value

    st.session_state[
        prepared_key
    ] = event_id


def _clear_edit_mode() -> None:
    st.session_state.pop(
        "input_mode",
        None,
    )

    st.session_state.pop(
        "edit_event_id",
        None,
    )

    st.session_state.pop(
        "edit_event_source",
        None,
    )

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


def _return_to_source() -> None:
    source = str(
        st.session_state.get(
            "edit_event_source"
        )
        or ""
    )

    _clear_edit_mode()

    if (
        source
        == "RIWAYAT_OPERASI"
    ):
        st.switch_page(
            "pages/riwayat_kejadian.py"
        )

    else:
        st.switch_page(
            "pages/gangguan_aktif.py"
        )


# ==========================================================
# INDICATION UPDATE
# ==========================================================


def _replace_event_indications(
    *,
    event_id: str,
    indication_codes: list[str],
) -> None:
    supabase = (
        get_supabase_client()
    )

    (
        supabase
        .table(
            "trx_kejadian_indikasi"
        )
        .delete()
        .eq(
            "event_id",
            event_id,
        )
        .execute()
    )

    clean_codes = [
        str(code).strip()
        for code in indication_codes
        if str(code).strip()
    ]

    if not clean_codes:
        return

    rows = [
        {
            "event_id":
                event_id,

            "indikasi_code":
                code,
        }
        for code
        in clean_codes
    ]

    (
        supabase
        .table(
            "trx_kejadian_indikasi"
        )
        .insert(
            rows
        )
        .execute()
    )


# ==========================================================
# SUPPLY / ENS PREVIEW
# ==========================================================


def _calculate_supply_metrics(
    *,
    event_date: date,
    event_time: time,
    supply_status: str,
    supply_date: date | None,
    supply_time: time | None,
    final_supply_normalized: bool,
    final_supply_date: date | None,
    final_supply_time: time | None,
    pmt_recovery_status: str,
    pmt_recovery_date: date | None,
    pmt_recovery_time: time | None,
    voltage_kv: float,
    load_current_before_r: float | None,
    load_current_before_s: float | None,
    load_current_before_t: float | None,
    load_current_before: float,
    power_factor: float,
    maneuvered_current_r: float | None,
    maneuvered_current_s: float | None,
    maneuvered_current_t: float | None,
) -> dict[str, float | None]:
    """
    Preview kalkulasi pemadaman.

    Nilai final tetap dihitung database. Untuk Manuver Sebagian,
    preview memakai arus termanuver dan sisa beban per phasa.
    """

    result: dict[
        str,
        float | None
    ] = {
        "customer_outage_min": None,
        "pmt_duration_min": None,
        "ens_kwh": None,
        "remaining_current": None,
        "remaining_current_r": None,
        "remaining_current_s": None,
        "remaining_current_t": None,
    }

    if (
        pmt_recovery_status
        != "BELUM"
    ):
        result[
            "pmt_duration_min"
        ] = _duration_minutes(
            event_date,
            event_time,
            pmt_recovery_date,
            pmt_recovery_time,
        )

    if supply_status == "BELUM":
        result["remaining_current_r"] = load_current_before_r
        result["remaining_current_s"] = load_current_before_s
        result["remaining_current_t"] = load_current_before_t
        result["remaining_current"] = (
            _three_phase_average(
                load_current_before_r,
                load_current_before_s,
                load_current_before_t,
            )
            or load_current_before
        )
        return result

    first_supply_duration = _duration_minutes(
        event_date,
        event_time,
        supply_date,
        supply_time,
    )

    if first_supply_duration is None:
        return result

    if supply_status in {
        "FEEDER_ASAL",
        "MANUVER_PENUH",
    }:
        result["customer_outage_min"] = first_supply_duration
        result["remaining_current"] = 0.0
        result["remaining_current_r"] = 0.0
        result["remaining_current_s"] = 0.0
        result["remaining_current_t"] = 0.0

        result["ens_kwh"] = _calculate_ens_kwh(
            voltage_kv=voltage_kv,
            current_a=load_current_before,
            power_factor=power_factor,
            duration_minutes=first_supply_duration,
        )
        return result

    if supply_status == "MANUVER_SEBAGIAN":
        before_r = _optional_float(load_current_before_r)
        before_s = _optional_float(load_current_before_s)
        before_t = _optional_float(load_current_before_t)

        maneuver_r = _optional_float(maneuvered_current_r)
        maneuver_s = _optional_float(maneuvered_current_s)
        maneuver_t = _optional_float(maneuvered_current_t)

        if (
            before_r is None
            or before_s is None
            or before_t is None
            or maneuver_r is None
            or maneuver_s is None
            or maneuver_t is None
        ):
            return result

        maneuver_r = max(0.0, min(maneuver_r, before_r))
        maneuver_s = max(0.0, min(maneuver_s, before_s))
        maneuver_t = max(0.0, min(maneuver_t, before_t))

        remaining_r = max(before_r - maneuver_r, 0.0)
        remaining_s = max(before_s - maneuver_s, 0.0)
        remaining_t = max(before_t - maneuver_t, 0.0)

        remaining_avg = (
            _three_phase_average(
                remaining_r,
                remaining_s,
                remaining_t,
            )
            or 0.0
        )

        result["remaining_current_r"] = remaining_r
        result["remaining_current_s"] = remaining_s
        result["remaining_current_t"] = remaining_t
        result["remaining_current"] = remaining_avg

        ens_interval_1 = _calculate_ens_kwh(
            voltage_kv=voltage_kv,
            current_a=load_current_before,
            power_factor=power_factor,
            duration_minutes=first_supply_duration,
        )

        if not final_supply_normalized:
            return result

        final_duration = _duration_minutes(
            event_date,
            event_time,
            final_supply_date,
            final_supply_time,
        )

        if (
            final_duration is None
            or final_duration < first_supply_duration
        ):
            return result

        remaining_duration = (
            final_duration
            - first_supply_duration
        )

        ens_interval_2 = _calculate_ens_kwh(
            voltage_kv=voltage_kv,
            current_a=remaining_avg,
            power_factor=power_factor,
            duration_minutes=remaining_duration,
        )

        result["customer_outage_min"] = final_duration
        result["ens_kwh"] = (
            ens_interval_1
            + ens_interval_2
        )

    return result

# ==========================================================
# SUPPLY / NORMALIZATION COMPONENT
# ==========================================================


def _render_supply_restoration(
    *,
    prefix: str,
    event_date: date,
    event_time: time,
    voltage_before: float,
    load_current_before_r: float | None,
    load_current_before_s: float | None,
    load_current_before_t: float | None,
    load_current_before: float,
    power_factor: float,
    enabled: bool,
) -> dict[str, Any]:
    supply_status_key = (
        f"{prefix}_supply_status"
    )

    supply_date_key = (
        f"{prefix}_supply_date"
    )

    supply_time_key = (
        f"{prefix}_supply_time"
    )

    maneuvered_current_r_key = (
        f"{prefix}_maneuvered_current_r"
    )

    maneuvered_current_s_key = (
        f"{prefix}_maneuvered_current_s"
    )

    maneuvered_current_t_key = (
        f"{prefix}_maneuvered_current_t"
    )

    final_normalized_key = (
        f"{prefix}_final_supply_normalized"
    )

    final_date_key = (
        f"{prefix}_final_supply_date"
    )

    final_time_key = (
        f"{prefix}_final_supply_time"
    )

    pmt_status_key = (
        f"{prefix}_pmt_recovery_status"
    )

    pmt_date_key = (
        f"{prefix}_pmt_recovery_date"
    )

    pmt_time_key = (
        f"{prefix}_pmt_recovery_time"
    )

    pmt_counter_after_key = (
        f"{prefix}_pmt_counter_after"
    )

    current_after_r_key = (
        f"{prefix}_load_current_after_r"
    )

    current_after_s_key = (
        f"{prefix}_load_current_after_s"
    )

    current_after_t_key = (
        f"{prefix}_load_current_after_t"
    )

    voltage_after_key = (
        f"{prefix}_voltage_after"
    )

    # ======================================================
    # AUTO SYNCHRONIZATION
    # ======================================================

    stored_pmt_status = str(
        st.session_state.get(
            pmt_status_key,
            "BELUM",
        )
        or "BELUM"
    ).strip()

    stored_supply_status = str(
        st.session_state.get(
            supply_status_key,
            "BELUM",
        )
        or "BELUM"
    ).strip()

    stored_pmt_date = (
        st.session_state.get(
            pmt_date_key
        )
    )

    stored_pmt_time = (
        st.session_state.get(
            pmt_time_key
        )
    )

    if (
        stored_pmt_status
        == "MASUK"
    ):
        # --------------------------------------------------
        # BELUM TERSUPLAI
        # PMT masuk langsung memulihkan feeder asal.
        # --------------------------------------------------

        if (
            stored_supply_status
            == "BELUM"
        ):
            st.session_state[
                supply_status_key
            ] = "FEEDER_ASAL"

            if isinstance(
                stored_pmt_date,
                date,
            ):
                st.session_state[
                    supply_date_key
                ] = stored_pmt_date

            if isinstance(
                stored_pmt_time,
                time,
            ):
                st.session_state[
                    supply_time_key
                ] = stored_pmt_time

            st.session_state[
                final_normalized_key
            ] = True

        # --------------------------------------------------
        # FEEDER ASAL
        # Sinkronkan waktu dengan operasi PMT.
        # --------------------------------------------------

        elif (
            stored_supply_status
            == "FEEDER_ASAL"
        ):
            if isinstance(
                stored_pmt_date,
                date,
            ):
                st.session_state[
                    supply_date_key
                ] = stored_pmt_date

            if isinstance(
                stored_pmt_time,
                time,
            ):
                st.session_state[
                    supply_time_key
                ] = stored_pmt_time

            st.session_state[
                final_normalized_key
            ] = True

        # --------------------------------------------------
        # MANUVER SEBAGIAN
        # Jangan hapus histori manuver.
        # PMT masuk dapat menjadi normalisasi sisa beban.
        # --------------------------------------------------

        elif (
            stored_supply_status
            == "MANUVER_SEBAGIAN"
            and not bool(
                st.session_state.get(
                    final_normalized_key,
                    False,
                )
            )
        ):
            st.session_state[
                final_normalized_key
            ] = True

            if isinstance(
                stored_pmt_date,
                date,
            ):
                st.session_state[
                    final_date_key
                ] = stored_pmt_date

            if isinstance(
                stored_pmt_time,
                time,
            ):
                st.session_state[
                    final_time_key
                ] = stored_pmt_time

        # MANUVER_PENUH tetap dipertahankan.
        # PMT masuk hanya menjadi normalisasi feeder asal.

    # ======================================================
    # SUPPLY
    # ======================================================

    supply_labels: dict[
        str,
        str
    ] = {
        "BELUM":
            "Belum Tersuplai",

        "FEEDER_ASAL":
            "Tersuplai dari Feeder Asal",

        "MANUVER_PENUH":
            "Manuver Seluruh Beban",

        "MANUVER_SEBAGIAN":
            "Manuver Sebagian Beban",
    }

    supply_options = [
        "BELUM",
        "FEEDER_ASAL",
        "MANUVER_PENUH",
        "MANUVER_SEBAGIAN",
    ]

    def format_supply(
        value: str,
    ) -> str:
        return (
            supply_labels.get(
                value,
                value,
            )
        )

    with st.container(
        border=True
    ):
        st.markdown(
            "#### Pemulihan Beban"
        )

        st.caption(
            "Catat kapan beban pelanggan kembali tersuplai. "
            "Jika PMT berhasil masuk saat beban masih padam, "
            "status otomatis menjadi Tersuplai dari Feeder Asal."
        )

        current_state_supply = str(
            st.session_state.get(
                supply_status_key,
                "BELUM",
            )
            or "BELUM"
        )

        supply_locked_by_pmt = (
            stored_pmt_status
            == "MASUK"
            and current_state_supply
            == "FEEDER_ASAL"
        )

        col_status, col_info = (
            st.columns(
                [1.6, 1]
            )
        )

        with col_status:
            supply_status_raw = (
                st.selectbox(
                    "Status Suplai Beban",
                    options=(
                        supply_options
                    ),
                    format_func=(
                        format_supply
                    ),
                    key=(
                        supply_status_key
                    ),
                    disabled=(
                        not enabled
                        or supply_locked_by_pmt
                    ),
                )
            )

        supply_status = str(
            supply_status_raw
            or "BELUM"
        )

        with col_info:
            if (
                supply_locked_by_pmt
            ):
                st.caption(
                    "Otomatis dari Status PMT"
                )

                st.write(
                    "**Feeder Asal Tersuplai**"
                )

        has_supply = (
            supply_status
            != "BELUM"
        )

        col_date, col_time = (
            st.columns(2)
        )

        with col_date:
            supply_date = (
                st.date_input(
                    "Tanggal Mulai Tersuplai",
                    key=(
                        supply_date_key
                    ),
                    disabled=(
                        not enabled
                        or not has_supply
                        or supply_locked_by_pmt
                    ),
                )
            )

        with col_time:
            supply_time = (
                st.time_input(
                    "Waktu Mulai Tersuplai",
                    key=(
                        supply_time_key
                    ),
                    disabled=(
                        not enabled
                        or not has_supply
                        or supply_locked_by_pmt
                    ),
                )
            )

        maneuvered_current_r: float | None = None
        maneuvered_current_s: float | None = None
        maneuvered_current_t: float | None = None
        maneuvered_current: float | None = None

        if (
            supply_status
            == "MANUVER_PENUH"
        ):
            maneuvered_current_r = (
                _optional_float(
                    load_current_before_r
                )
            )

            maneuvered_current_s = (
                _optional_float(
                    load_current_before_s
                )
            )

            maneuvered_current_t = (
                _optional_float(
                    load_current_before_t
                )
            )

            maneuvered_current = (
                _three_phase_average(
                    maneuvered_current_r,
                    maneuvered_current_s,
                    maneuvered_current_t,
                )
            )

            st.caption(
                "Seluruh beban berhasil dialihkan melalui manuver."
            )

            col_r, col_s, col_t = st.columns(3)

            with col_r:
                st.metric(
                    "Termanuver R",
                    (
                        f"{maneuvered_current_r:,.2f} A"
                        if maneuvered_current_r is not None
                        else "-"
                    ),
                )

            with col_s:
                st.metric(
                    "Termanuver S",
                    (
                        f"{maneuvered_current_s:,.2f} A"
                        if maneuvered_current_s is not None
                        else "-"
                    ),
                )

            with col_t:
                st.metric(
                    "Termanuver T",
                    (
                        f"{maneuvered_current_t:,.2f} A"
                        if maneuvered_current_t is not None
                        else "-"
                    ),
                )

        elif (
            supply_status
            == "MANUVER_SEBAGIAN"
        ):
            st.caption(
                "Beban Berhasil Dimanuver"
            )

            col_mr, col_ms, col_mt = st.columns(3)

            with col_mr:
                maneuvered_current_r = (
                    _numeric_text_input_optional(
                        "Phasa R (A)",
                        key=maneuvered_current_r_key,
                        disabled=not enabled,
                        placeholder="R",
                        help_text=(
                            "Arus beban phasa R yang berhasil "
                            "dialihkan melalui manuver."
                        ),
                    )
                )

            with col_ms:
                maneuvered_current_s = (
                    _numeric_text_input_optional(
                        "Phasa S (A)",
                        key=maneuvered_current_s_key,
                        disabled=not enabled,
                        placeholder="S",
                        help_text=(
                            "Arus beban phasa S yang berhasil "
                            "dialihkan melalui manuver."
                        ),
                    )
                )

            with col_mt:
                maneuvered_current_t = (
                    _numeric_text_input_optional(
                        "Phasa T (A)",
                        key=maneuvered_current_t_key,
                        disabled=not enabled,
                        placeholder="T",
                        help_text=(
                            "Arus beban phasa T yang berhasil "
                            "dialihkan melalui manuver."
                        ),
                    )
                )

            maneuvered_current = (
                _three_phase_average(
                    maneuvered_current_r,
                    maneuvered_current_s,
                    maneuvered_current_t,
                )
            )

            remaining_current_r = (
                max(
                    _safe_float(load_current_before_r)
                    - _safe_float(maneuvered_current_r),
                    0.0,
                )
                if (
                    load_current_before_r is not None
                    and maneuvered_current_r is not None
                )
                else None
            )

            remaining_current_s = (
                max(
                    _safe_float(load_current_before_s)
                    - _safe_float(maneuvered_current_s),
                    0.0,
                )
                if (
                    load_current_before_s is not None
                    and maneuvered_current_s is not None
                )
                else None
            )

            remaining_current_t = (
                max(
                    _safe_float(load_current_before_t)
                    - _safe_float(maneuvered_current_t),
                    0.0,
                )
                if (
                    load_current_before_t is not None
                    and maneuvered_current_t is not None
                )
                else None
            )

            st.caption(
                "Sisa Beban Belum Tersuplai — dihitung otomatis"
            )

            col_rr, col_rs, col_rt = st.columns(3)

            with col_rr:
                st.metric(
                    "Sisa R",
                    (
                        f"{remaining_current_r:,.2f} A"
                        if remaining_current_r is not None
                        else "-"
                    ),
                )

            with col_rs:
                st.metric(
                    "Sisa S",
                    (
                        f"{remaining_current_s:,.2f} A"
                        if remaining_current_s is not None
                        else "-"
                    ),
                )

            with col_rt:
                st.metric(
                    "Sisa T",
                    (
                        f"{remaining_current_t:,.2f} A"
                        if remaining_current_t is not None
                        else "-"
                    ),
                )

            remaining_average = (
                _three_phase_average(
                    remaining_current_r,
                    remaining_current_s,
                    remaining_current_t,
                )
            )

            if maneuvered_current is not None:
                caption = (
                    "Rata-rata termanuver: "
                    f"**{maneuvered_current:,.2f} A**"
                )

                if remaining_average is not None:
                    caption += (
                        " · Rata-rata sisa: "
                        f"**{remaining_average:,.2f} A**"
                    )

                st.caption(
                    caption
                )

        # ==================================================
        # FINAL SUPPLY NORMALIZATION
        # ==================================================

        final_supply_normalized = (
            False
        )

        final_supply_date: (
            date | None
        ) = None

        final_supply_time: (
            time | None
        ) = None

        if (
            supply_status
            == "MANUVER_SEBAGIAN"
        ):
            st.markdown(
                "##### Normalisasi Sisa Beban"
            )

            final_supply_normalized = (
                st.checkbox(
                    "Seluruh sisa beban sudah kembali tersuplai",
                    key=(
                        final_normalized_key
                    ),
                    disabled=(
                        not enabled
                    ),
                )
            )

            col_final_date, col_final_time = (
                st.columns(2)
            )

            with col_final_date:
                final_supply_date = (
                    st.date_input(
                        "Tanggal Seluruh Beban Tersuplai",
                        key=(
                            final_date_key
                        ),
                        disabled=(
                            not enabled
                            or not final_supply_normalized
                        ),
                    )
                )

            with col_final_time:
                final_supply_time = (
                    st.time_input(
                        "Waktu Seluruh Beban Tersuplai",
                        key=(
                            final_time_key
                        ),
                        disabled=(
                            not enabled
                            or not final_supply_normalized
                        ),
                    )
                )

        elif supply_status in {
            "FEEDER_ASAL",
            "MANUVER_PENUH",
        }:
            final_supply_normalized = (
                True
            )

    # ======================================================
    # PMT NORMALIZATION
    # ======================================================

    pmt_labels = {
        "BELUM":
            "Belum Normal",

        "MASUK":
            "PMT Berhasil Masuk",

        "MASUK_TRIP":
            "PMT Masuk - Trip Kembali",
    }

    pmt_options = [
        "BELUM",
        "MASUK",
        "MASUK_TRIP",
    ]

    def format_pmt(
        value: str,
    ) -> str:
        return (
            pmt_labels.get(
                value,
                value,
            )
        )

    with st.container(
        border=True
    ):
        st.markdown(
            "#### Normalisasi PMT"
        )

        st.caption(
            "Catat hasil operasi PMT feeder asal "
            "setelah pemulihan / normalisasi."
        )

        col_status, col_info = (
            st.columns(
                [1.6, 1]
            )
        )

        with col_status:
            pmt_status_raw = (
                st.selectbox(
                    "Status PMT",
                    options=(
                        pmt_options
                    ),
                    format_func=(
                        format_pmt
                    ),
                    key=(
                        pmt_status_key
                    ),
                    disabled=(
                        not enabled
                    ),
                )
            )

        pmt_status = str(
            pmt_status_raw
            or "BELUM"
        )

        has_pmt_recovery = (
            pmt_status
            != "BELUM"
        )

        with col_info:
            if (
                pmt_status
                == "MASUK"
            ):
                st.caption(
                    "Kondisi Akhir"
                )

                st.write(
                    "**PMT Normal**"
                )

            elif (
                pmt_status
                == "MASUK_TRIP"
            ):
                st.caption(
                    "Kondisi Akhir"
                )

                st.write(
                    "**PMT Trip Kembali**"
                )

        col_date, col_time = (
            st.columns(2)
        )

        with col_date:
            pmt_recovery_date = (
                st.date_input(
                    "Tanggal Operasi PMT",
                    key=(
                        pmt_date_key
                    ),
                    disabled=(
                        not enabled
                        or not has_pmt_recovery
                    ),
                )
            )

        with col_time:
            pmt_recovery_time = (
                st.time_input(
                    "Waktu Operasi PMT",
                    key=(
                        pmt_time_key
                    ),
                    disabled=(
                        not enabled
                        or not has_pmt_recovery
                    ),
                )
            )

        # ==================================================
        # PARAMETER AFTER OPERATION
        # ==================================================

        st.caption(
            "Arus Beban Setelah Operasi"
        )

        (
            col_after_r,
            col_after_s,
            col_after_t,
            col_voltage,
        ) = st.columns(
            [1, 1, 1, 1.15]
        )

        with col_after_r:
            load_current_after_r = (
                _numeric_text_input_optional(
                    "Phasa R (A)",
                    key=current_after_r_key,
                    disabled=(
                        not enabled
                        or not has_pmt_recovery
                    ),
                    placeholder="R",
                )
            )

        with col_after_s:
            load_current_after_s = (
                _numeric_text_input_optional(
                    "Phasa S (A)",
                    key=current_after_s_key,
                    disabled=(
                        not enabled
                        or not has_pmt_recovery
                    ),
                    placeholder="S",
                )
            )

        with col_after_t:
            load_current_after_t = (
                _numeric_text_input_optional(
                    "Phasa T (A)",
                    key=current_after_t_key,
                    disabled=(
                        not enabled
                        or not has_pmt_recovery
                    ),
                    placeholder="T",
                )
            )

        with col_voltage:
            voltage_after = (
                _numeric_text_input_optional(
                    "Tegangan Setelah (kV)",
                    key=voltage_after_key,
                    disabled=(
                        not enabled
                        or not has_pmt_recovery
                    ),
                    placeholder="Masukkan tegangan",
                )
            )

        load_current_after_average = (
            _three_phase_average(
                load_current_after_r,
                load_current_after_s,
                load_current_after_t,
            )
            if has_pmt_recovery
            else None
        )

        if load_current_after_average is not None:
            st.caption(
                "Arus rata-rata setelah operasi: "
                f"**{load_current_after_average:,.2f} A**"
            )

        # ==================================================
        # PMT COUNTER
        # ==================================================

        pmt_counter_after_raw = (
            st.text_input(
                "Counter PMT Setelah Operasi",
                key=(
                    pmt_counter_after_key
                ),
                placeholder=(
                    "Contoh: 1254"
                ),
                disabled=(
                    not enabled
                    or not has_pmt_recovery
                ),
                help=(
                    "Masukkan nilai counter PMT setelah "
                    "operasi pemulihan / percobaan masuk. "
                    "Biarkan kosong jika belum diketahui."
                ),
            )
        )

        if (
            pmt_status
            == "MASUK_TRIP"
        ):
            st.caption(
                "PMT sempat masuk tetapi trip kembali. "
                "Counter tetap dapat dicatat setelah percobaan operasi."
            )

    # ======================================================
    # PARSE PMT COUNTER
    # ======================================================

    pmt_counter_after: (
        int | None
    ) = None

    counter_error: (
        str | None
    ) = None

    if has_pmt_recovery:
        (
            pmt_counter_after,
            counter_error,
        ) = (
            _parse_optional_nonnegative_int(
                pmt_counter_after_raw
            )
        )

    # ======================================================
    # EFFECTIVE VALUES
    # ======================================================

    effective_supply_status = (
        supply_status
    )

    effective_supply_date: (
        date | None
    ) = (
        supply_date
        if has_supply
        else None
    )

    effective_supply_time: (
        time | None
    ) = (
        supply_time
        if has_supply
        else None
    )

    effective_final_normalized = (
        final_supply_normalized
    )

    effective_final_date = (
        final_supply_date
    )

    effective_final_time = (
        final_supply_time
    )

    effective_maneuvered_current_r: (
        float | None
    ) = (
        _optional_float(
            maneuvered_current_r
        )
        if supply_status in {
            "MANUVER_PENUH",
            "MANUVER_SEBAGIAN",
        }
        else None
    )

    effective_maneuvered_current_s: (
        float | None
    ) = (
        _optional_float(
            maneuvered_current_s
        )
        if supply_status in {
            "MANUVER_PENUH",
            "MANUVER_SEBAGIAN",
        }
        else None
    )

    effective_maneuvered_current_t: (
        float | None
    ) = (
        _optional_float(
            maneuvered_current_t
        )
        if supply_status in {
            "MANUVER_PENUH",
            "MANUVER_SEBAGIAN",
        }
        else None
    )

    effective_maneuvered_current: (
        float | None
    ) = (
        _three_phase_average(
            effective_maneuvered_current_r,
            effective_maneuvered_current_s,
            effective_maneuvered_current_t,
        )
    )

    # ======================================================
    # PMT MASUK
    # ======================================================

    if (
        pmt_status
        == "MASUK"
    ):
        # --------------------------------------------------
        # BELUM -> FEEDER_ASAL
        # --------------------------------------------------

        if (
            effective_supply_status
            == "BELUM"
        ):
            effective_supply_status = (
                "FEEDER_ASAL"
            )

            effective_supply_date = (
                pmt_recovery_date
            )

            effective_supply_time = (
                pmt_recovery_time
            )

            effective_final_normalized = (
                True
            )

            effective_final_date = (
                None
            )

            effective_final_time = (
                None
            )

            effective_maneuvered_current_r = None
            effective_maneuvered_current_s = None
            effective_maneuvered_current_t = None
            effective_maneuvered_current = None

        # --------------------------------------------------
        # FEEDER_ASAL
        # --------------------------------------------------

        elif (
            effective_supply_status
            == "FEEDER_ASAL"
        ):
            effective_supply_date = (
                pmt_recovery_date
            )

            effective_supply_time = (
                pmt_recovery_time
            )

            effective_final_normalized = (
                True
            )

            effective_final_date = (
                None
            )

            effective_final_time = (
                None
            )

            effective_maneuvered_current_r = None
            effective_maneuvered_current_s = None
            effective_maneuvered_current_t = None
            effective_maneuvered_current = None

        # --------------------------------------------------
        # MANUVER SEBAGIAN
        # PMT masuk menjadi normalisasi sisa beban
        # jika belum dinormalisasi.
        # --------------------------------------------------

        elif (
            effective_supply_status
            == "MANUVER_SEBAGIAN"
            and not effective_final_normalized
        ):
            effective_final_normalized = (
                True
            )

            effective_final_date = (
                pmt_recovery_date
            )

            effective_final_time = (
                pmt_recovery_time
            )

        # MANUVER_PENUH tetap dipertahankan.

    # ======================================================
    # PREVIEW
    # ======================================================

    metrics = (
        _calculate_supply_metrics(
            event_date=event_date,
            event_time=event_time,
            supply_status=(
                effective_supply_status
            ),
            supply_date=(
                effective_supply_date
            ),
            supply_time=(
                effective_supply_time
            ),
            final_supply_normalized=(
                effective_final_normalized
            ),
            final_supply_date=(
                effective_final_date
            ),
            final_supply_time=(
                effective_final_time
            ),
            pmt_recovery_status=(
                pmt_status
            ),
            pmt_recovery_date=(
                pmt_recovery_date
                if has_pmt_recovery
                else None
            ),
            pmt_recovery_time=(
                pmt_recovery_time
                if has_pmt_recovery
                else None
            ),
            voltage_kv=(
                voltage_before
            ),
            load_current_before_r=(
                load_current_before_r
            ),
            load_current_before_s=(
                load_current_before_s
            ),
            load_current_before_t=(
                load_current_before_t
            ),
            load_current_before=(
                load_current_before
            ),
            power_factor=(
                power_factor
            ),
            maneuvered_current_r=(
                effective_maneuvered_current_r
            ),
            maneuvered_current_s=(
                effective_maneuvered_current_s
            ),
            maneuvered_current_t=(
                effective_maneuvered_current_t
            ),
        )
    )

    with st.container(
        border=True
    ):
        st.markdown(
            "#### Kalkulasi Pemadaman"
        )

        outage_minutes = (
            metrics.get(
                "customer_outage_min"
            )
        )

        pmt_minutes = (
            metrics.get(
                "pmt_duration_min"
            )
        )

        ens_kwh = (
            metrics.get(
                "ens_kwh"
            )
        )

        metric_a, metric_b, metric_c = (
            st.columns(3)
        )

        with metric_a:
            st.metric(
                "Durasi Beban Tidak Tersuplai",
                _format_duration(
                    outage_minutes
                ),
            )

        with metric_b:
            st.metric(
                "Durasi Kondisi PMT",
                _format_duration(
                    pmt_minutes
                ),
            )

        with metric_c:
            st.metric(
                "ENS",
                (
                    f"{ens_kwh:,.2f} kWh"
                    if ens_kwh
                    is not None
                    else "-"
                ),
            )

        if (
            pmt_counter_after
            is not None
        ):
            st.caption(
                "Counter PMT setelah operasi: "
                f"**{pmt_counter_after:,}**"
            )

        st.caption(
            "Nilai Durasi dan ENS di atas merupakan preview. "
            "Nilai final dihitung kembali oleh database "
            "saat data disimpan."
        )

    return {
        "supply_status_code":
            effective_supply_status,

        "supply_restored_date":
            effective_supply_date,

        "supply_restored_time":
            effective_supply_time,

        "maneuvered_current_r_a":
            effective_maneuvered_current_r,

        "maneuvered_current_s_a":
            effective_maneuvered_current_s,

        "maneuvered_current_t_a":
            effective_maneuvered_current_t,

        # Legacy average untuk kompatibilitas.
        "maneuvered_current_a":
            effective_maneuvered_current,

        "remaining_current_r_a":
            metrics.get(
                "remaining_current_r"
            ),

        "remaining_current_s_a":
            metrics.get(
                "remaining_current_s"
            ),

        "remaining_current_t_a":
            metrics.get(
                "remaining_current_t"
            ),

        "remaining_current_a":
            metrics.get(
                "remaining_current"
            ),

        "final_supply_normalized":
            effective_final_normalized,

        "final_supply_normalization_date":
            (
                effective_final_date
                if (
                    effective_supply_status
                    == "MANUVER_SEBAGIAN"
                    and effective_final_normalized
                )
                else None
            ),

        "final_supply_normalization_time":
            (
                effective_final_time
                if (
                    effective_supply_status
                    == "MANUVER_SEBAGIAN"
                    and effective_final_normalized
                )
                else None
            ),

        "recovery_status_code":
            (
                pmt_status
                if has_pmt_recovery
                else None
            ),

        "recovery_date":
            (
                pmt_recovery_date
                if has_pmt_recovery
                else None
            ),

        "recovery_time":
            (
                pmt_recovery_time
                if has_pmt_recovery
                else None
            ),

        "pmt_counter_after":
            (
                pmt_counter_after
                if has_pmt_recovery
                else None
            ),

        "pmt_counter_error":
            counter_error,

        "load_current_after_r_a":
            (
                _optional_float(
                    load_current_after_r
                )
                if has_pmt_recovery
                else None
            ),

        "load_current_after_s_a":
            (
                _optional_float(
                    load_current_after_s
                )
                if has_pmt_recovery
                else None
            ),

        "load_current_after_t_a":
            (
                _optional_float(
                    load_current_after_t
                )
                if has_pmt_recovery
                else None
            ),

        # Legacy average dipertahankan sementara untuk kompatibilitas.
        "load_current_after_a":
            (
                load_current_after_average
                if has_pmt_recovery
                else None
            ),

        "voltage_after_kv":
            (
                (
                    _optional_float(voltage_after)
                )
                if has_pmt_recovery
                else None
            ),

        "preview_outage_min":
            metrics.get(
                "customer_outage_min"
            ),

        "preview_pmt_duration_min":
            metrics.get(
                "pmt_duration_min"
            ),

        "preview_ens_kwh":
            metrics.get(
                "ens_kwh"
            ),
    }


# ==========================================================
# VALIDATION
# ==========================================================


def _validate_supply_data(
    *,
    event_date: date,
    event_time: time,
    load_current_before_r: float | None,
    load_current_before_s: float | None,
    load_current_before_t: float | None,
    load_current_before: float,
    supply_data: dict[str, Any],
) -> list[str]:
    errors: list[str] = []

    event_dt = datetime.combine(
        event_date,
        event_time,
    )

    counter_error = (
        supply_data.get(
            "pmt_counter_error"
        )
    )

    if counter_error:
        errors.append(
            str(
                counter_error
            )
        )

    supply_status = str(
        supply_data.get(
            "supply_status_code"
        )
        or "BELUM"
    ).strip()

    # ======================================================
    # SUPPLY
    # ======================================================

    if (
        supply_status
        != "BELUM"
    ):
        supply_date = (
            supply_data.get(
                "supply_restored_date"
            )
        )

        supply_time = (
            supply_data.get(
                "supply_restored_time"
            )
        )

        if (
            not isinstance(
                supply_date,
                date,
            )
            or not isinstance(
                supply_time,
                time,
            )
        ):
            errors.append(
                "Tanggal dan waktu beban mulai tersuplai "
                "wajib diisi."
            )

        else:
            supply_dt = (
                datetime.combine(
                    supply_date,
                    supply_time,
                )
            )

            if (
                supply_dt
                < event_dt
            ):
                errors.append(
                    "Waktu beban mulai tersuplai "
                    "tidak boleh lebih awal dari waktu operasi."
                )

    # ======================================================
    # MANUVER SEBAGIAN
    # ======================================================

    if (
        supply_status
        == "MANUVER_SEBAGIAN"
    ):
        maneuvered_r = _optional_float(
            supply_data.get(
                "maneuvered_current_r_a"
            )
        )

        maneuvered_s = _optional_float(
            supply_data.get(
                "maneuvered_current_s_a"
            )
        )

        maneuvered_t = _optional_float(
            supply_data.get(
                "maneuvered_current_t_a"
            )
        )

        errors.extend(
            _validate_three_phase_current(
                current_r=maneuvered_r,
                current_s=maneuvered_s,
                current_t=maneuvered_t,
                label="Beban Berhasil Dimanuver",
                required=True,
            )
        )

        before_values = {
            "R": _optional_float(load_current_before_r),
            "S": _optional_float(load_current_before_s),
            "T": _optional_float(load_current_before_t),
        }

        maneuver_values = {
            "R": maneuvered_r,
            "S": maneuvered_s,
            "T": maneuvered_t,
        }

        if all(
            value is not None
            for value in maneuver_values.values()
        ):
            if all(
                _safe_float(value) <= 0
                for value in maneuver_values.values()
            ):
                errors.append(
                    "Beban termanuver harus lebih dari 0 A "
                    "pada minimal satu phasa."
                )

            for phase in ("R", "S", "T"):
                maneuver_value = (
                    maneuver_values[
                        phase
                    ]
                )

                before_value = (
                    before_values[
                        phase
                    ]
                )

                if (
                    maneuver_value is not None
                    and maneuver_value < 0
                ):
                    errors.append(
                        f"Beban termanuver phasa {phase} "
                        "tidak boleh negatif."
                    )

                if (
                    maneuver_value is not None
                    and before_value is not None
                    and maneuver_value > before_value
                ):
                    errors.append(
                        f"Beban termanuver phasa {phase} "
                        "tidak boleh melebihi beban awal "
                        f"phasa {phase}."
                    )

            all_fully_transferred = all(
                (
                    maneuver_values[phase]
                    is not None
                    and before_values[phase]
                    is not None
                    and abs(
                        _safe_float(
                            maneuver_values[
                                phase
                            ]
                        )
                        - _safe_float(
                            before_values[
                                phase
                            ]
                        )
                    ) < 1e-9
                )
                for phase in ("R", "S", "T")
            )

            if all_fully_transferred:
                errors.append(
                    "Jika seluruh beban R/S/T berhasil dimanuver, "
                    "gunakan status Manuver Seluruh Beban."
                )

        final_normalized = bool(
            supply_data.get(
                "final_supply_normalized"
            )
        )

        if final_normalized:
            final_date = (
                supply_data.get(
                    "final_supply_normalization_date"
                )
            )

            final_time = (
                supply_data.get(
                    "final_supply_normalization_time"
                )
            )

            supply_date = (
                supply_data.get(
                    "supply_restored_date"
                )
            )

            supply_time = (
                supply_data.get(
                    "supply_restored_time"
                )
            )

            if (
                not isinstance(
                    final_date,
                    date,
                )
                or not isinstance(
                    final_time,
                    time,
                )
            ):
                errors.append(
                    "Tanggal dan waktu seluruh sisa beban "
                    "kembali tersuplai wajib diisi."
                )

            elif (
                isinstance(
                    supply_date,
                    date,
                )
                and isinstance(
                    supply_time,
                    time,
                )
            ):
                final_dt = (
                    datetime.combine(
                        final_date,
                        final_time,
                    )
                )

                supply_dt = (
                    datetime.combine(
                        supply_date,
                        supply_time,
                    )
                )

                if (
                    final_dt
                    < supply_dt
                ):
                    errors.append(
                        "Normalisasi sisa beban tidak boleh "
                        "lebih awal dari waktu manuver sebagian."
                    )

    # ======================================================
    # PMT
    # ======================================================

    recovery_status_raw = (
        supply_data.get(
            "recovery_status_code"
        )
    )

    recovery_status = (
        str(
            recovery_status_raw
        ).strip()
        if recovery_status_raw
        else ""
    )

    if recovery_status:
        errors.extend(
            _validate_three_phase_current(
                current_r=_optional_float(
                    supply_data.get(
                        "load_current_after_r_a"
                    )
                ),
                current_s=_optional_float(
                    supply_data.get(
                        "load_current_after_s_a"
                    )
                ),
                current_t=_optional_float(
                    supply_data.get(
                        "load_current_after_t_a"
                    )
                ),
                label="Arus Beban Setelah Operasi",
                required=False,
            )
        )

        recovery_date = (
            supply_data.get(
                "recovery_date"
            )
        )

        recovery_time = (
            supply_data.get(
                "recovery_time"
            )
        )

        if (
            not isinstance(
                recovery_date,
                date,
            )
            or not isinstance(
                recovery_time,
                time,
            )
        ):
            errors.append(
                "Tanggal dan waktu operasi PMT wajib diisi."
            )

        else:
            recovery_dt = (
                datetime.combine(
                    recovery_date,
                    recovery_time,
                )
            )

            if (
                recovery_dt
                < event_dt
            ):
                errors.append(
                    "Waktu operasi PMT tidak boleh "
                    "lebih awal dari waktu gangguan / manuver."
                )

    return errors


# ==========================================================
# READ-ONLY IDENTITY
# ==========================================================


def _render_update_identity(
    row: EventRow,
) -> None:
    with st.container(
        border=True
    ):
        st.markdown(
            "#### Identitas Penyulang"
        )

        col_ultg, col_gi, col_bay, col_feeder = (
            st.columns(
                [1, 1.4, 1.8, 1.4]
            )
        )

        with col_ultg:
            st.caption(
                "ULTG"
            )

            st.write(
                f"**{row.get('ultg_name') or '-'}**"
            )

        with col_gi:
            st.caption(
                "Gardu Induk"
            )

            st.write(
                f"**{row.get('gi_name') or '-'}**"
            )

        with col_bay:
            st.caption(
                "Bay"
            )

            st.write(
                f"**{row.get('bay_name') or '-'}**"
            )

        with col_feeder:
            st.caption(
                "Penyulang"
            )

            code = str(
                row.get(
                    "penyulang_code"
                )
                or "-"
            )

            name = str(
                row.get(
                    "penyulang_name"
                )
                or "-"
            )

            st.write(
                f"**{code} — {name}**"
            )


# ==========================================================
# OPERATION STAFF
# ==========================================================


def _current_input_user_name() -> str:
    """
    Nama user yang sedang login.
    Diambil melalui RPC profile agar tidak bergantung pada
    direct SELECT app_user_profile.
    """

    try:
        profile = get_my_profile()

    except Exception:
        return "-"

    return str(
        profile.get(
            "full_name"
        )
        or profile.get(
            "employee_id"
        )
        or "-"
    ).strip() or "-"


def _render_operation_staff(
    *,
    prefix: str,
    existing_row: EventRow | None,
    disabled: bool,
) -> tuple[str, str]:
    """
    Operator Bertugas dan Dispatcher UP2D wajib.
    Diinput Oleh otomatis/read-only.
    """

    if existing_row is not None:
        input_user_name = str(
            existing_row.get(
                "created_by_name"
            )
            or ""
        ).strip()

        if not input_user_name:
            input_user_name = (
                _current_input_user_name()
            )

    else:
        input_user_name = (
            _current_input_user_name()
        )

    with st.container(
        border=True
    ):
        st.markdown(
            "#### Informasi Petugas"
        )

        st.caption(
            "Operator Bertugas dan Dispatcher UP2D wajib diisi. "
            "Diinput Oleh tercatat otomatis dari akun login."
        )

        col_operator, col_dispatcher, col_input = (
            st.columns(
                [1.35, 1.35, 1.3]
            )
        )

        with col_operator:
            operator_name = st.text_input(
                "Operator Bertugas *",
                key=(
                    f"{prefix}_operator_name"
                ),
                placeholder=(
                    "Nama operator"
                ),
                disabled=disabled,
            )

        with col_dispatcher:
            dispatcher_name = st.text_input(
                "Dispatcher UP2D *",
                key=(
                    f"{prefix}_dispatcher_up2d_name"
                ),
                placeholder=(
                    "Nama dispatcher"
                ),
                disabled=disabled,
            )

        with col_input:
            st.text_input(
                "Diinput Oleh",
                value=input_user_name,
                disabled=True,
                key=(
                    f"{prefix}_created_by_display"
                ),
                help=(
                    "Terisi otomatis berdasarkan user login "
                    "saat record dibuat."
                ),
            )

    return (
        str(
            operator_name
            or ""
        ).strip(),
        str(
            dispatcher_name
            or ""
        ).strip(),
    )


# ==========================================================
# COMMON SUPPLY PAYLOAD
# ==========================================================


def _build_supply_payload(
    supply_data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "supply_status_code":
            supply_data[
                "supply_status_code"
            ],

        "supply_restored_date":
            _date_value(
                supply_data[
                    "supply_restored_date"
                ]
            ),

        "supply_restored_time":
            _time_value(
                supply_data[
                    "supply_restored_time"
                ]
            ),

        "maneuvered_current_r_a":
            supply_data[
                "maneuvered_current_r_a"
            ],

        "maneuvered_current_s_a":
            supply_data[
                "maneuvered_current_s_a"
            ],

        "maneuvered_current_t_a":
            supply_data[
                "maneuvered_current_t_a"
            ],

        # Legacy average tetap dipertahankan.
        "maneuvered_current_a":
            supply_data[
                "maneuvered_current_a"
            ],

        # Sisa beban read-only dari UI dan dihitung ulang database.
        "remaining_current_r_a":
            supply_data[
                "remaining_current_r_a"
            ],

        "remaining_current_s_a":
            supply_data[
                "remaining_current_s_a"
            ],

        "remaining_current_t_a":
            supply_data[
                "remaining_current_t_a"
            ],

        "remaining_current_a":
            supply_data[
                "remaining_current_a"
            ],

        "final_supply_normalized":
            supply_data[
                "final_supply_normalized"
            ],

        "final_supply_normalization_date":
            _date_value(
                supply_data[
                    "final_supply_normalization_date"
                ]
            ),

        "final_supply_normalization_time":
            _time_value(
                supply_data[
                    "final_supply_normalization_time"
                ]
            ),

        "recovery_status_code":
            supply_data[
                "recovery_status_code"
            ],

        "recovery_date":
            _date_value(
                supply_data[
                    "recovery_date"
                ]
            ),

        "recovery_time":
            _time_value(
                supply_data[
                    "recovery_time"
                ]
            ),

        "pmt_counter_after":
            supply_data[
                "pmt_counter_after"
            ],

        "load_current_after_r_a":
            supply_data[
                "load_current_after_r_a"
            ],

        "load_current_after_s_a":
            supply_data[
                "load_current_after_s_a"
            ],

        "load_current_after_t_a":
            supply_data[
                "load_current_after_t_a"
            ],

        # Legacy average untuk kalkulasi/service yang belum dimigrasi.
        "load_current_after_a":
            supply_data[
                "load_current_after_a"
            ],

        "voltage_after_kv":
            supply_data[
                "voltage_after_kv"
            ],
    }


# ==========================================================
# MONTHLY PERIOD LOCK
# ==========================================================


def _resolve_period_guard_penyulang_id(
    *,
    selected: HierarchySelection | None,
    existing_row: EventRow | None,
) -> str:
    """
    Mengambil penyulang_id baik pada mode CREATE maupun UPDATE.
    """

    if selected is not None:
        selected_id = str(
            selected.get(
                "penyulang_id"
            )
            or ""
        ).strip()

        if selected_id:
            return selected_id

    if existing_row is not None:
        existing_id = str(
            existing_row.get(
                "penyulang_id"
            )
            or ""
        ).strip()

        if existing_id:
            return existing_id

    return ""


def _render_period_lock_after_datetime(
    *,
    selected: HierarchySelection | None,
    existing_row: EventRow | None,
    event_date: date,
    event_type: str,
) -> bool:
    """
    Guard UI yang tampil segera setelah Tanggal + Jam operasi.

    Bila periode sudah APPROVED:
    - tampilkan notifikasi;
    - hentikan rendering form berikutnya;
    - penyimpanan tidak mungkin dilakukan dari UI.

    Trigger Supabase tetap menjadi proteksi final.
    """

    penyulang_id = (
        _resolve_period_guard_penyulang_id(
            selected=selected,
            existing_row=existing_row,
        )
    )

    return render_monthly_period_guard(
        penyulang_id=(
            penyulang_id
        ),
        event_date=(
            event_date
        ),
        event_type=(
            event_type
        ),
    )


# ==========================================================
# GANGGUAN FORM
# ==========================================================


def _render_gangguan_form(
    *,
    mode: str,
    selected: HierarchySelection | None,
    existing_row: EventRow | None,
) -> None:
    is_active_update = (
        mode
        == "UPDATE"
    )

    is_history_update = (
        mode
        == "UPDATE_HISTORY"
    )

    if is_active_update:
        prefix = (
            "update_gangguan"
        )

    elif is_history_update:
        prefix = (
            "history_gangguan"
        )

    else:
        prefix = (
            "create_gangguan"
        )

    initial_disabled = (
        is_active_update
    )

    # ======================================================
    # DATA GANGGUAN
    # ======================================================

    with st.container(
        border=True
    ):
        st.markdown(
            "#### Data Gangguan"
        )

        if is_active_update:
            st.caption(
                "Data gangguan awal dikunci. "
                "Mode ini hanya untuk Pemulihan & Normalisasi."
            )

        elif is_history_update:
            st.caption(
                "Mode Edit Riwayat. "
                "Data operasional dapat diperbaiki."
            )

        else:
            st.caption(
                "Status PMT awal otomatis: **TRIP**"
            )

        col_date, col_time = (
            st.columns(2)
        )

        with col_date:
            event_date = (
                st.date_input(
                    "Tanggal Gangguan",
                    key=(
                        f"{prefix}_date"
                    ),
                    disabled=(
                        initial_disabled
                    ),
                )
            )

        with col_time:
            event_time = (
                st.time_input(
                    "Waktu Trip PMT",
                    key=(
                        f"{prefix}_time"
                    ),
                    disabled=(
                        initial_disabled
                    ),
                )
            )

        period_allowed = (
            _render_period_lock_after_datetime(
                selected=selected,
                existing_row=existing_row,
                event_date=event_date,
                event_type="GANGGUAN",
            )
        )

        if not period_allowed:
            return

        (
            load_current_before_r,
            load_current_before_s,
            load_current_before_t,
        ) = _render_three_phase_current_input(
            title="Arus Beban Sebelum Gangguan",
            key_prefix=f"{prefix}_load_current_before",
            disabled=initial_disabled,
            help_text=(
                "Masukkan arus beban masing-masing phasa "
                "sebelum gangguan."
            ),
        )

        load_current_before = (
            _three_phase_average(
                load_current_before_r,
                load_current_before_s,
                load_current_before_t,
            )
        )

        col_voltage, col_pf = st.columns(
            [1, 0.8]
        )

        with col_voltage:
            voltage_before = (
                _numeric_text_input_optional(
                    "Tegangan Sistem (kV)",
                    key=f"{prefix}_voltage_before",
                    disabled=initial_disabled,
                    placeholder="Masukkan tegangan",
                )
            )

        with col_pf:
            power_factor = (
                _fixed_pf_display(
                    key=f"{prefix}_power_factor"
                )
            )

        if load_current_before is not None:
            st.caption(
                "Arus rata-rata 3 phasa untuk kalkulasi ENS: "
                f"**{load_current_before:,.2f} A**"
            )

    operator_name, dispatcher_up2d_name = (
        _render_operation_staff(
            prefix=prefix,
            existing_row=existing_row,
            disabled=initial_disabled,
        )
    )

    # ======================================================
    # PROTEKSI
    # ======================================================

    annunciator_options = (
        _build_reference_options(
            get_annunciators(),
            "annunciator_code",
        )
    )

    indication_options = (
        _build_reference_options(
            get_indications(),
            "indikasi_code",
        )
    )

    def format_annunciator(
        value: str,
    ) -> str:
        if value == "":
            return (
                "Pilih Annunciator"
            )

        return (
            annunciator_options.get(
                value,
                value,
            )
        )

    def format_indication(
        value: str,
    ) -> str:
        return (
            indication_options.get(
                value,
                value,
            )
        )

    with st.container(
        border=True
    ):
        st.markdown(
            "#### Proteksi & Indikasi"
        )

        col_ann, col_ind = (
            st.columns(2)
        )

        with col_ann:
            annunciator = (
                st.selectbox(
                    "Annunciator",
                    options=[
                        "",
                        *list(
                            annunciator_options.keys()
                        ),
                    ],
                    format_func=(
                        format_annunciator
                    ),
                    key=(
                        f"{prefix}_annunciator"
                    ),
                    disabled=(
                        initial_disabled
                    ),
                )
            )

        with col_ind:
            selected_indications = (
                st.multiselect(
                    "Indikasi Relay / Proteksi",
                    options=list(
                        indication_options.keys()
                    ),
                    format_func=(
                        format_indication
                    ),
                    placeholder=(
                        "Pilih indikasi"
                    ),
                    key=(
                        f"{prefix}_indications"
                    ),
                    disabled=(
                        initial_disabled
                    ),
                )
            )

        st.caption(
            "Arus Gangguan"
        )

        col_r, col_s, col_t, col_n = (
            st.columns(4)
        )

        with col_r:
            fault_current_r = (
                _numeric_text_input_optional(
                    "I-R (A)",
                    key=f"{prefix}_fault_current_r",
                    disabled=initial_disabled,
                    placeholder="Kosong",
                )
            )

        with col_s:
            fault_current_s = (
                _numeric_text_input_optional(
                    "I-S (A)",
                    key=f"{prefix}_fault_current_s",
                    disabled=initial_disabled,
                    placeholder="Kosong",
                )
            )

        with col_t:
            fault_current_t = (
                _numeric_text_input_optional(
                    "I-T (A)",
                    key=f"{prefix}_fault_current_t",
                    disabled=initial_disabled,
                    placeholder="Kosong",
                )
            )

        with col_n:
            fault_current_n = (
                _numeric_text_input_optional(
                    "I-N / Residual (A)",
                    key=f"{prefix}_fault_current_n",
                    disabled=initial_disabled,
                    placeholder="Kosong",
                )
            )

        selected_phases = (
            st.pills(
                "Phasa Terganggu",
                options=[
                    "R",
                    "S",
                    "T",
                    "N",
                ],
                selection_mode="multi",
                key=(
                    f"{prefix}_phases"
                ),
                disabled=(
                    initial_disabled
                ),
            )
        )

    # ======================================================
    # CLASSIFICATION
    # ======================================================

    cause_options = (
        _build_reference_options(
            get_causes(),
            "cause_code",
        )
    )

    cause_rules = (
        get_cause_rules()
    )

    valid_causes = [
        str(
            rule.get(
                "cause_code"
            )
        )
        for rule
        in cause_rules
        if (
            str(
                rule.get(
                    "status_code"
                )
                or ""
            ).strip()
            == "TRIP"
            and str(
                rule.get(
                    "pic_code"
                )
                or ""
            ).strip()
            == "UPT"
            and rule.get(
                "cause_code"
            )
        )
    ]

    if (
        is_history_update
        and existing_row is not None
    ):
        existing_cause = str(
            existing_row.get(
                "cause_code"
            )
            or ""
        )

        if (
            existing_cause
            and existing_cause
            not in valid_causes
        ):
            valid_causes.append(
                existing_cause
            )

    def format_cause(
        value: str,
    ) -> str:
        if value == "":
            return (
                "Pilih klasifikasi"
            )

        return (
            cause_options.get(
                value,
                value,
            )
        )

    with st.container(
        border=True
    ):
        st.markdown(
            "#### Klasifikasi & Kronologi"
        )

        col_pic, col_cause = (
            st.columns(2)
        )

        with col_pic:
            st.text_input(
                "PIC Gangguan",
                value="UPT",
                disabled=True,
                key=(
                    f"{prefix}_pic_display"
                ),
            )

        with col_cause:
            selected_cause = (
                st.selectbox(
                    "Klasifikasi Penyebab",
                    options=[
                        "",
                        *[
                            code
                            for code
                            in valid_causes
                            if code
                            in cause_options
                        ],
                    ],
                    format_func=(
                        format_cause
                    ),
                    key=(
                        f"{prefix}_cause"
                    ),
                    disabled=(
                        initial_disabled
                    ),
                )
            )

        event_description = (
            st.text_area(
                "Kronologi Gangguan",
                placeholder=(
                    "Ringkas trip PMT, indikasi proteksi, "
                    "hasil pengecekan awal, dan kondisi jaringan..."
                ),
                height=110,
                key=(
                    f"{prefix}_description"
                ),
                disabled=(
                    initial_disabled
                ),
            )
        )

    # ======================================================
    # SUPPLY / PMT
    # ======================================================

    supply_data = (
        _render_supply_restoration(
            prefix=prefix,
            event_date=event_date,
            event_time=event_time,
            voltage_before=_safe_float(voltage_before),
            load_current_before_r=(
                _optional_float(
                    load_current_before_r
                )
            ),
            load_current_before_s=(
                _optional_float(
                    load_current_before_s
                )
            ),
            load_current_before_t=(
                _optional_float(
                    load_current_before_t
                )
            ),
            load_current_before=_safe_float(load_current_before),
            power_factor=float(
                power_factor
            ),
            enabled=True,
        )
    )

    with st.container(
        border=True
    ):
        recovery_description = (
            st.text_area(
                "Keterangan Pemulihan / Normalisasi",
                placeholder=(
                    "Manuver jaringan, feeder tujuan, "
                    "percobaan masuk PMT, normalisasi beban, "
                    "atau kondisi akhir..."
                ),
                height=100,
                key=(
                    f"{prefix}_recovery_description"
                ),
            )
        )

    # ======================================================
    # EVIDENCE
    # ======================================================

    with st.container(
        border=True
    ):
        st.markdown(
            "#### Evidence"
        )

        evidence = (
            st.file_uploader(
                "Upload Evidence (Opsional)",
                type=[
                    "jpg",
                    "jpeg",
                    "png",
                    "pdf",
                ],
                accept_multiple_files=True,
                key=(
                    f"{prefix}_evidence"
                ),
            )
        )

        if evidence:
            st.caption(
                f"{len(evidence)} file dipilih. "
                "Evidence akan diarsipkan ke Google Drive "
                "dan dikirim ke Telegram saat data disimpan."
            )

    # ======================================================
    # ACTIVE UPDATE
    # ======================================================

    if is_active_update:
        st.divider()

        col_back, col_save = (
            st.columns(
                [1, 2]
            )
        )

        with col_back:
            back_clicked = (
                st.button(
                    "Kembali",
                    use_container_width=True,
                    key=(
                        "update_back_to_active"
                    ),
                )
            )

        if back_clicked:
            _return_to_source()
            return

        with col_save:
            save_clicked = (
                st.button(
                    "Simpan Pemulihan & Normalisasi",
                    type="primary",
                    use_container_width=True,
                    key=(
                        "update_save_recovery"
                    ),
                )
            )

        if not save_clicked:
            return

        if existing_row is None:
            st.error(
                "Data Gangguan Aktif tidak ditemukan."
            )
            return

        errors = (
            _validate_three_phase_current(
                current_r=load_current_before_r,
                current_s=load_current_before_s,
                current_t=load_current_before_t,
                label="Arus Beban Sebelum Gangguan",
                required=False,
            )
        )

        errors.extend(
            _validate_supply_data(
                event_date=event_date,
                event_time=event_time,
                load_current_before_r=(
                    _optional_float(
                        load_current_before_r
                    )
                ),
                load_current_before_s=(
                    _optional_float(
                        load_current_before_s
                    )
                ),
                load_current_before_t=(
                    _optional_float(
                        load_current_before_t
                    )
                ),
                load_current_before=_safe_float(load_current_before),
                supply_data=(
                    supply_data
                ),
            )
        )

        if errors:
            for error in errors:
                st.error(
                    error
                )

            return

        user_id = (
            get_current_user_id()
        )

        if user_id is None:
            st.error(
                "Session login tidak valid."
            )
            return

        event_id = str(
            existing_row.get(
                "event_id"
            )
            or ""
        )

        update_payload = (
            _build_supply_payload(
                supply_data
            )
        )

        update_payload[
            "recovery_description"
        ] = (
            recovery_description.strip()
            or None
        )

        update_payload[
            "updated_by"
        ] = user_id

        try:
            with st.spinner(
                "Menyimpan pemulihan..."
            ):
                updated_event = (
                    update_event_recovery(
                        event_id=event_id,
                        payload=update_payload,
                    )
                )

            existing_hierarchy: dict[str, Any] = {
                "ultg_name":
                    existing_row.get("ultg_name"),

                "gi_name":
                    existing_row.get("gi_name"),

                "bay_name":
                    existing_row.get("bay_name"),

                "penyulang_code":
                    existing_row.get("penyulang_code"),

                "penyulang_name":
                    existing_row.get("penyulang_name"),
            }

            recovery_cause_name = str(
                existing_row.get("cause_name")
                or existing_row.get("cause_code")
                or "TANPA PENYEBAB"
            )

            drive_count, drive_errors = (
                drive_service.upload_evidence_files(
                    uploaded_files=list(
                        evidence
                        or []
                    ),
                    event_id=event_id,
                    event_type="GANGGUAN",
                    hierarchy=existing_hierarchy,
                    event_date=str(
                        existing_row.get("event_date")
                        or event_date.isoformat()
                    ),
                    event_time=str(
                        existing_row.get("event_time")
                        or event_time.isoformat()
                    ),
                    cause_name=recovery_cause_name,
                )
            )

            latest_event_row = (
                get_event_by_id(
                    event_id
                )
                or existing_row
            )

            telegram_ok, telegram_message = (
                telegram_service.send_recovery_notification(
                    event_id=event_id,
                    event_row=latest_event_row,
                    recovery_payload=update_payload,
                    uploaded_files=list(
                        evidence
                        or []
                    ),
                )
            )

            st.session_state[
                "gangguan_active_telegram_flash"
            ] = (
                (
                    "📨 "
                    + telegram_message
                )
                if telegram_ok
                else (
                    "⚠️ Telegram pemulihan gagal: "
                    + telegram_message
                )
            )

            if drive_errors:
                st.session_state[
                    "gangguan_active_drive_flash"
                ] = (
                    "Sebagian evidence gagal diarsipkan "
                    "ke Google Drive: "
                    + " | ".join(
                        drive_errors
                    )
                )

            elif drive_count > 0:
                st.session_state[
                    "gangguan_active_drive_flash"
                ] = (
                    f"{drive_count} evidence berhasil "
                    "diarsipkan ke Google Drive."
                )

            updated_status = str(
                updated_event.get(
                    "record_status"
                )
                or ""
            )

            if (
                updated_status
                == "RECOVERED"
            ):
                st.session_state[
                    "gangguan_active_flash"
                ] = (
                    "Pemulihan berhasil disimpan. "
                    "Gangguan telah berstatus RECOVERED."
                )

            else:
                st.session_state[
                    "gangguan_active_flash"
                ] = (
                    "Update pemulihan berhasil disimpan. "
                    "Gangguan masih berstatus ONGOING."
                )

            _return_to_source()

        except Exception as exc:
            error_text = str(
                exc
            )

            if (
                "EVENT_PERIOD_ALREADY_APPROVED"
                in error_text
                or "EVENT_LOCKED_BY_APPROVED_MONTHLY_REPORT"
                in error_text
            ):
                st.error(
                    "Data tidak dapat diubah karena Laporan Bulanan "
                    "pada periode tersebut sudah Terverifikasi."
                )

                st.caption(
                    "Silakan hubungi Evaluator / Admin / Super Admin "
                    "untuk mengembalikan Laporan Bulanan ke Draft."
                )

            else:
                st.error(
                    "Pemulihan gagal disimpan."
                )

                st.exception(
                    exc
                )

        return

    # ======================================================
    # HISTORY UPDATE
    # ======================================================

    if is_history_update:
        st.divider()

        col_back, col_save = (
            st.columns(
                [1, 2]
            )
        )

        with col_back:
            back_clicked = (
                st.button(
                    "Kembali ke Riwayat",
                    use_container_width=True,
                    key=(
                        "history_gangguan_back"
                    ),
                )
            )

        if back_clicked:
            _return_to_source()
            return

        with col_save:
            save_clicked = (
                st.button(
                    "Simpan Perubahan",
                    type="primary",
                    use_container_width=True,
                    key=(
                        "history_gangguan_save"
                    ),
                )
            )

        if not save_clicked:
            return

        if existing_row is None:
            st.error(
                "Data riwayat tidak ditemukan."
            )
            return

        errors: list[str] = []

        if not selected_cause:
            errors.append(
                "Klasifikasi penyebab wajib dipilih."
            )

        if not operator_name:
            errors.append(
                "Operator Bertugas wajib diisi."
            )

        if not dispatcher_up2d_name:
            errors.append(
                "Dispatcher UP2D wajib diisi."
            )

        errors.extend(
            _validate_three_phase_current(
                current_r=load_current_before_r,
                current_s=load_current_before_s,
                current_t=load_current_before_t,
                label="Arus Beban Sebelum Gangguan",
                required=False,
            )
        )

        errors.extend(
            _validate_supply_data(
                event_date=event_date,
                event_time=event_time,
                load_current_before_r=(
                    _optional_float(
                        load_current_before_r
                    )
                ),
                load_current_before_s=(
                    _optional_float(
                        load_current_before_s
                    )
                ),
                load_current_before_t=(
                    _optional_float(
                        load_current_before_t
                    )
                ),
                load_current_before=_safe_float(load_current_before),
                supply_data=(
                    supply_data
                ),
            )
        )

        if errors:
            for error in errors:
                st.error(
                    error
                )

            return

        user_id = (
            get_current_user_id()
        )

        if user_id is None:
            st.error(
                "Session login tidak valid."
            )
            return

        event_id = str(
            existing_row.get(
                "event_id"
            )
            or ""
        )

        payload: dict[
            str,
            Any
        ] = {
            "event_date":
                event_date.isoformat(),

            "event_time":
                event_time.isoformat(),

            "load_current_before_r_a":
                _optional_float(
                    load_current_before_r
                ),

            "load_current_before_s_a":
                _optional_float(
                    load_current_before_s
                ),

            "load_current_before_t_a":
                _optional_float(
                    load_current_before_t
                ),

            # Legacy average dipertahankan sementara.
            "load_current_before_a":
                _optional_float(
                    load_current_before
                ),

            "voltage_before_kv":
                (
                    _optional_float(voltage_before)
                ),

            "power_factor_before":
                0.85,

            "operator_name":
                operator_name,

            "dispatcher_up2d_name":
                dispatcher_up2d_name,

            "fault_current_r_a":
                (
                    _optional_float(fault_current_r)
                ),

            "fault_current_s_a":
                (
                    _optional_float(fault_current_s)
                ),

            "fault_current_t_a":
                (
                    _optional_float(fault_current_t)
                ),

            "fault_current_n_a":
                (
                    _optional_float(fault_current_n)
                ),

            "phase_r":
                "R"
                in selected_phases,

            "phase_s":
                "S"
                in selected_phases,

            "phase_t":
                "T"
                in selected_phases,

            "phase_n":
                "N"
                in selected_phases,

            "annunciator_code":
                (
                    str(
                        annunciator
                    )
                    if annunciator
                    else None
                ),

            "pic_code":
                "UPT",

            "cause_code":
                str(
                    selected_cause
                ),

            "event_description":
                (
                    event_description.strip()
                    or None
                ),

            "recovery_description":
                (
                    recovery_description.strip()
                    or None
                ),

            "updated_by":
                user_id,
        }

        payload.update(
            _build_supply_payload(
                supply_data
            )
        )

        try:
            with st.spinner(
                "Menyimpan perubahan riwayat..."
            ):
                update_event(
                    event_id=event_id,
                    payload=payload,
                )

                _replace_event_indications(
                    event_id=event_id,
                    indication_codes=[
                        str(code)
                        for code
                        in selected_indications
                    ],
                )

            st.session_state[
                "history_flash_message"
            ] = (
                "Perubahan riwayat Gangguan "
                "berhasil disimpan."
            )

            _return_to_source()

        except Exception as exc:
            error_text = str(
                exc
            )

            if (
                "EVENT_PERIOD_ALREADY_APPROVED"
                in error_text
                or "EVENT_LOCKED_BY_APPROVED_MONTHLY_REPORT"
                in error_text
            ):
                st.error(
                    "Riwayat tidak dapat diubah karena Laporan Bulanan "
                    "pada periode tersebut sudah Terverifikasi."
                )

                st.caption(
                    "Silakan hubungi Evaluator / Admin / Super Admin "
                    "untuk mengembalikan Laporan Bulanan ke Draft."
                )

            else:
                st.error(
                    "Perubahan riwayat gagal disimpan."
                )

                st.exception(
                    exc
                )

        return

    # ======================================================
    # CREATE GANGGUAN
    # ======================================================

    st.divider()

    save_clicked = (
        st.button(
            "Simpan Data Gangguan",
            type="primary",
            use_container_width=True,
            key=(
                "create_save_gangguan"
            ),
        )
    )

    if not save_clicked:
        return

    errors: list[str] = []

    if selected is None:
        errors.append(
            "Penyulang belum dipilih."
        )

    if not selected_cause:
        errors.append(
            "Klasifikasi penyebab wajib dipilih."
        )

    if not operator_name:
        errors.append(
            "Operator Bertugas wajib diisi."
        )

    if not dispatcher_up2d_name:
        errors.append(
            "Dispatcher UP2D wajib diisi."
        )

    errors.extend(
        _validate_supply_data(
            event_date=event_date,
            event_time=event_time,
            load_current_before_r=(
                _optional_float(
                    load_current_before_r
                )
            ),
            load_current_before_s=(
                _optional_float(
                    load_current_before_s
                )
            ),
            load_current_before_t=(
                _optional_float(
                    load_current_before_t
                )
            ),
            load_current_before=_safe_float(load_current_before),
            supply_data=(
                supply_data
            ),
        )
    )

    if errors:
        for error in errors:
            st.error(
                error
            )

        return

    if selected is None:
        return

    user_id = (
        get_current_user_id()
    )

    if user_id is None:
        st.error(
            "Session login tidak valid."
        )
        return

    payload: dict[
        str,
        Any
    ] = {
        "event_type_code":
            "GANGGUAN",

        "penyulang_id":
            str(
                selected[
                    "penyulang_id"
                ]
            ),

        "pmt_status_code":
            "TRIP",

        "pic_code":
            "UPT",

        "cause_code":
            str(
                selected_cause
            ),

        "event_date":
            event_date.isoformat(),

        "event_time":
            event_time.isoformat(),

        "load_current_before_r_a":
            _optional_float(
                load_current_before_r
            ),

        "load_current_before_s_a":
            _optional_float(
                load_current_before_s
            ),

        "load_current_before_t_a":
            _optional_float(
                load_current_before_t
            ),

        # Legacy average dipertahankan sementara.
        "load_current_before_a":
            _optional_float(
                load_current_before
            ),

        "voltage_before_kv":
            _optional_float(voltage_before),

        "power_factor_before":
                0.85,

        "operator_name":
            operator_name,

        "dispatcher_up2d_name":
            dispatcher_up2d_name,

        "fault_current_r_a":
            _optional_float(fault_current_r),

        "fault_current_s_a":
            _optional_float(fault_current_s),

        "fault_current_t_a":
            _optional_float(fault_current_t),

        "fault_current_n_a":
            _optional_float(fault_current_n),

        "phase_r":
            "R"
            in selected_phases,

        "phase_s":
            "S"
            in selected_phases,

        "phase_t":
            "T"
            in selected_phases,

        "phase_n":
            "N"
            in selected_phases,

        "annunciator_code":
            (
                str(
                    annunciator
                )
                if annunciator
                else None
            ),

        "event_description":
            (
                event_description.strip()
                or None
            ),

        "recovery_description":
            (
                recovery_description.strip()
                or None
            ),

        "created_by":
            user_id,

        "updated_by":
            user_id,
    }

    payload.update(
        _build_supply_payload(
            supply_data
        )
    )

    try:
        with st.spinner(
            "Menyimpan data gangguan..."
        ):
            saved_event = (
                create_event(
                    payload
                )
            )

            event_id = str(
                saved_event[
                    "event_id"
                ]
            )

            create_event_indications(
                event_id=event_id,
                indication_codes=[
                    str(code)
                    for code
                    in selected_indications
                ],
            )

            cause_name = (
                cause_options.get(
                    str(
                        selected_cause
                    )
                )
                or str(
                    selected_cause
                )
            )

            drive_count, drive_errors = (
                drive_service.upload_evidence_files(
                    uploaded_files=list(
                        evidence
                        or []
                    ),
                    event_id=event_id,
                    event_type="GANGGUAN",
                    hierarchy=selected,
                    event_date=event_date.isoformat(),
                    event_time=event_time.isoformat(),
                    cause_name=cause_name,
                )
            )

            telegram_payload = dict(
                payload
            )

            telegram_payload[
                "created_by_name"
            ] = _current_input_user_name()

            telegram_ok, telegram_message = (
                telegram_service.send_event_notification(
                    event_id=event_id,
                    event_type="GANGGUAN",
                    hierarchy=selected,
                    payload=telegram_payload,
                    cause_name=cause_name,
                    pic_name="UPT",
                    annunciator_name=(
                        annunciator_options.get(
                            str(
                                annunciator
                            )
                        )
                        if annunciator
                        else None
                    ),
                    indication_names=[
                        indication_options.get(
                            str(
                                code
                            ),
                            str(
                                code
                            ),
                        )
                        for code
                        in selected_indications
                    ],
                    uploaded_files=list(
                        evidence
                        or []
                    ),
                )
            )

            # Jika data pemulihan sudah diisi langsung saat
            # input Gangguan, kirim notifikasi Pemulihan
            # sebagai pesan Telegram kedua. User tidak perlu
            # masuk dahulu ke halaman Gangguan Aktif.
            recovery_status_code = str(
                payload.get(
                    "recovery_status_code"
                )
                or ""
            ).strip().upper()

            supply_status_code = str(
                payload.get(
                    "supply_status_code"
                )
                or "BELUM"
            ).strip().upper()

            has_direct_recovery = (
                recovery_status_code
                not in {
                    "",
                    "BELUM",
                }
                or supply_status_code
                not in {
                    "",
                    "BELUM",
                }
                or bool(
                    payload.get(
                        "final_supply_normalized"
                    )
                )
            )

            if has_direct_recovery:
                latest_event_row = (
                    get_event_by_id(
                        event_id
                    )
                    or saved_event
                )

                (
                    recovery_telegram_ok,
                    recovery_telegram_message,
                ) = (
                    telegram_service.send_recovery_notification(
                        event_id=event_id,
                        event_row=latest_event_row,
                        recovery_payload=payload,
                        uploaded_files=list(
                            evidence
                            or []
                        ),
                    )
                )

                telegram_ok = (
                    telegram_ok
                    and recovery_telegram_ok
                )

                telegram_message = (
                    f"{telegram_message} | "
                    f"{recovery_telegram_message}"
                )

        drive_ok = (
            not drive_errors
        )

        drive_message = (
            (
                f"{drive_count} evidence berhasil diarsipkan ke Google Drive."
                if drive_count > 0
                else "Tidak ada evidence yang diunggah."
            )
            if drive_ok
            else (
                "Sebagian evidence gagal diarsipkan ke Google Drive: "
                + " | ".join(
                    drive_errors
                )
            )
        )

        _set_input_success(
            event_id=event_id,
            event_type="GANGGUAN",
            telegram_ok=telegram_ok,
            telegram_message=telegram_message,
            drive_ok=drive_ok,
            drive_message=drive_message,
        )

        st.rerun()

    except Exception as exc:
        error_text = str(
            exc
        )

        if (
            "EVENT_PERIOD_ALREADY_APPROVED"
            in error_text
            or "EVENT_LOCKED_BY_APPROVED_MONTHLY_REPORT"
            in error_text
        ):
            st.error(
                "Periode laporan sudah Terverifikasi. "
                "Data Gangguan tidak dapat disimpan."
            )

            st.caption(
                "Silakan hubungi Evaluator / Admin / Super Admin "
                "untuk mengembalikan Laporan Bulanan ke Draft."
            )

        else:
            st.error(
                "Data gangguan gagal disimpan."
            )

            st.exception(
                exc
            )


# ==========================================================
# MANUVER FORM
# ==========================================================


def _render_manuver_form(
    *,
    mode: str,
    selected: HierarchySelection | None,
    existing_row: EventRow | None,
) -> None:
    is_history_update = (
        mode
        == "UPDATE_HISTORY"
    )

    prefix = (
        "history_manuver"
        if is_history_update
        else "create_manuver"
    )

    with st.container(
        border=True
    ):
        st.markdown(
            "#### Data Operasi Manuver"
        )

        if is_history_update:
            st.caption(
                "Mode Edit Riwayat Manuver."
            )

        else:
            st.caption(
                "Status operasi PMT awal otomatis: **LEPAS**"
            )

        col_date, col_time = (
            st.columns(2)
        )

        with col_date:
            event_date = (
                st.date_input(
                    "Tanggal Manuver",
                    key=(
                        f"{prefix}_date"
                    ),
                )
            )

        with col_time:
            event_time = (
                st.time_input(
                    "Waktu PMT Lepas",
                    key=(
                        f"{prefix}_time"
                    ),
                )
            )

        period_allowed = (
            _render_period_lock_after_datetime(
                selected=selected,
                existing_row=existing_row,
                event_date=event_date,
                event_type="MANUVER",
            )
        )

        if not period_allowed:
            return

        (
            load_current_before_r,
            load_current_before_s,
            load_current_before_t,
        ) = _render_three_phase_current_input(
            title="Arus Beban Sebelum Manuver",
            key_prefix=f"{prefix}_load_current_before",
            disabled=False,
            help_text=(
                "Masukkan arus beban masing-masing phasa "
                "sebelum manuver."
            ),
        )

        load_current_before = (
            _three_phase_average(
                load_current_before_r,
                load_current_before_s,
                load_current_before_t,
            )
        )

        col_voltage, col_pf = st.columns(
            [1, 0.8]
        )

        with col_voltage:
            voltage_before = (
                _numeric_text_input_optional(
                    "Tegangan Sistem (kV)",
                    key=f"{prefix}_voltage_before",
                    placeholder="Masukkan tegangan",
                )
            )

        with col_pf:
            power_factor = (
                _fixed_pf_display(
                    key=f"{prefix}_power_factor"
                )
            )

        if load_current_before is not None:
            st.caption(
                "Arus rata-rata 3 phasa untuk kalkulasi ENS: "
                f"**{load_current_before:,.2f} A**"
            )

    operator_name, dispatcher_up2d_name = (
        _render_operation_staff(
            prefix=prefix,
            existing_row=existing_row,
            disabled=False,
        )
    )

    # ======================================================
    # PIC / CAUSE
    # ======================================================

    pic_options = (
        _build_reference_options(
            get_pics(),
            "pic_code",
        )
    )

    cause_options = (
        _build_reference_options(
            get_causes(),
            "cause_code",
        )
    )

    valid_rules = [
        row
        for row
        in get_cause_rules()
        if (
            str(
                row.get(
                    "status_code"
                )
                or ""
            ).strip()
            == "LEPAS"
        )
    ]

    valid_pic_codes = list(
        dict.fromkeys(
            str(
                row.get(
                    "pic_code"
                )
            )
            for row
            in valid_rules
            if row.get(
                "pic_code"
            )
        )
    )

    if (
        is_history_update
        and existing_row is not None
    ):
        existing_pic = str(
            existing_row.get(
                "pic_code"
            )
            or ""
        )

        if (
            existing_pic
            and existing_pic
            not in valid_pic_codes
        ):
            valid_pic_codes.append(
                existing_pic
            )

    def format_pic(
        value: str,
    ) -> str:
        if value == "":
            return (
                "Pilih PIC"
            )

        return (
            pic_options.get(
                value,
                value,
            )
        )

    with st.container(
        border=True
    ):
        st.markdown(
            "#### PIC & Tujuan Operasi"
        )

        col_pic, col_cause = (
            st.columns(2)
        )

        with col_pic:
            selected_pic_raw = (
                st.selectbox(
                    "PIC Operasi",
                    options=[
                        "",
                        *[
                            code
                            for code
                            in valid_pic_codes
                            if code
                            in pic_options
                        ],
                    ],
                    format_func=(
                        format_pic
                    ),
                    key=(
                        f"{prefix}_pic"
                    ),
                )
            )

        selected_pic = str(
            selected_pic_raw
            or ""
        )

        valid_cause_codes = [
            str(
                row.get(
                    "cause_code"
                )
            )
            for row
            in valid_rules
            if (
                str(
                    row.get(
                        "pic_code"
                    )
                    or ""
                )
                == selected_pic
                and row.get(
                    "cause_code"
                )
            )
        ]

        if (
            is_history_update
            and existing_row is not None
        ):
            existing_cause = str(
                existing_row.get(
                    "cause_code"
                )
                or ""
            )

            if (
                existing_cause
                and existing_cause
                not in valid_cause_codes
            ):
                valid_cause_codes.append(
                    existing_cause
                )

        def format_manuver_cause(
            value: str,
        ) -> str:
            if value == "":
                return (
                    "Pilih tujuan / klasifikasi"
                )

            return (
                cause_options.get(
                    value,
                    value,
                )
            )

        with col_cause:
            selected_cause = (
                st.selectbox(
                    "Tujuan / Klasifikasi Manuver",
                    options=[
                        "",
                        *[
                            code
                            for code
                            in valid_cause_codes
                            if code
                            in cause_options
                        ],
                    ],
                    format_func=(
                        format_manuver_cause
                    ),
                    key=(
                        f"{prefix}_cause"
                    ),
                    disabled=(
                        not bool(
                            selected_pic
                        )
                    ),
                )
            )

        event_description = (
            st.text_area(
                "Keterangan Manuver",
                placeholder=(
                    "Perintah operasi, tujuan manuver, "
                    "kondisi jaringan, dan informasi pendukung..."
                ),
                height=110,
                key=(
                    f"{prefix}_description"
                ),
            )
        )

    # ======================================================
    # SUPPLY
    # ======================================================

    supply_data = (
        _render_supply_restoration(
            prefix=prefix,
            event_date=event_date,
            event_time=event_time,
            voltage_before=_safe_float(voltage_before),
            load_current_before_r=(
                _optional_float(
                    load_current_before_r
                )
            ),
            load_current_before_s=(
                _optional_float(
                    load_current_before_s
                )
            ),
            load_current_before_t=(
                _optional_float(
                    load_current_before_t
                )
            ),
            load_current_before=_safe_float(load_current_before),
            power_factor=float(
                power_factor
            ),
            enabled=True,
        )
    )

    with st.container(
        border=True
    ):
        recovery_description = (
            st.text_area(
                "Keterangan Normalisasi",
                placeholder=(
                    "Feeder tujuan manuver, lokasi switching, "
                    "beban termanuver, sisa padam, "
                    "dan proses normalisasi..."
                ),
                height=100,
                key=(
                    f"{prefix}_"
                    "recovery_description"
                ),
            )
        )

    # ======================================================
    # EVIDENCE
    # ======================================================

    with st.container(
        border=True
    ):
        st.markdown(
            "#### Evidence"
        )

        evidence = (
            st.file_uploader(
                "Upload Evidence (Opsional)",
                type=[
                    "jpg",
                    "jpeg",
                    "png",
                    "pdf",
                ],
                accept_multiple_files=True,
                key=(
                    f"{prefix}_evidence"
                ),
            )
        )

        if evidence:
            st.caption(
                f"{len(evidence)} file dipilih. "
                "Evidence akan diarsipkan ke Google Drive "
                "dan dikirim ke Telegram saat data disimpan."
            )

    # ======================================================
    # COMMON VALIDATION
    # ======================================================

    def validate_form() -> list[str]:
        errors: list[str] = []

        if not selected_pic:
            errors.append(
                "PIC Operasi wajib dipilih."
            )

        if not selected_cause:
            errors.append(
                "Tujuan / klasifikasi manuver wajib dipilih."
            )

        if not operator_name:
            errors.append(
                "Operator Bertugas wajib diisi."
            )

        if not dispatcher_up2d_name:
            errors.append(
                "Dispatcher UP2D wajib diisi."
            )

        errors.extend(
            _validate_three_phase_current(
                current_r=load_current_before_r,
                current_s=load_current_before_s,
                current_t=load_current_before_t,
                label="Arus Beban Sebelum Gangguan",
                required=False,
            )
        )

        errors.extend(
            _validate_three_phase_current(
                current_r=load_current_before_r,
                current_s=load_current_before_s,
                current_t=load_current_before_t,
                label="Arus Beban Sebelum Manuver",
                required=False,
            )
        )

        errors.extend(
            _validate_supply_data(
                event_date=event_date,
                event_time=event_time,
                load_current_before_r=(
                    _optional_float(
                        load_current_before_r
                    )
                ),
                load_current_before_s=(
                    _optional_float(
                        load_current_before_s
                    )
                ),
                load_current_before_t=(
                    _optional_float(
                        load_current_before_t
                    )
                ),
                load_current_before=_safe_float(load_current_before),
                supply_data=(
                    supply_data
                ),
            )
        )

        return errors

    # ======================================================
    # UPDATE HISTORY MANUVER
    # ======================================================

    if is_history_update:
        st.divider()

        col_back, col_save = (
            st.columns(
                [1, 2]
            )
        )

        with col_back:
            back_clicked = (
                st.button(
                    "Kembali ke Riwayat",
                    use_container_width=True,
                    key=(
                        "history_manuver_back"
                    ),
                )
            )

        if back_clicked:
            _return_to_source()
            return

        with col_save:
            save_clicked = (
                st.button(
                    "Simpan Perubahan",
                    type="primary",
                    use_container_width=True,
                    key=(
                        "history_manuver_save"
                    ),
                )
            )

        if not save_clicked:
            return

        if existing_row is None:
            st.error(
                "Data riwayat Manuver tidak ditemukan."
            )
            return

        errors = (
            validate_form()
        )

        if errors:
            for error in errors:
                st.error(
                    error
                )

            return

        user_id = (
            get_current_user_id()
        )

        if user_id is None:
            st.error(
                "Session login tidak valid."
            )
            return

        event_id = str(
            existing_row.get(
                "event_id"
            )
            or ""
        )

        payload: dict[
            str,
            Any
        ] = {
            "event_date":
                event_date.isoformat(),

            "event_time":
                event_time.isoformat(),

            "load_current_before_r_a":
                _optional_float(
                    load_current_before_r
                ),

            "load_current_before_s_a":
                _optional_float(
                    load_current_before_s
                ),

            "load_current_before_t_a":
                _optional_float(
                    load_current_before_t
                ),

            # Legacy average dipertahankan sementara.
            "load_current_before_a":
                _optional_float(
                    load_current_before
                ),

            "voltage_before_kv":
                (
                    _optional_float(voltage_before)
                ),

            "power_factor_before":
                0.85,

            "operator_name":
                operator_name,

            "dispatcher_up2d_name":
                dispatcher_up2d_name,

            "pic_code":
                selected_pic,

            "cause_code":
                str(
                    selected_cause
                ),

            "event_description":
                (
                    event_description.strip()
                    or None
                ),

            "recovery_description":
                (
                    recovery_description.strip()
                    or None
                ),

            "updated_by":
                user_id,
        }

        payload.update(
            _build_supply_payload(
                supply_data
            )
        )

        try:
            with st.spinner(
                "Menyimpan perubahan riwayat..."
            ):
                update_event(
                    event_id=event_id,
                    payload=payload,
                )

            st.session_state[
                "history_flash_message"
            ] = (
                "Perubahan riwayat Manuver "
                "berhasil disimpan."
            )

            _return_to_source()

        except Exception as exc:
            error_text = str(
                exc
            )

            if (
                "EVENT_PERIOD_ALREADY_APPROVED"
                in error_text
                or "EVENT_LOCKED_BY_APPROVED_MONTHLY_REPORT"
                in error_text
            ):
                st.error(
                    "Riwayat Manuver tidak dapat diubah karena "
                    "Laporan Bulanan pada periode tersebut "
                    "sudah Terverifikasi."
                )

                st.caption(
                    "Silakan hubungi Evaluator / Admin / Super Admin "
                    "untuk mengembalikan Laporan Bulanan ke Draft."
                )

            else:
                st.error(
                    "Perubahan riwayat Manuver gagal disimpan."
                )

                st.exception(
                    exc
                )

        return

    # ======================================================
    # CREATE MANUVER
    # ======================================================

    st.divider()

    save_clicked = (
        st.button(
            "Simpan Data Manuver",
            type="primary",
            use_container_width=True,
            key=(
                "create_save_manuver"
            ),
        )
    )

    if not save_clicked:
        return

    errors = (
        validate_form()
    )

    if selected is None:
        errors.insert(
            0,
            "Penyulang belum dipilih.",
        )

    if errors:
        for error in errors:
            st.error(
                error
            )

        return

    if selected is None:
        return

    user_id = (
        get_current_user_id()
    )

    if user_id is None:
        st.error(
            "Session login tidak valid."
        )
        return

    payload: dict[
        str,
        Any
    ] = {
        "event_type_code":
            "MANUVER",

        "penyulang_id":
            str(
                selected[
                    "penyulang_id"
                ]
            ),

        "pmt_status_code":
            "LEPAS",

        "pic_code":
            selected_pic,

        "cause_code":
            str(
                selected_cause
            ),

        "event_date":
            event_date.isoformat(),

        "event_time":
            event_time.isoformat(),

        "load_current_before_r_a":
            _optional_float(
                load_current_before_r
            ),

        "load_current_before_s_a":
            _optional_float(
                load_current_before_s
            ),

        "load_current_before_t_a":
            _optional_float(
                load_current_before_t
            ),

        # Legacy average dipertahankan sementara.
        "load_current_before_a":
            _optional_float(
                load_current_before
            ),

        "voltage_before_kv":
            _optional_float(voltage_before),

        "power_factor_before":
                0.85,

        "operator_name":
            operator_name,

        "dispatcher_up2d_name":
            dispatcher_up2d_name,

        "fault_current_r_a":
            None,

        "fault_current_s_a":
            None,

        "fault_current_t_a":
            None,

        "fault_current_n_a":
            None,

        "phase_r":
            False,

        "phase_s":
            False,

        "phase_t":
            False,

        "phase_n":
            False,

        "annunciator_code":
            None,

        "event_description":
            (
                event_description.strip()
                or None
            ),

        "recovery_description":
            (
                recovery_description.strip()
                or None
            ),

        "created_by":
            user_id,

        "updated_by":
            user_id,
    }

    payload.update(
        _build_supply_payload(
            supply_data
        )
    )

    try:
        with st.spinner(
            "Menyimpan data manuver..."
        ):
            saved_event = (
                create_event(
                    payload
                )
            )

            event_id = str(
                saved_event[
                    "event_id"
                ]
            )

            cause_name = (
                cause_options.get(
                    str(
                        selected_cause
                    )
                )
                or str(
                    selected_cause
                )
            )

            drive_count, drive_errors = (
                drive_service.upload_evidence_files(
                    uploaded_files=list(
                        evidence
                        or []
                    ),
                    event_id=event_id,
                    event_type="MANUVER",
                    hierarchy=selected,
                    event_date=event_date.isoformat(),
                    event_time=event_time.isoformat(),
                    cause_name=cause_name,
                )
            )

            telegram_payload = dict(
                payload
            )

            telegram_payload[
                "created_by_name"
            ] = _current_input_user_name()

            telegram_ok, telegram_message = (
                telegram_service.send_event_notification(
                    event_id=event_id,
                    event_type="MANUVER",
                    hierarchy=selected,
                    payload=telegram_payload,
                    cause_name=cause_name,
                    pic_name=(
                        pic_options.get(
                            selected_pic
                        )
                    ),
                    uploaded_files=list(
                        evidence
                        or []
                    ),
                )
            )

        drive_ok = (
            not drive_errors
        )

        drive_message = (
            (
                f"{drive_count} evidence berhasil diarsipkan ke Google Drive."
                if drive_count > 0
                else "Tidak ada evidence yang diunggah."
            )
            if drive_ok
            else (
                "Sebagian evidence gagal diarsipkan ke Google Drive: "
                + " | ".join(
                    drive_errors
                )
            )
        )

        _set_input_success(
            event_id=event_id,
            event_type="MANUVER",
            telegram_ok=telegram_ok,
            telegram_message=telegram_message,
            drive_ok=drive_ok,
            drive_message=drive_message,
        )

        st.rerun()

    except Exception as exc:
        error_text = str(
            exc
        )

        if (
            "EVENT_PERIOD_ALREADY_APPROVED"
            in error_text
            or "EVENT_LOCKED_BY_APPROVED_MONTHLY_REPORT"
            in error_text
        ):
            st.error(
                "Periode laporan sudah Terverifikasi. "
                "Data Manuver tidak dapat disimpan."
            )

            st.caption(
                "Silakan hubungi Evaluator / Admin / Super Admin "
                "untuk mengembalikan Laporan Bulanan ke Draft."
            )

        else:
            st.error(
                "Data manuver gagal disimpan."
            )

            st.exception(
                exc
            )



# ==========================================================
# SUCCESS / RESET
# ==========================================================


def _clear_create_form_state() -> None:
    """
    Reset seluruh widget CREATE tanpa mengganggu session login,
    mode edit, atau state halaman lain.
    """

    removable_prefixes = (
        "create_gangguan_",
        "create_manuver_",
        "input_event_",
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

    st.session_state.pop(
        "input_event_type",
        None,
    )


def _set_input_success(
    *,
    event_id: str,
    event_type: str,
    telegram_ok: bool | None = None,
    telegram_message: str | None = None,
    drive_ok: bool | None = None,
    drive_message: str | None = None,
) -> None:
    st.session_state[
        "input_success_dialog"
    ] = {
        "event_id":
            event_id,

        "event_type":
            event_type,

        "telegram_ok":
            telegram_ok,

        "telegram_message":
            telegram_message,

        "drive_ok":
            drive_ok,

        "drive_message":
            drive_message,
    }


@st.dialog(
    "Data Berhasil Disimpan",
    width="small",
)
def _render_success_dialog(
    event_id: str,
    event_type: str,
    telegram_ok: bool | None,
    telegram_message: str | None,
    drive_ok: bool | None,
    drive_message: str | None,
) -> None:
    label = (
        "Gangguan"
        if event_type
        == "GANGGUAN"
        else "Manuver"
    )

    st.success(
        f"Data {label} berhasil disimpan."
    )

    st.caption(
        "Pilih langkah berikutnya."
    )

    if telegram_ok is True:
        st.caption(
            "📨 Notifikasi Telegram berhasil dikirim."
        )

    elif telegram_ok is False:
        st.warning(
            "Data sudah tersimpan, tetapi notifikasi Telegram gagal dikirim."
        )

        if telegram_message:
            st.caption(
                telegram_message
            )

    if drive_ok is True:
        if drive_message:
            st.caption(
                f"☁️ {drive_message}"
            )

    elif drive_ok is False:
        st.warning(
            "Data tersimpan, tetapi arsip Google Drive "
            "tidak seluruhnya berhasil."
        )

        if drive_message:
            st.caption(
                drive_message
            )

    col_new, col_history = (
        st.columns(2)
    )

    with col_new:
        if st.button(
            "Input Baru",
            icon=":material/add_circle:",
            type="primary",
            use_container_width=True,
            key="success_input_new",
        ):
            _clear_create_form_state()

            st.session_state.pop(
                "input_success_dialog",
                None,
            )

            st.rerun()

    with col_history:
        if st.button(
            "Lihat Riwayat",
            icon=":material/history:",
            use_container_width=True,
            key="success_open_history",
        ):
            _clear_create_form_state()

            st.session_state.pop(
                "input_success_dialog",
                None,
            )

            st.switch_page(
                "pages/riwayat_kejadian.py"
            )


def _maybe_render_success_dialog() -> None:
    data = st.session_state.get(
        "input_success_dialog"
    )

    if not isinstance(
        data,
        dict,
    ):
        return

    event_id = str(
        data.get(
            "event_id"
        )
        or ""
    )

    event_type = str(
        data.get(
            "event_type"
        )
        or ""
    ).upper()

    telegram_ok_raw = (
        data.get(
            "telegram_ok"
        )
    )

    telegram_ok: bool | None = (
        telegram_ok_raw
        if isinstance(
            telegram_ok_raw,
            bool,
        )
        else None
    )

    telegram_message = str(
        data.get(
            "telegram_message"
        )
        or ""
    ).strip() or None

    drive_ok_raw = (
        data.get(
            "drive_ok"
        )
    )

    drive_ok: bool | None = (
        drive_ok_raw
        if isinstance(
            drive_ok_raw,
            bool,
        )
        else None
    )

    drive_message = str(
        data.get(
            "drive_message"
        )
        or ""
    ).strip() or None

    if not event_id:
        st.session_state.pop(
            "input_success_dialog",
            None,
        )
        return

    _render_success_dialog(
        event_id=event_id,
        event_type=event_type,
        telegram_ok=telegram_ok,
        telegram_message=telegram_message,
        drive_ok=drive_ok,
        drive_message=drive_message,
    )


# ==========================================================
# PAGE
# ==========================================================


def render_page() -> None:
    render_sidebar()
    _apply_page_style()

    _maybe_render_success_dialog()

    # ======================================================
    # ACCESS GUARD
    # ======================================================
    #
    # CREATE:
    # - INSPECTOR / EVALUATOR / ADMIN / SUPER_ADMIN
    #
    # UPDATE & UPDATE_HISTORY:
    # - user harus memiliki capability Edit
    #
    # Sidebar hanya mengatur visibilitas menu.
    # Guard halaman tetap diperlukan agar user tidak dapat
    # membuka halaman secara langsung melalui URL.
    # RLS Supabase tetap menjadi pengaman terakhir.
    # ======================================================

    mode = str(
        st.session_state.get(
            "input_mode",
            "CREATE",
        )
    ).upper()

    if mode == "CREATE":
        if not can_input():
            st.error(
                "Anda tidak memiliki akses untuk "
                "Input Gangguan / Manuver."
            )

            st.caption(
                "Hubungi administrator apabila Anda "
                "memerlukan akses input pada unit kerja."
            )

            return

    elif mode in {
        "UPDATE",
        "UPDATE_HISTORY",
    }:
        if not can_edit():
            st.error(
                "Anda tidak memiliki akses untuk "
                "mengubah data operasi."
            )

            st.caption(
                "Akses Edit mengikuti role dan scope unit "
                "yang telah ditetapkan."
            )

            return

    else:
        # Mode tidak dikenali. Bersihkan state agar halaman
        # kembali aman ke mode CREATE.
        _clear_edit_mode()

        if not can_input():
            st.error(
                "Anda tidak memiliki akses untuk "
                "Input Gangguan / Manuver."
            )

            return

        mode = "CREATE"

    _migrate_create_form_state()
    _prepare_create_state()

    edit_event_id_raw = (
        st.session_state.get(
            "edit_event_id"
        )
    )

    edit_event_id = (
        str(
            edit_event_id_raw
        )
        if edit_event_id_raw
        else None
    )

    existing_row: (
        EventRow | None
    ) = None

    # ======================================================
    # ACTIVE UPDATE
    # ======================================================

    if (
        mode == "UPDATE"
        and edit_event_id
    ):
        try:
            existing_row = (
                get_event_by_id(
                    edit_event_id
                )
            )

        except Exception as exc:
            st.error(
                "Data Gangguan Aktif tidak dapat dibaca."
            )

            st.exception(
                exc
            )
            return

        if existing_row is None:
            st.error(
                "Data Gangguan Aktif tidak ditemukan."
            )
            return

        event_type = str(
            existing_row.get(
                "event_type_code"
            )
            or ""
        )

        if (
            event_type
            != "GANGGUAN"
        ):
            st.error(
                "Mode Pemulihan dari Gangguan Aktif "
                "hanya dapat membuka Gangguan."
            )
            return

        _prepare_gangguan_existing_state(
            event_id=(
                edit_event_id
            ),
            row=(
                existing_row
            ),
            prefix=(
                "update_gangguan"
            ),
        )

        if st.button(
            "← Kembali ke Gangguan Aktif",
            key=(
                "update_top_back"
            ),
        ):
            _return_to_source()
            return

        st.title(
            "Pemulihan & Normalisasi Gangguan"
        )

        st.caption(
            "Lengkapi pemulihan beban, normalisasi PMT, "
            "dan Counter PMT setelah operasi."
        )

        _render_update_identity(
            existing_row
        )

        with st.container(
            border=True
        ):
            col_1, col_2, col_3 = (
                st.columns(3)
            )

            with col_1:
                st.caption(
                    "Status Record"
                )

                st.write(
                    f"**{existing_row.get('record_status_name') or existing_row.get('record_status') or '-'}**"
                )

            with col_2:
                st.caption(
                    "Status Suplai Saat Ini"
                )

                st.write(
                    f"**{existing_row.get('supply_status_name') or '-'}**"
                )

            with col_3:
                st.caption(
                    "Status PMT Saat Ini"
                )

                st.write(
                    f"**{existing_row.get('recovery_status_name') or 'Belum Normal'}**"
                )

        _render_gangguan_form(
            mode="UPDATE",
            selected=None,
            existing_row=(
                existing_row
            ),
        )

        return

    # ======================================================
    # HISTORY UPDATE
    # ======================================================

    if (
        mode
        == "UPDATE_HISTORY"
        and edit_event_id
    ):
        try:
            existing_row = (
                get_event_by_id(
                    edit_event_id
                )
            )

        except Exception as exc:
            st.error(
                "Data Riwayat Operasi tidak dapat dibaca."
            )

            st.exception(
                exc
            )
            return

        if existing_row is None:
            st.error(
                "Data Riwayat Operasi tidak ditemukan."
            )

            if st.button(
                "← Kembali ke Riwayat Operasi",
                key=(
                    "history_missing_back"
                ),
            ):
                _return_to_source()

            return

        event_type = str(
            existing_row.get(
                "event_type_code"
            )
            or ""
        ).strip()


        # ==================================================
        # RECORD YANG SEDANG DIEDIT
        # ==================================================

        selected_code = str(
            existing_row.get(
                "penyulang_code"
            )
            or "-"
        )

        selected_name = str(
            existing_row.get(
                "penyulang_name"
            )
            or "-"
        )

        selected_date = (
            _parse_date(
                existing_row.get(
                    "event_date"
                )
            )
        )

        selected_time = (
            _parse_time(
                existing_row.get(
                    "event_time"
                )
            )
        )

        selected_date_text = (
            selected_date.strftime(
                "%d-%m-%Y"
            )
            if selected_date
            else "-"
        )

        selected_time_text = (
            selected_time.strftime(
                "%H:%M"
            )
            if selected_time
            else "-"
        )

        st.caption(
            f"Record yang diedit: "
            f"**{selected_code} — {selected_name}** • "
            f"{selected_date_text} {selected_time_text}"
        )


        if st.button(
            "← Kembali ke Riwayat Operasi",
            key=(
                "history_top_back"
            ),
        ):
            _return_to_source()
            return

        st.title(
            "Edit Riwayat Operasi"
        )

        st.caption(
            "Perbaiki data operasi yang sudah tersimpan. "
            "Durasi pemadaman dan ENS akan dihitung ulang "
            "oleh database setelah disimpan."
        )

        _render_update_identity(
            existing_row
        )

        with st.container(
            border=True
        ):
            col_type, col_status = (
                st.columns(2)
            )

            with col_type:
                st.caption(
                    "Jenis Operasi"
                )

                st.write(
                    f"**{existing_row.get('event_type_name') or event_type or '-'}**"
                )

            with col_status:
                st.caption(
                    "Status Record"
                )

                st.write(
                    f"**{existing_row.get('record_status_name') or existing_row.get('record_status') or '-'}**"
                )

        if (
            event_type
            == "GANGGUAN"
        ):
            _prepare_gangguan_existing_state(
                event_id=(
                    edit_event_id
                ),
                row=(
                    existing_row
                ),
                prefix=(
                    "history_gangguan"
                ),
            )

            _render_gangguan_form(
                mode=(
                    "UPDATE_HISTORY"
                ),
                selected=None,
                existing_row=(
                    existing_row
                ),
            )

        elif (
            event_type
            == "MANUVER"
        ):
            _prepare_manuver_existing_state(
                event_id=(
                    edit_event_id
                ),
                row=(
                    existing_row
                ),
                prefix=(
                    "history_manuver"
                ),
            )

            _render_manuver_form(
                mode=(
                    "UPDATE_HISTORY"
                ),
                selected=None,
                existing_row=(
                    existing_row
                ),
            )

        else:
            st.error(
                "Jenis operasi pada record tidak dikenali."
            )

        return

    # ======================================================
    # CREATE
    # ======================================================

    st.title(
        "Input Gangguan / Manuver"
    )

    st.caption(
        "Pencatatan operasi Penyulang 20 kV, "
        "proteksi, pemulihan beban, dan normalisasi sistem."
    )

    with st.container(
        border=True
    ):
        st.markdown(
            "#### Identitas Penyulang"
        )

        selected = (
            render_hierarchy_selector(
                key_prefix=(
                    "input_event"
                )
            )
        )

        if selected is None:
            st.caption(
                "Pilih ULTG, Gardu Induk, Bay, "
                "dan Penyulang untuk mengaktifkan form."
            )

        else:
            code = str(
                selected.get(
                    "penyulang_code"
                )
                or "-"
            )

            name = str(
                selected.get(
                    "penyulang_name"
                )
                or "-"
            )

            st.caption(
                f"Objek terpilih: "
                f"**{code} — {name}**"
            )

    location_ready = (
        selected is not None
    )

    with st.container(
        border=True
    ):
        st.markdown(
            "#### Jenis Operasi"
        )

        def format_operation_type(
            value: str,
        ) -> str:
            if (
                value
                == "GANGGUAN"
            ):
                return (
                    "Gangguan"
                )

            return (
                "Manuver"
            )

        operation_type = (
            st.segmented_control(
                "Jenis Operasi",
                options=[
                    "GANGGUAN",
                    "MANUVER",
                ],
                default=(
                    "GANGGUAN"
                ),
                format_func=(
                    format_operation_type
                ),
                key=(
                    "input_event_type"
                ),
                label_visibility=(
                    "collapsed"
                ),
                disabled=(
                    not location_ready
                ),
            )
        )

    if not location_ready:
        return

    if (
        operation_type
        is None
    ):
        operation_type = (
            "GANGGUAN"
        )

    if (
        operation_type
        == "GANGGUAN"
    ):
        _render_gangguan_form(
            mode="CREATE",
            selected=(
                selected
            ),
            existing_row=None,
        )

    else:
        _render_manuver_form(
            mode="CREATE",
            selected=(
                selected
            ),
            existing_row=None,
        )


render_page()