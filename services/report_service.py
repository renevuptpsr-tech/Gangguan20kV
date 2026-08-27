from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any, cast

import pandas as pd
import streamlit as st

from services.supabase_client import get_supabase_client


# ==========================================================
# TYPES
# ==========================================================

ReportRow = dict[str, Any]
MonthlyReportRow = dict[str, Any]


# ==========================================================
# CONSTANTS / MAPPING
# ==========================================================

TRIP_RELAY_CODES: tuple[str, ...] = (
    "OCR_INST",
    "OCR_TD",
    "GFR_INST",
    "GFR_TD",
    "UFR_UVLS",
    "OLS",
    "RTN",
)

TRIP_GROUP_MAPPING: dict[str, set[str]] = {
    "OCR_GFR": {
        "OCR_INST",
        "OCR_TD",
        "GFR_INST",
        "GFR_TD",
    },
    "UFR_UVLS": {
        "UFR_UVLS",
    },
    "OLS": {
        "OLS",
    },
    "RTN": {
        "RTN",
    },
}

LEPAS_CAUSE_MAPPING: dict[str, str] = {
    # HAR
    "PEMELIHARAAN_2_TAHUNAN": "HAR",
    "PEKERJAAN_ULTG_SESUAI_ROB": "HAR",
    "MANUVER_PEMBEBANAN_TRAFO_DAYA": "HAR",

    # DEFISIT
    "DEFISIT_SYSTEM": "DEFISIT",

    # ULP
    "PEMELIHARAAN_UP2D_UP3_ULP": "ULP",

    # EMERGENCY UPT
    "EMERGENCY_TCS_FAIL": "EMERGENCY_UPT",
    "EMERGENCY_DESISAN_KUBIKEL": "EMERGENCY_UPT",
    "EMERGENCY_SUPPLY_DC_MATI": "EMERGENCY_UPT",
    "EMERGENCY_ANOMALI_KUBIKEL_20KV": "EMERGENCY_UPT",

    # EMERGENCY ULP / UP2D
    "EMERGENCY_UP2D_UP3_ULP": "EMERGENCY_ULP",
    "EMERGENCY_BEBAN_PINCANG": "EMERGENCY_ULP",

    # BLACKOUT
    "EMERGENCY_HILANG_TEGANGAN": "BLACKOUT",

    # Belum memiliki kolom khusus pada template lama.
    "ENERGIZE_FEEDER_BARU": "LAINNYA",
    "PEKERJAAN_PIHAK_3": "LAINNYA",
}

LEPAS_CATEGORIES: tuple[str, ...] = (
    "HAR",
    "DEFISIT",
    "ULP",
    "EMERGENCY_UPT",
    "EMERGENCY_ULP",
    "BLACKOUT",
    "LAINNYA",
)

MONTHLY_REPORT_STATUSES: tuple[str, ...] = (
    "DRAFT",
    "SUBMITTED",
    "APPROVED",
    "REJECTED",
)


# ==========================================================
# GENERIC HELPERS
# ==========================================================


def _safe_string(
    value: Any,
    default: str = "",
) -> str:
    if value is None:
        return default

    text = str(value).strip()
    return text or default


def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(
    value: Any,
) -> float | None:
    """
    Konversi nilai numerik opsional.
    """

    if value is None:
        return None

    try:
        return float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return None


def _phase_current_value(
    row: ReportRow,
    *,
    phase_field: str,
    legacy_field: str,
) -> float | None:
    """
    Membaca arus per phasa.

    Record lama tetap didukung:
    jika kolom R/S/T belum tersedia, gunakan field legacy.
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


def _three_phase_average_from_row(
    row: ReportRow,
    *,
    prefix: str,
    legacy_field: str,
) -> float | None:
    """
    Iavg = (IR + IS + IT) / 3.

    Nilai ini dipertahankan untuk kompatibilitas report template
    lama yang masih menggunakan field 'amp'.
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
        return _optional_float(
            row.get(
                legacy_field
            )
        )

    return (
        current_r
        + current_s
        + current_t
    ) / 3.0


def _safe_int(
    value: Any,
    default: int = 0,
) -> int:
    if value is None:
        return default

    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_code_set(
    value: Any,
) -> set[str]:
    if value is None:
        return set()

    if isinstance(value, list):
        return {
            _safe_string(item).upper()
            for item in value
            if _safe_string(item)
        }

    if isinstance(value, tuple):
        return {
            _safe_string(item).upper()
            for item in value
            if _safe_string(item)
        }

    text = _safe_string(value)

    if not text:
        return set()

    # Fallback jika PostgreSQL ARRAY terbaca sebagai teks.
    text = (
        text
        .replace("{", "")
        .replace("}", "")
        .replace("[", "")
        .replace("]", "")
        .replace('"', "")
    )

    return {
        item.strip().upper()
        for item in text.split(",")
        if item.strip()
    }


def _phase_label(
    row: ReportRow,
) -> str:
    phases: list[str] = []

    if bool(row.get("phase_r")):
        phases.append("R")

    if bool(row.get("phase_s")):
        phases.append("S")

    if bool(row.get("phase_t")):
        phases.append("T")

    if bool(row.get("phase_n")):
        phases.append("N")

    return " ".join(phases)


def _event_date_text(
    value: Any,
) -> str:
    text = _safe_string(value)

    if not text:
        return ""

    return text[:10]


def _event_day(
    value: Any,
) -> int | None:
    text = _event_date_text(value)

    if not text:
        return None

    try:
        return date.fromisoformat(text).day
    except ValueError:
        return None


def _time_hhmm(
    value: Any,
) -> str:
    text = _safe_string(value)

    if not text:
        return ""

    return text[:5]


def _is_trip_event(
    row: ReportRow,
) -> bool:
    pmt_status = _safe_string(
        row.get("pmt_status_code")
    ).upper()

    event_type = _safe_string(
        row.get("event_type_code")
    ).upper()

    return (
        pmt_status == "TRIP"
        or event_type == "GANGGUAN"
    )


def _is_lepas_event(
    row: ReportRow,
) -> bool:
    pmt_status = _safe_string(
        row.get("pmt_status_code")
    ).upper()

    event_type = _safe_string(
        row.get("event_type_code")
    ).upper()

    return (
        pmt_status in {"LEPAS", "BLACKOUT"}
        or event_type == "MANUVER"
    )


def _lepas_category(
    row: ReportRow,
) -> str:
    cause_code = _safe_string(
        row.get("cause_code")
    ).upper()

    pmt_status = _safe_string(
        row.get("pmt_status_code")
    ).upper()

    if pmt_status == "BLACKOUT":
        return "BLACKOUT"

    return LEPAS_CAUSE_MAPPING.get(
        cause_code,
        "LAINNYA",
    )


def _feeder_sort_key(
    row: ReportRow,
) -> tuple[str, str, str, str]:
    return (
        _safe_string(row.get("ultg_name")).upper(),
        _safe_string(row.get("gi_name")).upper(),
        _safe_string(row.get("bay_name")).upper(),
        _safe_string(row.get("penyulang_code")).upper(),
    )


# ==========================================================
# PERIOD
# ==========================================================


def get_month_period(
    report_year: int,
    report_month: int,
) -> tuple[date, date]:
    if report_year < 2000 or report_year > 2100:
        raise ValueError("Tahun laporan tidak valid.")

    if report_month < 1 or report_month > 12:
        raise ValueError("Bulan laporan tidak valid.")

    last_day = monthrange(
        report_year,
        report_month,
    )[1]

    return (
        date(
            report_year,
            report_month,
            1,
        ),
        date(
            report_year,
            report_month,
            last_day,
        ),
    )


# ==========================================================
# SCOPE / FEEDER MASTER
# ==========================================================


@st.cache_data(
    ttl=120,
    show_spinner=False,
)
def get_accessible_feeders() -> list[ReportRow]:
    supabase = get_supabase_client()

    response = (
        supabase
        .table(
            "vw_penyulang_hierarchy_accessible"
        )
        .select(
            "ultg_flc,ultg_name,"
            "gi_flc,gi_name,"
            "bay_flc,bay_name,"
            "penyulang_id,penyulang_code,"
            "penyulang_name,penyulang_short_name,"
            "penyulang_alias,penyulang_is_active,"
            "penyulang_status_code"
        )
        .order(
            "ultg_name"
        )
        .order(
            "gi_name"
        )
        .order(
            "bay_name"
        )
        .order(
            "penyulang_code"
        )
        .execute()
    )

    if not response.data:
        return []

    return cast(
        list[ReportRow],
        response.data,
    )


def filter_feeders_by_scope(
    feeders: list[ReportRow],
    scope_functloc_id: str,
) -> list[ReportRow]:
    scope_id = _safe_string(
        scope_functloc_id
    )

    if not scope_id:
        return []

    filtered = [
        row
        for row in feeders
        if scope_id
        in {
            _safe_string(row.get("ultg_flc")),
            _safe_string(row.get("gi_flc")),
            _safe_string(row.get("bay_flc")),
        }
    ]

    return sorted(
        filtered,
        key=_feeder_sort_key,
    )


# ==========================================================
# MONTHLY EVENT DATA
# ==========================================================


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def load_monthly_events(
    report_year: int,
    report_month: int,
    scope_functloc_id: str,
) -> list[ReportRow]:
    """
    Membaca data bulanan melalui view detail.

    Scope laporan resmi saat ini adalah Gardu Induk (GI).
    RLS view tetap menentukan data yang dapat dilihat user.
    """

    start_date, end_date = get_month_period(
        report_year,
        report_month,
    )

    scope_id = _safe_string(
        scope_functloc_id
    )

    if not scope_id:
        raise ValueError(
            "Scope laporan belum dipilih."
        )

    supabase = get_supabase_client()

    response = (
        supabase
        .table(
            "vw_kejadian_penyulang_detail"
        )
        .select("*")
        .gte(
            "event_date",
            start_date.isoformat(),
        )
        .lte(
            "event_date",
            end_date.isoformat(),
        )
        .order(
            "event_date"
        )
        .order(
            "event_time"
        )
        .execute()
    )

    if not response.data:
        return []

    rows = cast(
        list[ReportRow],
        response.data,
    )

    # Filtering scope dilakukan di Python. Workflow laporan resmi
    # menggunakan scope GI; kompatibilitas ULTG/BAY tetap tidak
    # dihapus pada helper lama agar perubahan bertahap tetap aman.
    scoped_rows = [
        row
        for row in rows
        if scope_id
        in {
            _safe_string(row.get("ultg_flc")),
            _safe_string(row.get("gi_flc")),
            _safe_string(row.get("bay_flc")),
        }
    ]

    # Laporan bulanan tidak memakai record soft-deleted /
    # cancelled sebagai data operasi resmi.
    return [
        row
        for row in scoped_rows
        if _safe_string(
            row.get("record_status")
        ).upper()
        not in {
            "CANCELLED",
            "DELETED",
        }
    ]


def clear_report_cache() -> None:
    get_accessible_feeders.clear()
    load_monthly_events.clear()


# ==========================================================
# TRIP RECAP
# ==========================================================


def build_rekap_trip(
    events: list[ReportRow],
    feeders: list[ReportRow],
) -> pd.DataFrame:
    """
    Rekap Trip mengikuti halaman 1 laporan lama.

    Semua feeder pada scope tetap tampil walaupun tidak
    memiliki kejadian pada bulan tersebut.
    """

    trip_events = [
        row
        for row in events
        if _is_trip_event(row)
    ]

    events_by_feeder: dict[str, list[ReportRow]] = {}

    for event in trip_events:
        feeder_id = _safe_string(
            event.get("penyulang_id")
        )

        if not feeder_id:
            feeder_id = _safe_string(
                event.get("penyulang_code")
            )

        if not feeder_id:
            continue

        events_by_feeder.setdefault(
            feeder_id,
            [],
        ).append(event)

    result: list[dict[str, Any]] = []

    for feeder in feeders:
        feeder_id = _safe_string(
            feeder.get("penyulang_id")
        )

        if not feeder_id:
            feeder_id = _safe_string(
                feeder.get("penyulang_code")
            )

        feeder_events = events_by_feeder.get(
            feeder_id,
            [],
        )

        relay_count = {
            code: 0
            for code in TRIP_RELAY_CODES
        }

        group_count = {
            group: 0
            for group in TRIP_GROUP_MAPPING
        }

        group_minutes = {
            group: 0.0
            for group in TRIP_GROUP_MAPPING
        }

        group_ens = {
            group: 0.0
            for group in TRIP_GROUP_MAPPING
        }

        for event in feeder_events:
            codes = _as_code_set(
                event.get("indikasi_codes")
            )

            for relay_code in TRIP_RELAY_CODES:
                if relay_code in codes:
                    relay_count[
                        relay_code
                    ] += 1

            duration_min = _safe_float(
                event.get(
                    "customer_outage_duration_min"
                )
            )

            ens_kwh = _safe_float(
                event.get(
                    "ens_kwh"
                )
            )

            # Satu event dihitung maksimal satu kali pada
            # masing-masing group. Event boleh masuk lebih
            # dari satu group jika memang beberapa kategori
            # relay berbeda bekerja bersamaan.
            for group, members in TRIP_GROUP_MAPPING.items():
                if codes.intersection(
                    members
                ):
                    group_count[group] += 1
                    group_minutes[group] += (
                        duration_min
                    )
                    group_ens[group] += (
                        ens_kwh
                    )

        result.append(
            {
                "ultg_flc":
                    feeder.get("ultg_flc"),

                "ultg_name":
                    feeder.get("ultg_name"),

                "gi_flc":
                    feeder.get("gi_flc"),

                "gi_name":
                    feeder.get("gi_name"),

                "bay_flc":
                    feeder.get("bay_flc"),

                "bay_name":
                    feeder.get("bay_name"),

                "penyulang_id":
                    feeder.get("penyulang_id"),

                "feeder":
                    _safe_string(
                        feeder.get(
                            "penyulang_code"
                        )
                    ),

                "feeder_name":
                    _safe_string(
                        feeder.get(
                            "penyulang_name"
                        )
                    ),

                "feeder_alias":
                    _safe_string(
                        feeder.get(
                            "penyulang_alias"
                        )
                    ),

                # RELE YANG BEKERJA
                "ocr_inst":
                    relay_count["OCR_INST"],

                "ocr_td":
                    relay_count["OCR_TD"],

                "gfr_inst":
                    relay_count["GFR_INST"],

                "gfr_td":
                    relay_count["GFR_TD"],

                "ufr_uvls_relay":
                    relay_count["UFR_UVLS"],

                "ols_relay":
                    relay_count["OLS"],

                "rtn_relay":
                    relay_count["RTN"],

                # JUMLAH TRIP
                "trip_ocr_gfr":
                    group_count["OCR_GFR"],

                "trip_ufr_uvls":
                    group_count["UFR_UVLS"],

                "trip_ols":
                    group_count["OLS"],

                "trip_rtn":
                    group_count["RTN"],

                "total_trip_event":
                    len(feeder_events),

                # JUMLAH WAKTU / MENIT
                "menit_ocr_gfr":
                    round(
                        group_minutes[
                            "OCR_GFR"
                        ],
                        2,
                    ),

                "menit_ufr_uvls":
                    round(
                        group_minutes[
                            "UFR_UVLS"
                        ],
                        2,
                    ),

                "menit_ols":
                    round(
                        group_minutes[
                            "OLS"
                        ],
                        2,
                    ),

                "menit_rtn":
                    round(
                        group_minutes[
                            "RTN"
                        ],
                        2,
                    ),

                "total_menit":
                    round(
                        sum(
                            _safe_float(
                                event.get(
                                    "customer_outage_duration_min"
                                )
                            )
                            for event
                            in feeder_events
                        ),
                        2,
                    ),

                # KWH PADAM
                "kwh_ocr_gfr":
                    round(
                        group_ens[
                            "OCR_GFR"
                        ],
                        4,
                    ),

                "kwh_ufr_uvls":
                    round(
                        group_ens[
                            "UFR_UVLS"
                        ],
                        4,
                    ),

                "kwh_ols":
                    round(
                        group_ens[
                            "OLS"
                        ],
                        4,
                    ),

                "kwh_rtn":
                    round(
                        group_ens[
                            "RTN"
                        ],
                        4,
                    ),

                "total_kwh":
                    round(
                        sum(
                            _safe_float(
                                event.get(
                                    "ens_kwh"
                                )
                            )
                            for event
                            in feeder_events
                        ),
                        4,
                    ),
            }
        )

    return pd.DataFrame(result)


# ==========================================================
# LEPAS RECAP
# ==========================================================


def build_rekap_lepas(
    events: list[ReportRow],
    feeders: list[ReportRow],
) -> pd.DataFrame:
    """
    Rekap Lepas mengikuti halaman 2 laporan lama.

    BLACKOUT ikut kelompok laporan Lepas.
    Cause yang belum memiliki kategori lama masuk LAINNYA.
    """

    lepas_events = [
        row
        for row in events
        if _is_lepas_event(row)
        and not _is_trip_event(row)
    ]

    events_by_feeder: dict[str, list[ReportRow]] = {}

    for event in lepas_events:
        feeder_id = _safe_string(
            event.get("penyulang_id")
        )

        if not feeder_id:
            feeder_id = _safe_string(
                event.get("penyulang_code")
            )

        if not feeder_id:
            continue

        events_by_feeder.setdefault(
            feeder_id,
            [],
        ).append(event)

    result: list[dict[str, Any]] = []

    for feeder in feeders:
        feeder_id = _safe_string(
            feeder.get("penyulang_id")
        )

        if not feeder_id:
            feeder_id = _safe_string(
                feeder.get("penyulang_code")
            )

        feeder_events = events_by_feeder.get(
            feeder_id,
            [],
        )

        count_by_category = {
            category: 0
            for category in LEPAS_CATEGORIES
        }

        minutes_by_category = {
            category: 0.0
            for category in LEPAS_CATEGORIES
        }

        ens_by_category = {
            category: 0.0
            for category in LEPAS_CATEGORIES
        }

        for event in feeder_events:
            category = _lepas_category(
                event
            )

            count_by_category[
                category
            ] += 1

            minutes_by_category[
                category
            ] += _safe_float(
                event.get(
                    "customer_outage_duration_min"
                )
            )

            ens_by_category[
                category
            ] += _safe_float(
                event.get(
                    "ens_kwh"
                )
            )

        result.append(
            {
                "ultg_flc":
                    feeder.get("ultg_flc"),

                "ultg_name":
                    feeder.get("ultg_name"),

                "gi_flc":
                    feeder.get("gi_flc"),

                "gi_name":
                    feeder.get("gi_name"),

                "bay_flc":
                    feeder.get("bay_flc"),

                "bay_name":
                    feeder.get("bay_name"),

                "penyulang_id":
                    feeder.get("penyulang_id"),

                "feeder":
                    _safe_string(
                        feeder.get(
                            "penyulang_code"
                        )
                    ),

                "feeder_name":
                    _safe_string(
                        feeder.get(
                            "penyulang_name"
                        )
                    ),

                "feeder_alias":
                    _safe_string(
                        feeder.get(
                            "penyulang_alias"
                        )
                    ),

                # DATA LEPAS
                "lepas_har":
                    count_by_category["HAR"],

                "lepas_defisit":
                    count_by_category["DEFISIT"],

                "lepas_ulp":
                    count_by_category["ULP"],

                "lepas_emergency_upt":
                    count_by_category[
                        "EMERGENCY_UPT"
                    ],

                "lepas_emergency_ulp":
                    count_by_category[
                        "EMERGENCY_ULP"
                    ],

                "lepas_blackout":
                    count_by_category[
                        "BLACKOUT"
                    ],

                "lepas_lainnya":
                    count_by_category[
                        "LAINNYA"
                    ],

                "jumlah_lepas":
                    len(feeder_events),

                # JUMLAH WAKTU / MENIT
                "menit_har":
                    round(
                        minutes_by_category[
                            "HAR"
                        ],
                        2,
                    ),

                "menit_defisit":
                    round(
                        minutes_by_category[
                            "DEFISIT"
                        ],
                        2,
                    ),

                "menit_ulp":
                    round(
                        minutes_by_category[
                            "ULP"
                        ],
                        2,
                    ),

                "menit_emergency_upt":
                    round(
                        minutes_by_category[
                            "EMERGENCY_UPT"
                        ],
                        2,
                    ),

                "menit_emergency_ulp":
                    round(
                        minutes_by_category[
                            "EMERGENCY_ULP"
                        ],
                        2,
                    ),

                "menit_blackout":
                    round(
                        minutes_by_category[
                            "BLACKOUT"
                        ],
                        2,
                    ),

                "menit_lainnya":
                    round(
                        minutes_by_category[
                            "LAINNYA"
                        ],
                        2,
                    ),

                "total_menit":
                    round(
                        sum(
                            minutes_by_category.values()
                        ),
                        2,
                    ),

                # KWH PADAM
                "kwh_har":
                    round(
                        ens_by_category[
                            "HAR"
                        ],
                        4,
                    ),

                "kwh_defisit":
                    round(
                        ens_by_category[
                            "DEFISIT"
                        ],
                        4,
                    ),

                "kwh_ulp":
                    round(
                        ens_by_category[
                            "ULP"
                        ],
                        4,
                    ),

                "kwh_emergency_upt":
                    round(
                        ens_by_category[
                            "EMERGENCY_UPT"
                        ],
                        4,
                    ),

                "kwh_emergency_ulp":
                    round(
                        ens_by_category[
                            "EMERGENCY_ULP"
                        ],
                        4,
                    ),

                "kwh_blackout":
                    round(
                        ens_by_category[
                            "BLACKOUT"
                        ],
                        4,
                    ),

                "kwh_lainnya":
                    round(
                        ens_by_category[
                            "LAINNYA"
                        ],
                        4,
                    ),

                "total_kwh":
                    round(
                        sum(
                            ens_by_category.values()
                        ),
                        4,
                    ),
            }
        )

    return pd.DataFrame(result)


# ==========================================================
# DETAIL TRIP
# ==========================================================


def build_detail_trip(
    events: list[ReportRow],
) -> pd.DataFrame:
    result: list[dict[str, Any]] = []

    trip_events = sorted(
        (
            row
            for row in events
            if _is_trip_event(row)
        ),
        key=lambda row: (
            _event_date_text(
                row.get("event_date")
            ),
            _time_hhmm(
                row.get("event_time")
            ),
            _safe_string(
                row.get("penyulang_code")
            ),
        ),
    )

    for index, row in enumerate(
        trip_events,
        start=1,
    ):
        result.append(
            {
                "no":
                    index,

                "event_id":
                    row.get("event_id"),

                "nama_penyulang":
                    _safe_string(
                        row.get(
                            "penyulang_code"
                        )
                    ),

                "penyulang_name":
                    _safe_string(
                        row.get(
                            "penyulang_name"
                        )
                    ),

                "penyulang_alias":
                    _safe_string(
                        row.get(
                            "penyulang_alias"
                        )
                    ),

                "kondisi":
                    "TRIP",

                "tgl":
                    _event_day(
                        row.get(
                            "event_date"
                        )
                    ),

                "tanggal":
                    _event_date_text(
                        row.get(
                            "event_date"
                        )
                    ),

                "pkl":
                    _time_hhmm(
                        row.get(
                            "event_time"
                        )
                    ),

                # Arus beban sebelum gangguan - 3 phasa
                "amp_r":
                    _phase_current_value(
                        row,
                        phase_field="load_current_before_r_a",
                        legacy_field="load_current_before_a",
                    ),

                "amp_s":
                    _phase_current_value(
                        row,
                        phase_field="load_current_before_s_a",
                        legacy_field="load_current_before_a",
                    ),

                "amp_t":
                    _phase_current_value(
                        row,
                        phase_field="load_current_before_t_a",
                        legacy_field="load_current_before_a",
                    ),

                # Legacy average tetap dipertahankan sementara
                # agar template/export lama tidak langsung rusak.
                "amp":
                    _three_phase_average_from_row(
                        row,
                        prefix="load_current_before",
                        legacy_field="load_current_before_a",
                    ),

                "kv":
                    row.get(
                        "voltage_before_kv"
                    ),

                "r":
                    row.get(
                        "fault_current_r_a"
                    ),

                "s":
                    row.get(
                        "fault_current_s_a"
                    ),

                "t":
                    row.get(
                        "fault_current_t_a"
                    ),

                "n":
                    row.get(
                        "fault_current_n_a"
                    ),

                "pemulihan_kondisi":
                    _safe_string(
                        row.get(
                            "recovery_status_name"
                        ),
                        _safe_string(
                            row.get(
                                "recovery_status_code"
                            )
                        ),
                    ),

                "pemulihan_tgl":
                    _event_day(
                        row.get(
                            "recovery_date"
                        )
                    ),

                "pemulihan_tanggal":
                    _event_date_text(
                        row.get(
                            "recovery_date"
                        )
                    ),

                "pemulihan_pkl":
                    _time_hhmm(
                        row.get(
                            "recovery_time"
                        )
                    ),

                # Arus beban setelah pemulihan / operasi - 3 phasa
                "amp_after_r":
                    _phase_current_value(
                        row,
                        phase_field="load_current_after_r_a",
                        legacy_field="load_current_after_a",
                    ),

                "amp_after_s":
                    _phase_current_value(
                        row,
                        phase_field="load_current_after_s_a",
                        legacy_field="load_current_after_a",
                    ),

                "amp_after_t":
                    _phase_current_value(
                        row,
                        phase_field="load_current_after_t_a",
                        legacy_field="load_current_after_a",
                    ),

                "amp_after":
                    _three_phase_average_from_row(
                        row,
                        prefix="load_current_after",
                        legacy_field="load_current_after_a",
                    ),

                # Pemulihan beban / manuver.
                # Gangguan Trip dapat dipulihkan melalui feeder asal,
                # manuver penuh, maupun manuver sebagian.
                "supply_status_code":
                    _safe_string(
                        row.get(
                            "supply_status_code"
                        )
                    ),

                "supply_status_name":
                    _safe_string(
                        row.get(
                            "supply_status_name"
                        ),
                        _safe_string(
                            row.get(
                                "supply_status_code"
                            )
                        ),
                    ),

                "supply_restored_date":
                    _event_date_text(
                        row.get(
                            "supply_restored_date"
                        )
                    ),

                "supply_restored_time":
                    _time_hhmm(
                        row.get(
                            "supply_restored_time"
                        )
                    ),

                "maneuvered_r":
                    _phase_current_value(
                        row,
                        phase_field="maneuvered_current_r_a",
                        legacy_field="maneuvered_current_a",
                    ),

                "maneuvered_s":
                    _phase_current_value(
                        row,
                        phase_field="maneuvered_current_s_a",
                        legacy_field="maneuvered_current_a",
                    ),

                "maneuvered_t":
                    _phase_current_value(
                        row,
                        phase_field="maneuvered_current_t_a",
                        legacy_field="maneuvered_current_a",
                    ),

                "maneuvered":
                    _three_phase_average_from_row(
                        row,
                        prefix="maneuvered_current",
                        legacy_field="maneuvered_current_a",
                    ),

                "remaining_r":
                    _phase_current_value(
                        row,
                        phase_field="remaining_current_r_a",
                        legacy_field="remaining_current_a",
                    ),

                "remaining_s":
                    _phase_current_value(
                        row,
                        phase_field="remaining_current_s_a",
                        legacy_field="remaining_current_a",
                    ),

                "remaining_t":
                    _phase_current_value(
                        row,
                        phase_field="remaining_current_t_a",
                        legacy_field="remaining_current_a",
                    ),

                "remaining":
                    _three_phase_average_from_row(
                        row,
                        prefix="remaining_current",
                        legacy_field="remaining_current_a",
                    ),

                "final_supply_normalized":
                    bool(
                        row.get(
                            "final_supply_normalized"
                        )
                    ),

                "final_supply_normalization_date":
                    _event_date_text(
                        row.get(
                            "final_supply_normalization_date"
                        )
                    ),

                "final_supply_normalization_time":
                    _time_hhmm(
                        row.get(
                            "final_supply_normalization_time"
                        )
                    ),

                "menit":
                    _safe_float(
                        row.get(
                            "customer_outage_duration_min"
                        )
                    ),

                "jlh_kwh":
                    _safe_float(
                        row.get(
                            "ens_kwh"
                        )
                    ),

                "annunciator":
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

                "indikasi":
                    ", ".join(
                        sorted(
                            _as_code_set(
                                row.get(
                                    "indikasi_codes"
                                )
                            )
                        )
                    ),

                "indikasi_name":
                    ", ".join(
                        _safe_string(item)
                        for item in (
                            row.get(
                                "indikasi_names"
                            )
                            or []
                        )
                        if _safe_string(item)
                    )
                    if isinstance(
                        row.get(
                            "indikasi_names"
                        ),
                        list,
                    )
                    else _safe_string(
                        row.get(
                            "indikasi_names"
                        )
                    ),

                "phasa":
                    _phase_label(row),

                "penyebab_kejadian":
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

                "keterangan":
                    _safe_string(
                        row.get(
                            "event_description"
                        )
                    ),

                "keterangan_pemulihan":
                    _safe_string(
                        row.get(
                            "recovery_description"
                        )
                    ),

                "catatan":
                    _safe_string(
                        row.get(
                            "notes"
                        )
                    ),

                # Data audit tambahan; tidak wajib ditampilkan
                # pada PDF template lama.
                "operator_bertugas":
                    _safe_string(
                        row.get(
                            "operator_name"
                        )
                    ),

                "dispatcher_up2d":
                    _safe_string(
                        row.get(
                            "dispatcher_up2d_name"
                        )
                    ),

                "diinput_oleh":
                    _safe_string(
                        row.get(
                            "created_by_name"
                        )
                    ),
            }
        )

    return pd.DataFrame(result)


# ==========================================================
# DETAIL LEPAS
# ==========================================================


def build_detail_lepas(
    events: list[ReportRow],
) -> pd.DataFrame:
    result: list[dict[str, Any]] = []

    lepas_events = sorted(
        (
            row
            for row in events
            if _is_lepas_event(row)
            and not _is_trip_event(row)
        ),
        key=lambda row: (
            _event_date_text(
                row.get("event_date")
            ),
            _time_hhmm(
                row.get("event_time")
            ),
            _safe_string(
                row.get("penyulang_code")
            ),
        ),
    )

    for index, row in enumerate(
        lepas_events,
        start=1,
    ):
        pmt_status = _safe_string(
            row.get(
                "pmt_status_code"
            )
        ).upper()

        kondisi = (
            "BLACKOUT"
            if pmt_status == "BLACKOUT"
            else "LEPAS"
        )

        result.append(
            {
                "no":
                    index,

                "event_id":
                    row.get("event_id"),

                "nama_penyulang":
                    _safe_string(
                        row.get(
                            "penyulang_code"
                        )
                    ),

                "penyulang_name":
                    _safe_string(
                        row.get(
                            "penyulang_name"
                        )
                    ),

                "penyulang_alias":
                    _safe_string(
                        row.get(
                            "penyulang_alias"
                        )
                    ),

                "kondisi":
                    kondisi,

                "tgl":
                    _event_day(
                        row.get(
                            "event_date"
                        )
                    ),

                "tanggal":
                    _event_date_text(
                        row.get(
                            "event_date"
                        )
                    ),

                "pkl":
                    _time_hhmm(
                        row.get(
                            "event_time"
                        )
                    ),

                # Arus beban sebelum manuver / lepas - 3 phasa
                "amp_r":
                    _phase_current_value(
                        row,
                        phase_field="load_current_before_r_a",
                        legacy_field="load_current_before_a",
                    ),

                "amp_s":
                    _phase_current_value(
                        row,
                        phase_field="load_current_before_s_a",
                        legacy_field="load_current_before_a",
                    ),

                "amp_t":
                    _phase_current_value(
                        row,
                        phase_field="load_current_before_t_a",
                        legacy_field="load_current_before_a",
                    ),

                # Legacy average tetap dipertahankan sementara.
                "amp":
                    _three_phase_average_from_row(
                        row,
                        prefix="load_current_before",
                        legacy_field="load_current_before_a",
                    ),

                "kv":
                    row.get(
                        "voltage_before_kv"
                    ),

                # Sengaja kosong pada laporan Lepas.
                "r":
                    None,

                "s":
                    None,

                "t":
                    None,

                "n":
                    None,

                "pemulihan_kondisi":
                    _safe_string(
                        row.get(
                            "recovery_status_name"
                        ),
                        _safe_string(
                            row.get(
                                "recovery_status_code"
                            )
                        ),
                    ),

                "pemulihan_tgl":
                    _event_day(
                        row.get(
                            "recovery_date"
                        )
                    ),

                "pemulihan_tanggal":
                    _event_date_text(
                        row.get(
                            "recovery_date"
                        )
                    ),

                "pemulihan_pkl":
                    _time_hhmm(
                        row.get(
                            "recovery_time"
                        )
                    ),

                # Arus beban setelah normalisasi / operasi - 3 phasa
                "amp_after_r":
                    _phase_current_value(
                        row,
                        phase_field="load_current_after_r_a",
                        legacy_field="load_current_after_a",
                    ),

                "amp_after_s":
                    _phase_current_value(
                        row,
                        phase_field="load_current_after_s_a",
                        legacy_field="load_current_after_a",
                    ),

                "amp_after_t":
                    _phase_current_value(
                        row,
                        phase_field="load_current_after_t_a",
                        legacy_field="load_current_after_a",
                    ),

                "amp_after":
                    _three_phase_average_from_row(
                        row,
                        prefix="load_current_after",
                        legacy_field="load_current_after_a",
                    ),

                # Status pemulihan beban dan detail manuver 3 phasa.
                "supply_status_code":
                    _safe_string(
                        row.get(
                            "supply_status_code"
                        )
                    ),

                "supply_status_name":
                    _safe_string(
                        row.get(
                            "supply_status_name"
                        ),
                        _safe_string(
                            row.get(
                                "supply_status_code"
                            )
                        ),
                    ),

                "supply_restored_date":
                    _event_date_text(
                        row.get(
                            "supply_restored_date"
                        )
                    ),

                "supply_restored_time":
                    _time_hhmm(
                        row.get(
                            "supply_restored_time"
                        )
                    ),

                "maneuvered_r":
                    _phase_current_value(
                        row,
                        phase_field="maneuvered_current_r_a",
                        legacy_field="maneuvered_current_a",
                    ),

                "maneuvered_s":
                    _phase_current_value(
                        row,
                        phase_field="maneuvered_current_s_a",
                        legacy_field="maneuvered_current_a",
                    ),

                "maneuvered_t":
                    _phase_current_value(
                        row,
                        phase_field="maneuvered_current_t_a",
                        legacy_field="maneuvered_current_a",
                    ),

                "maneuvered":
                    _three_phase_average_from_row(
                        row,
                        prefix="maneuvered_current",
                        legacy_field="maneuvered_current_a",
                    ),

                "remaining_r":
                    _phase_current_value(
                        row,
                        phase_field="remaining_current_r_a",
                        legacy_field="remaining_current_a",
                    ),

                "remaining_s":
                    _phase_current_value(
                        row,
                        phase_field="remaining_current_s_a",
                        legacy_field="remaining_current_a",
                    ),

                "remaining_t":
                    _phase_current_value(
                        row,
                        phase_field="remaining_current_t_a",
                        legacy_field="remaining_current_a",
                    ),

                "remaining":
                    _three_phase_average_from_row(
                        row,
                        prefix="remaining_current",
                        legacy_field="remaining_current_a",
                    ),

                "final_supply_normalized":
                    bool(
                        row.get(
                            "final_supply_normalized"
                        )
                    ),

                "final_supply_normalization_date":
                    _event_date_text(
                        row.get(
                            "final_supply_normalization_date"
                        )
                    ),

                "final_supply_normalization_time":
                    _time_hhmm(
                        row.get(
                            "final_supply_normalization_time"
                        )
                    ),

                "menit":
                    _safe_float(
                        row.get(
                            "customer_outage_duration_min"
                        )
                    ),

                "jlh_kwh":
                    _safe_float(
                        row.get(
                            "ens_kwh"
                        )
                    ),

                "annunciator":
                    "",

                "indikasi":
                    "",

                "phasa":
                    "",

                "penyebab_kejadian":
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

                "kategori_lepas":
                    _lepas_category(row),

                "keterangan":
                    _safe_string(
                        row.get(
                            "event_description"
                        )
                    ),

                "keterangan_pemulihan":
                    _safe_string(
                        row.get(
                            "recovery_description"
                        )
                    ),

                "catatan":
                    _safe_string(
                        row.get(
                            "notes"
                        )
                    ),

                "operator_bertugas":
                    _safe_string(
                        row.get(
                            "operator_name"
                        )
                    ),

                "dispatcher_up2d":
                    _safe_string(
                        row.get(
                            "dispatcher_up2d_name"
                        )
                    ),

                "diinput_oleh":
                    _safe_string(
                        row.get(
                            "created_by_name"
                        )
                    ),
            }
        )

    return pd.DataFrame(result)


# ==========================================================
# SUMMARY
# ==========================================================


def build_monthly_summary(
    events: list[ReportRow],
) -> dict[str, Any]:
    trip_events = [
        row
        for row in events
        if _is_trip_event(row)
    ]

    lepas_events = [
        row
        for row in events
        if _is_lepas_event(row)
        and not _is_trip_event(row)
    ]

    all_events = [
        *trip_events,
        *lepas_events,
    ]

    feeder_ids = {
        _safe_string(
            row.get("penyulang_id")
        )
        or _safe_string(
            row.get("penyulang_code")
        )
        for row in all_events
        if (
            _safe_string(
                row.get("penyulang_id")
            )
            or _safe_string(
                row.get("penyulang_code")
            )
        )
    }

    return {
        "total_operasi":
            len(all_events),

        "total_trip":
            len(trip_events),

        "total_lepas":
            len(lepas_events),

        "total_menit_padam":
            round(
                sum(
                    _safe_float(
                        row.get(
                            "customer_outage_duration_min"
                        )
                    )
                    for row in all_events
                ),
                2,
            ),

        "total_ens_kwh":
            round(
                sum(
                    _safe_float(
                        row.get(
                            "ens_kwh"
                        )
                    )
                    for row in all_events
                ),
                4,
            ),

        "penyulang_terdampak":
            len(feeder_ids),
    }


# ==========================================================
# MONTHLY REPORT WORKFLOW
# ==========================================================


def get_or_create_monthly_report(
    *,
    report_year: int,
    report_month: int,
    scope_functloc_id: str,
) -> MonthlyReportRow:
    supabase = get_supabase_client()

    response = supabase.rpc(
        "fn_monthly_report_get_or_create",
        {
            "p_report_year":
                report_year,

            "p_report_month":
                report_month,

            "p_scope_functloc_id":
                scope_functloc_id,
        },
    ).execute()

    if not response.data:
        raise RuntimeError(
            "Header laporan bulanan gagal dibuat/dibaca."
        )

    if isinstance(
        response.data,
        list,
    ):
        if not response.data:
            raise RuntimeError(
                "Header laporan bulanan tidak ditemukan."
            )

        return cast(
            MonthlyReportRow,
            response.data[0],
        )

    return cast(
        MonthlyReportRow,
        response.data,
    )


def submit_monthly_report(
    monthly_report_id: str,
) -> MonthlyReportRow:
    supabase = get_supabase_client()

    response = supabase.rpc(
        "fn_monthly_report_submit",
        {
            "p_monthly_report_id":
                monthly_report_id,
        },
    ).execute()

    if not response.data:
        raise RuntimeError(
            "Laporan bulanan gagal diajukan."
        )

    if isinstance(
        response.data,
        list,
    ):
        return cast(
            MonthlyReportRow,
            response.data[0],
        )

    return cast(
        MonthlyReportRow,
        response.data,
    )


def review_monthly_report(
    *,
    monthly_report_id: str,
    action: str,
    notes: str | None = None,
) -> MonthlyReportRow:
    normalized_action = _safe_string(
        action
    ).upper()

    if normalized_action not in {
        "APPROVE",
        "REJECT",
    }:
        raise ValueError(
            "Action review harus APPROVE atau REJECT."
        )

    if (
        normalized_action == "REJECT"
        and not _safe_string(notes)
    ):
        raise ValueError(
            "Catatan wajib diisi ketika laporan dikembalikan."
        )

    supabase = get_supabase_client()

    response = supabase.rpc(
        "fn_monthly_report_review",
        {
            "p_monthly_report_id":
                monthly_report_id,

            "p_action":
                normalized_action,

            "p_notes":
                _safe_string(notes)
                or None,
        },
    ).execute()

    if not response.data:
        raise RuntimeError(
            "Review laporan bulanan gagal diproses."
        )

    if isinstance(
        response.data,
        list,
    ):
        return cast(
            MonthlyReportRow,
            response.data[0],
        )

    return cast(
        MonthlyReportRow,
        response.data,
    )



def return_monthly_report_to_draft(
    *,
    monthly_report_id: str,
    notes: str,
) -> MonthlyReportRow:
    """
    Mengembalikan laporan APPROVED menjadi DRAFT.

    EVALUATOR / ADMIN / SUPER_ADMIN diizinkan sesuai scope
    dan capability yang diverifikasi oleh RPC Supabase.

    Catatan:
    - e-Sign aktif pada header laporan direset.
    - file resmi current dinonaktifkan oleh backend.
    - histori APPROVE tetap dipertahankan sebagai audit trail.
    - action RETURN_DRAFT ditambahkan ke histori.
    """

    normalized_notes = _safe_string(
        notes
    )

    if not normalized_notes:
        raise ValueError(
            "Alasan pengembalian ke Draft wajib diisi."
        )

    supabase = get_supabase_client()

    response = supabase.rpc(
        "fn_monthly_report_return_to_draft",
        {
            "p_monthly_report_id":
                monthly_report_id,

            "p_notes":
                normalized_notes,
        },
    ).execute()

    if not response.data:
        raise RuntimeError(
            "Laporan gagal dikembalikan ke Draft."
        )

    if isinstance(
        response.data,
        list,
    ):
        return cast(
            MonthlyReportRow,
            response.data[0],
        )

    return cast(
        MonthlyReportRow,
        response.data,
    )


def load_monthly_report_approval_history(
    monthly_report_id: str,
) -> list[MonthlyReportRow]:
    supabase = get_supabase_client()

    response = (
        supabase
        .table(
            "trx_monthly_report_approval"
        )
        .select(
            "approval_id,monthly_report_id,action,"
            "actor_user_id,actor_role,signer_name,"
            "signer_position,notes,signature_token,acted_at"
        )
        .eq(
            "monthly_report_id",
            monthly_report_id,
        )
        .order(
            "acted_at",
            desc=False,
        )
        .execute()
    )

    if not response.data:
        return []

    return cast(
        list[MonthlyReportRow],
        response.data,
    )


def is_official_report_available(
    monthly_report: MonthlyReportRow,
) -> bool:
    return (
        _safe_string(
            monthly_report.get(
                "status"
            )
        ).upper()
        == "APPROVED"
        and bool(
            _safe_string(
                monthly_report.get(
                    "signature_token"
                )
            )
        )
        and bool(
            _safe_string(
                monthly_report.get(
                    "verified_by"
                )
            )
        )
        and bool(
            _safe_string(
                monthly_report.get(
                    "verified_at"
                )
            )
        )
    )



# ==========================================================
# OFFICIAL REPORT FILES
# ==========================================================


def register_monthly_report_file(
    *,
    monthly_report_id: str,
    file_format: str,
    file_name: str,
    drive_file_url: str,
    drive_file_id: str | None = None,
    mime_type: str | None = None,
    file_size: int | None = None,
) -> MonthlyReportRow:
    """
    Menyimpan metadata file PDF/XLSX resmi yang sudah
    berhasil di-upload ke Google Drive.

    File hanya dapat diregistrasikan jika laporan sudah
    APPROVED dan memiliki signature_token.
    """

    normalized_format = _safe_string(
        file_format
    ).upper()

    if normalized_format not in {
        "PDF",
        "XLSX",
    }:
        raise ValueError(
            "file_format harus PDF atau XLSX."
        )

    supabase = get_supabase_client()

    response = supabase.rpc(
        "fn_monthly_report_register_file",
        {
            "p_monthly_report_id":
                monthly_report_id,

            "p_file_format":
                normalized_format,

            "p_file_name":
                file_name,

            "p_drive_file_url":
                drive_file_url,

            "p_drive_file_id":
                _safe_string(
                    drive_file_id
                )
                or None,

            "p_mime_type":
                _safe_string(
                    mime_type
                )
                or None,

            "p_file_size":
                file_size,
        },
    ).execute()

    if not response.data:
        raise RuntimeError(
            "Metadata file laporan gagal disimpan."
        )

    if isinstance(
        response.data,
        list,
    ):
        return cast(
            MonthlyReportRow,
            response.data[0],
        )

    return cast(
        MonthlyReportRow,
        response.data,
    )


def load_monthly_report_files(
    monthly_report_id: str,
    *,
    current_only: bool = True,
) -> list[MonthlyReportRow]:
    supabase = get_supabase_client()

    query = (
        supabase
        .table(
            "trx_monthly_report_file"
        )
        .select(
            "report_file_id,monthly_report_id,file_format,"
            "file_name,drive_file_id,drive_file_url,mime_type,"
            "file_size,version_no,signature_token,is_current,"
            "generated_by,generated_at"
        )
        .eq(
            "monthly_report_id",
            monthly_report_id,
        )
    )

    if current_only:
        query = query.eq(
            "is_current",
            True,
        )

    response = (
        query
        .order(
            "file_format"
        )
        .order(
            "version_no",
            desc=True,
        )
        .execute()
    )

    if not response.data:
        return []

    return cast(
        list[MonthlyReportRow],
        response.data,
    )


def load_monthly_report_list(
    *,
    limit: int = 120,
) -> list[MonthlyReportRow]:
    """
    Daftar laporan per GI yang dapat diakses user.
    File PDF/XLSX current digabungkan ke masing-masing row.
    """

    supabase = get_supabase_client()

    response = (
        supabase
        .table(
            "trx_monthly_report"
        )
        .select(
            "monthly_report_id,report_year,report_month,"
            "scope_functloc_id,status,submitted_at,"
            "verified_at,verified_role,signer_name,"
            "signer_position,signature_token,created_at,updated_at"
        )
        .order(
            "report_year",
            desc=True,
        )
        .order(
            "report_month",
            desc=True,
        )
        .limit(
            limit
        )
        .execute()
    )

    if not response.data:
        return []

    report_rows = cast(
        list[MonthlyReportRow],
        response.data,
    )

    report_ids = [
        _safe_string(
            row.get(
                "monthly_report_id"
            )
        )
        for row in report_rows
        if _safe_string(
            row.get(
                "monthly_report_id"
            )
        )
    ]

    files_by_report: dict[
        str,
        list[MonthlyReportRow],
    ] = {}

    if report_ids:
        file_response = (
            supabase
            .table(
                "trx_monthly_report_file"
            )
            .select(
                "report_file_id,monthly_report_id,file_format,"
                "file_name,drive_file_id,drive_file_url,mime_type,"
                "file_size,version_no,is_current,generated_at"
            )
            .in_(
                "monthly_report_id",
                report_ids,
            )
            .eq(
                "is_current",
                True,
            )
            .execute()
        )

        if file_response.data:
            for file_row in cast(
                list[MonthlyReportRow],
                file_response.data,
            ):
                report_id = _safe_string(
                    file_row.get(
                        "monthly_report_id"
                    )
                )

                if report_id:
                    files_by_report.setdefault(
                        report_id,
                        [],
                    ).append(
                        file_row
                    )

    feeder_rows = get_accessible_feeders()

    gi_name_by_flc: dict[str, str] = {}

    for feeder in feeder_rows:
        gi_flc = _safe_string(
            feeder.get(
                "gi_flc"
            )
        )

        gi_name = _safe_string(
            feeder.get(
                "gi_name"
            )
        )

        if gi_flc and gi_name:
            gi_name_by_flc[
                gi_flc
            ] = gi_name

    result: list[MonthlyReportRow] = []

    for row in report_rows:
        report_id = _safe_string(
            row.get(
                "monthly_report_id"
            )
        )

        scope_id = _safe_string(
            row.get(
                "scope_functloc_id"
            )
        )

        files = files_by_report.get(
            report_id,
            [],
        )

        pdf_file = next(
            (
                item
                for item in files
                if _safe_string(
                    item.get(
                        "file_format"
                    )
                ).upper()
                == "PDF"
            ),
            None,
        )

        xlsx_file = next(
            (
                item
                for item in files
                if _safe_string(
                    item.get(
                        "file_format"
                    )
                ).upper()
                == "XLSX"
            ),
            None,
        )

        enriched = dict(
            row
        )

        enriched[
            "gi_name"
        ] = gi_name_by_flc.get(
            scope_id,
            scope_id,
        )

        enriched[
            "pdf_file"
        ] = pdf_file

        enriched[
            "xlsx_file"
        ] = xlsx_file

        result.append(
            enriched
        )

    return result


# ==========================================================
# COMPLETE REPORT BUNDLE
# ==========================================================


def build_monthly_report_bundle(
    *,
    report_year: int,
    report_month: int,
    scope_functloc_id: str,
) -> dict[str, Any]:
    """
    Entry point utama halaman laporan_bulanan.py.

    Menghasilkan:
    - header workflow
    - summary
    - rekap_trip
    - rekap_lepas
    - detail_trip
    - detail_lepas
    - flag official_available
    """

    monthly_report = (
        get_or_create_monthly_report(
            report_year=report_year,
            report_month=report_month,
            scope_functloc_id=scope_functloc_id,
        )
    )

    all_feeders = (
        get_accessible_feeders()
    )

    feeders = (
        filter_feeders_by_scope(
            all_feeders,
            scope_functloc_id,
        )
    )

    events = load_monthly_events(
        report_year,
        report_month,
        scope_functloc_id,
    )

    rekap_trip = build_rekap_trip(
        events,
        feeders,
    )

    rekap_lepas = build_rekap_lepas(
        events,
        feeders,
    )

    detail_trip = build_detail_trip(
        events
    )

    detail_lepas = build_detail_lepas(
        events
    )

    summary = build_monthly_summary(
        events
    )

    monthly_report_id = _safe_string(
        monthly_report.get(
            "monthly_report_id"
        )
    )

    approval_history = (
        load_monthly_report_approval_history(
            monthly_report_id
        )
    )

    official_files = (
        load_monthly_report_files(
            monthly_report_id
        )
        if (
            monthly_report_id
            and is_official_report_available(
                monthly_report
            )
        )
        else []
    )

    return {
        "monthly_report":
            monthly_report,

        "summary":
            summary,

        "rekap_trip":
            rekap_trip,

        "rekap_lepas":
            rekap_lepas,

        "detail_trip":
            detail_trip,

        "detail_lepas":
            detail_lepas,

        "approval_history":
            approval_history,

        "official_files":
            official_files,

        "official_available":
            is_official_report_available(
                monthly_report
            ),
    }