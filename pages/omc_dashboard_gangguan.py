from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
import base64
from html import escape
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from components.sidebar import hide_sidebar
from services.auth_service import is_authenticated
from services.dashboard_operations_service import (
    get_dashboard_operations_events,
)
from services.dashboard_reliability_service import (
    get_dashboard_reliability_events,
)
from services.dashboard_transformer_service import (
    get_transformer_fault_exposure,
)
from services.omc_dashboard_service import (
    get_omc_recent_gangguan,
)


REFRESH_SECONDS = 30
CACHE_TTL_SECONDS = 20


# ==========================================================
# BASIC HELPERS
# ==========================================================



@st.cache_data(show_spinner=False)
def _load_pln_logo_data_uri() -> str:
    """
    Load assets/logo_pln.png and convert it into a data URI so it can be
    rendered inside the custom HTML header.
    """

    candidate_paths = [
        Path(__file__).resolve().parents[1] / "assets" / "logo_pln.png",
        Path.cwd() / "assets" / "logo_pln.png",
        Path("assets") / "logo_pln.png",
    ]

    for candidate in candidate_paths:
        try:
            if candidate.exists():
                png_bytes = candidate.read_bytes()
                encoded = base64.b64encode(png_bytes).decode("ascii")
                return f"data:image/png;base64,{encoded}"
        except Exception:
            continue

    return ""


def _safe_float(value: object) -> float:
    if value is None:
        return 0.0

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, (int, float)):
        return float(value)

    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0




def _inject_live_browser_clock() -> None:
    """
    Update the OMC header clock every second in the browser.

    This does NOT rerun dashboard queries. The dashboard data refresh
    interval remains controlled by REFRESH_SECONDS.
    """

    components.html(
        """
        <script>
        (() => {
          const pad = (value) => String(value).padStart(2, "0");

          const monthNames = [
            "JAN", "FEB", "MAR", "APR", "MEI", "JUN",
            "JUL", "AGU", "SEP", "OKT", "NOV", "DES"
          ];

          function updateClock() {
            try {
              const doc = window.parent.document;
              const clock = doc.querySelector(".omc-top-header .head-time");
              const dateNode = doc.querySelector(".omc-top-header .head-date");

              if (!clock) {
                return;
              }

              const now = new Date();

              const timeText =
                pad(now.getHours()) + ":" +
                pad(now.getMinutes()) + ":" +
                pad(now.getSeconds());

              clock.innerHTML =
                timeText +
                ' <span style="font-size:7px;color:#c4cfdb;font-weight:800;">WIB</span>';

              if (dateNode) {
                dateNode.textContent =
                  pad(now.getDate()) + " " +
                  monthNames[now.getMonth()] + " " +
                  now.getFullYear();
              }
            } catch (error) {
              // Keep dashboard unaffected if browser DOM access changes.
            }
          }

          updateClock();

          if (window.parent.__omcLiveClockTimer) {
            window.parent.clearInterval(
              window.parent.__omcLiveClockTimer
            );
          }

          window.parent.__omcLiveClockTimer =
            window.parent.setInterval(updateClock, 1000);
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def _render_html(
    value: str,
) -> None:
    """Render trusted local HTML without Markdown code-block formatting."""

    import textwrap

    st.markdown(
        textwrap.dedent(
            value
        ).strip(),
        unsafe_allow_html=True,
    )



def _safe_int(value: object) -> int:
    return int(round(_safe_float(value)))


def _as_text(value: object, default: str = "-") -> str:
    if value is None:
        return default

    text = str(value).strip()
    return text if text else default


def _first_value(
    row: dict[str, Any],
    *keys: str,
    default: str = "-",
) -> str:
    for key in keys:
        value = row.get(key)
        text = _as_text(value, "")

        if text:
            return text

    return default


def _first_numeric(
    row: dict[str, Any],
    *keys: str,
) -> float:
    for key in keys:
        value = row.get(key)

        if value is not None:
            return _safe_float(value)

    return 0.0


def _short(value: object, max_len: int = 30) -> str:
    text = _as_text(value)

    if len(text) <= max_len:
        return text

    return text[: max_len - 1] + "…"


def _event_datetime(row: dict[str, Any]) -> datetime | None:
    raw_date = row.get("event_date")
    raw_time = row.get("event_time")

    if raw_date is None:
        return None

    try:
        parsed_date = pd.to_datetime(raw_date).date()
    except Exception:
        return None

    if raw_time is None:
        return datetime.combine(parsed_date, time.min)

    try:
        parsed_time = pd.to_datetime(str(raw_time)).time()
    except Exception:
        parsed_time = time.min

    return datetime.combine(parsed_date, parsed_time)


def _event_clock(row: dict[str, Any]) -> str:
    event_dt = _event_datetime(row)

    if event_dt is None:
        return "-"

    return event_dt.strftime("%H:%M:%S")


def _relay_label(row: dict[str, Any]) -> str:
    return _first_value(
        row,
        "relay_indication",
        "relay_indication_name",
        "indication_name",
        "indication_code",
        "annunciator",
        default="-",
    )


def _phase_label(row: dict[str, Any]) -> str:
    return _first_value(
        row,
        "phase_label",
        "fault_phase",
        "phase_code",
        "phase",
        "phasa",
        default="-",
    )


def _supply_label(row: dict[str, Any]) -> str:
    normalized = row.get("final_supply_normalized")

    if isinstance(normalized, bool):
        return "NORMAL" if normalized else "NOT NORMAL"

    return _first_value(
        row,
        "supply_status",
        "supply_status_name",
        "record_status",
        default="-",
    ).upper()




def _row_ultg_name(
    row: dict[str, Any],
) -> str:
    return _first_value(
        row,
        "ultg_name",
        "ultg",
        default="",
    )


def _row_gi_name(
    row: dict[str, Any],
) -> str:
    return _first_value(
        row,
        "gi_name",
        "substation_name",
        "gi",
        default="",
    )


def _filter_rows_scope(
    rows: list[dict[str, Any]],
    *,
    selected_ultg: str,
    selected_gi: str,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []

    for row in rows:
        row_ultg = _row_ultg_name(row)
        row_gi = _row_gi_name(row)

        if (
            selected_ultg != "SEMUA ULTG"
            and row_ultg != selected_ultg
        ):
            continue

        if (
            selected_gi != "SEMUA GI"
            and row_gi != selected_gi
        ):
            continue

        filtered.append(row)

    return filtered


def _month_name_id(
    month: int,
) -> str:
    month_names = {
        1: "JANUARI",
        2: "FEBRUARI",
        3: "MARET",
        4: "APRIL",
        5: "MEI",
        6: "JUNI",
        7: "JULI",
        8: "AGUSTUS",
        9: "SEPTEMBER",
        10: "OKTOBER",
        11: "NOVEMBER",
        12: "DESEMBER",
    }

    return month_names.get(
        month,
        str(month),
    )


# ==========================================================
# DATA LOADERS
# ==========================================================


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _load_reliability(
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    return get_dashboard_reliability_events(
        start_date=start_date,
        end_date=end_date,
        ultg_flc=None,
        gi_flc=None,
        bay_flc=None,
        penyulang_id=None,
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _load_operations(
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    return get_dashboard_operations_events(
        start_date=start_date,
        end_date=end_date,
        ultg_flc=None,
        gi_flc=None,
        bay_flc=None,
        penyulang_id=None,
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _load_recent_gangguan(
    start_date: date,
    end_date: date,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return get_omc_recent_gangguan(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _load_exposure(
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    return get_transformer_fault_exposure(
        start_date=start_date,
        end_date=end_date,
        ultg_flc=None,
        gi_flc=None,
        bay_flc=None,
        penyulang_id=None,
    )


# ==========================================================
# SMALL HTML / SVG VISUALS
# ==========================================================


def _trend_svg(
    hourly_values: list[int],
) -> str:
    width = 620
    height = 285
    left = 34
    right = 16
    top = 34
    bottom = 34

    chart_w = width - left - right
    chart_h = height - top - bottom
    max_value = max(max(hourly_values), 1)

    grid: list[str] = []
    bars: list[str] = []
    axis_labels: list[str] = []
    data_labels: list[str] = []

    for tick in range(4):
        y = top + chart_h * tick / 3
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" '
            f'x2="{left + chart_w}" y2="{y:.1f}" '
            'stroke="#18324d" stroke-width="1"/>'
        )

    slot = chart_w / 24
    bar_w = max(6.0, slot * 0.58)

    for hour, value in enumerate(hourly_values):
        x = left + hour * slot + (slot - bar_w) / 2
        raw_h = (value / max_value) * chart_h
        bar_h = raw_h if value > 0 else 0
        y = top + chart_h - bar_h

        if value > 0:
            bars.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" '
                f'width="{bar_w:.1f}" height="{bar_h:.1f}" '
                'rx="3" fill="#3b9cff"/>'
            )
            data_labels.append(
                f'<text x="{x + bar_w / 2:.1f}" '
                f'y="{max(12, y - 5):.1f}" '
                'fill="#f5f7fb" font-size="12" '
                'font-weight="800" text-anchor="middle">'
                f"{value}</text>"
            )

    for hour in [0, 4, 8, 12, 16, 20, 23]:
        x = left + hour * slot + slot / 2
        label = "24:00" if hour == 23 else f"{hour:02d}:00"
        axis_labels.append(
            f'<text x="{x:.1f}" y="{height - 8}" '
            'fill="#91a3b8" font-size="10" '
            'text-anchor="middle">'
            f"{label}</text>"
        )

    empty_state = ""

    if sum(hourly_values) == 0:
        empty_state = (
            f'<text x="{left + chart_w / 2:.1f}" '
            f'y="{top + chart_h / 2:.1f}" '
            'fill="#61758d" font-size="13" font-weight="700" '
            'text-anchor="middle">Tidak ada gangguan hari ini</text>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" '
        'preserveAspectRatio="xMidYMid meet" class="svg-chart" style="width:100%;height:100%;display:block;">'
        + "".join(grid)
        + "".join(bars)
        + "".join(data_labels)
        + "".join(axis_labels)
        + empty_state
        + "</svg>"
    )


def _month_trend_svg(
    daily_values: list[int],
) -> str:
    width = 620
    height = 285
    left = 34
    right = 16
    top = 34
    bottom = 34

    chart_w = width - left - right
    chart_h = height - top - bottom
    max_value = max(max(daily_values), 1)
    count = max(len(daily_values), 1)
    slot = chart_w / count
    bar_w = max(4.0, min(15.0, slot * 0.62))

    grid: list[str] = []
    bars: list[str] = []
    axis_labels: list[str] = []
    data_labels: list[str] = []

    for tick in range(4):
        y = top + chart_h * tick / 3
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" '
            f'x2="{left + chart_w}" y2="{y:.1f}" '
            'stroke="#18324d" stroke-width="1"/>'
        )

    for index, value in enumerate(daily_values):
        x = left + index * slot + (slot - bar_w) / 2
        raw_h = (value / max_value) * chart_h
        bar_h = raw_h if value > 0 else 0
        y = top + chart_h - bar_h

        if value > 0:
            bars.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" '
                f'width="{bar_w:.1f}" height="{bar_h:.1f}" '
                'rx="3" fill="#ffb020"/>'
            )
            data_labels.append(
                f'<text x="{x + bar_w / 2:.1f}" '
                f'y="{max(12, y - 5):.1f}" '
                'fill="#f5f7fb" font-size="12" '
                'font-weight="800" text-anchor="middle">'
                f"{value}</text>"
            )

    visible_days = [1, 5, 10, 15, 20, 25, count]

    for day in sorted(set(d for d in visible_days if 1 <= d <= count)):
        index = day - 1
        x = left + index * slot + slot / 2
        axis_labels.append(
            f'<text x="{x:.1f}" y="{height - 8}" '
            'fill="#91a3b8" font-size="10" '
            'text-anchor="middle">'
            f"{day:02d}</text>"
        )

    empty_state = ""

    if sum(daily_values) == 0:
        empty_state = (
            f'<text x="{left + chart_w / 2:.1f}" '
            f'y="{top + chart_h / 2:.1f}" '
            'fill="#61758d" font-size="13" font-weight="700" '
            'text-anchor="middle">Belum ada gangguan bulan berjalan</text>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" '
        'preserveAspectRatio="xMidYMid meet" class="svg-chart" style="width:100%;height:100%;display:block;">'
        + "".join(grid)
        + "".join(bars)
        + "".join(data_labels)
        + "".join(axis_labels)
        + empty_state
        + "</svg>"
    )




def _relay_stacked_svg(
    daily_rows: list[dict[str, int]],
) -> str:
    width = 760
    height = 285
    left = 38
    right = 18
    top = 34
    bottom = 40

    chart_w = width - left - right
    chart_h = height - top - bottom

    series = [
        ("OCR_INST", "OCR INST", "#ffb020"),
        ("OCR_TD", "OCR TD", "#f59e0b"),
        ("GFR_INST", "GFR INST", "#ff4d55"),
        ("GFR_TD", "GFR TD", "#ef6a6f"),
        ("SYSTEM", "Sistem", "#b46cff"),
    ]

    totals = [
        sum(int(row.get(key, 0)) for key, _, _ in series)
        for row in daily_rows
    ]

    max_total = max(max(totals, default=0), 1)
    count = max(len(daily_rows), 1)
    slot = chart_w / count
    bar_w = max(5.0, min(18.0, slot * 0.66))

    grid: list[str] = []
    bars: list[str] = []
    labels: list[str] = []
    total_labels: list[str] = []

    for tick in range(4):
        y = top + chart_h * tick / 3
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" '
            f'x2="{left + chart_w}" y2="{y:.1f}" '
            'stroke="#18324d" stroke-width="1"/>'
        )

    for index, row in enumerate(daily_rows):
        x = left + index * slot + (slot - bar_w) / 2
        current_bottom = top + chart_h
        total = totals[index]

        for key, _, color in series:
            value = int(row.get(key, 0))

            if value <= 0:
                continue

            segment_h = value / max_total * chart_h
            y = current_bottom - segment_h

            bars.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" '
                f'width="{bar_w:.1f}" height="{segment_h:.1f}" '
                f'fill="{color}"/>'
            )

            current_bottom = y

        if total > 0:
            total_labels.append(
                f'<text x="{x + bar_w / 2:.1f}" '
                f'y="{max(13, current_bottom - 5):.1f}" '
                'fill="#f5f7fb" font-size="11" '
                'font-weight="900" text-anchor="middle">'
                f"{total}</text>"
            )

    visible_days = [1, 5, 10, 15, 20, 25, count]

    for day in sorted(
        set(
            d for d in visible_days
            if 1 <= d <= count
        )
    ):
        index = day - 1
        x = left + index * slot + slot / 2

        labels.append(
            f'<text x="{x:.1f}" y="{height - 9}" '
            'fill="#91a3b8" font-size="10" '
            'text-anchor="middle">'
            f"{day:02d}</text>"
        )

    empty_state = ""

    if sum(totals) == 0:
        empty_state = (
            f'<text x="{left + chart_w / 2:.1f}" '
            f'y="{top + chart_h / 2:.1f}" '
            'fill="#61758d" font-size="13" '
            'font-weight="700" text-anchor="middle">'
            'Belum ada relay bekerja pada bulan berjalan'
            '</text>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" '
        'preserveAspectRatio="xMidYMid meet" '
        'class="svg-chart" style="width:100%;height:100%;display:block;">'
        + "".join(grid)
        + "".join(bars)
        + "".join(total_labels)
        + "".join(labels)
        + empty_state
        + "</svg>"
    )



def _ens_daily_svg(
    daily_values: list[float],
) -> str:
    width = 620
    height = 210
    left = 38
    right = 16
    top = 34
    bottom = 34

    chart_w = width - left - right
    chart_h = height - top - bottom
    max_value = max(max(daily_values, default=0.0), 1.0)

    count = max(len(daily_values), 1)
    slot = chart_w / count
    bar_w = max(4.0, min(15.0, slot * 0.62))

    grid: list[str] = []
    bars: list[str] = []
    axis_labels: list[str] = []
    data_labels: list[str] = []

    for tick in range(4):
        y = top + chart_h * tick / 3
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" '
            f'x2="{left + chart_w}" y2="{y:.1f}" '
            'stroke="#18324d" stroke-width="1"/>'
        )

    for index, value in enumerate(daily_values):
        x = left + index * slot + (slot - bar_w) / 2
        raw_h = (value / max_value) * chart_h
        bar_h = raw_h if value > 0 else 0.0
        y = top + chart_h - bar_h

        if value > 0:
            bars.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" '
                f'width="{bar_w:.1f}" height="{bar_h:.1f}" '
                'rx="3" fill="#b46cff"/>'
            )

            value_label = (
                f"{value:,.0f}"
                if value >= 10
                else f"{value:,.1f}"
            )

            data_labels.append(
                f'<text x="{x + bar_w / 2:.1f}" '
                f'y="{max(13, y - 5):.1f}" '
                'fill="#f5f7fb" font-size="11" '
                'font-weight="800" text-anchor="middle">'
                f"{value_label}</text>"
            )

    visible_days = [1, 5, 10, 15, 20, 25, count]

    for day in sorted(
        set(
            d
            for d in visible_days
            if 1 <= d <= count
        )
    ):
        index = day - 1
        x = left + index * slot + slot / 2

        axis_labels.append(
            f'<text x="{x:.1f}" y="{height - 8}" '
            'fill="#91a3b8" font-size="10" '
            'text-anchor="middle">'
            f"{day:02d}</text>"
        )

    empty_state = ""

    if sum(daily_values) <= 0:
        empty_state = (
            f'<text x="{left + chart_w / 2:.1f}" '
            f'y="{top + chart_h / 2:.1f}" '
            'fill="#61758d" font-size="13" '
            'font-weight="700" text-anchor="middle">'
            'Belum ada ENS pada bulan berjalan'
            '</text>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" '
        'preserveAspectRatio="xMidYMid meet" '
        'class="svg-chart">'
        + "".join(grid)
        + "".join(bars)
        + "".join(data_labels)
        + "".join(axis_labels)
        + empty_state
        + "</svg>"
    )



def _transformer_frequency_rows(
    exposure_rows: list[dict[str, Any]],
) -> str:
    ranked = sorted(
        exposure_rows,
        key=lambda row: _safe_int(row.get("event_count")),
        reverse=True,
    )[:5]

    if not ranked:
        return (
            '<div class="transformer-empty">'
            'Belum ada gangguan downstream yang terpetakan ke Trafo '
            'pada bulan berjalan.'
            '</div>'
        )

    max_count = max(
        max(_safe_int(row.get("event_count")) for row in ranked),
        1,
    )

    parts: list[str] = []

    for row in ranked:
        trafo_name = _first_value(
            row,
            "transformer_bay_name",
            "techidentno",
            default="Trafo -",
        )
        gi_name = _first_value(
            row,
            "gi_name",
            default="-",
        )
        event_count = _safe_int(row.get("event_count"))
        feeder_count = _safe_int(row.get("feeder_count"))
        pct = event_count / max_count * 100

        parts.append(
            (
                '<div class="trafo-frequency-row">'
                '<div class="trafo-frequency-name">'
                f'<strong>{escape(_short(trafo_name, 28))}</strong>'
                f'<span>{escape(_short(gi_name, 24))} • '
                f'{feeder_count} penyulang terdampak</span>'
                '</div>'
                '<div class="trafo-frequency-track">'
                f'<div class="trafo-frequency-fill" '
                f'style="width:{pct:.1f}%"></div>'
                '</div>'
                f'<div class="trafo-frequency-value">{event_count}</div>'
                '</div>'
            )
        )

    return "".join(parts)




def _today_status_html(
    *,
    total_today: int,
    trip_today: int,
    recovered_count: int,
    ens_today: float,
    avg_recovery: float,
    last_event_text: str,
) -> str:
    if total_today == 0:
        status_class = "green"
        status_text = "SYSTEM NORMAL"
        status_note = "Tidak ada gangguan hari ini"
    else:
        status_class = "amber" if total_today <= 2 else "red"
        status_text = "MONITORING"
        status_note = f"{total_today} gangguan tercatat hari ini"

    return (
        '<div class="today-status-panel">'
        f'<div class="today-status-badge {status_class}">{status_text}</div>'
        f'<div class="today-status-note">{escape(status_note)}</div>'
        '<div class="today-status-grid">'
        '<div class="today-status-item">'
        '<span>Gangguan</span>'
        f'<strong class="blue">{total_today}</strong>'
        '</div>'
        '<div class="today-status-item">'
        '<span>PMT Trip</span>'
        f'<strong class="amber">{trip_today}</strong>'
        '</div>'
        '<div class="today-status-item">'
        '<span>Sudah Pulih</span>'
        f'<strong class="green">{recovered_count}</strong>'
        '</div>'
        '<div class="today-status-item">'
        '<span>ENS Hari Ini</span>'
        f'<strong class="purple">{ens_today:,.1f}</strong>'
        '<small>kWh</small>'
        '</div>'
        '<div class="today-status-item">'
        '<span>Avg Recovery</span>'
        f'<strong>{avg_recovery:.1f}</strong>'
        '<small>menit</small>'
        '</div>'
        '<div class="today-status-item wide">'
        '<span>Gangguan Terakhir</span>'
        f'<strong>{escape(last_event_text)}</strong>'
        '</div>'
        '</div>'
        '</div>'
    )


def _monthly_insight_html(
    *,
    month_total: int,
    month_daily_average: float,
    peak_day_label: str,
    peak_day_value: int,
    normal_days: int,
    disturbed_days: int,
) -> str:
    total_days = max(normal_days + disturbed_days, 1)
    normal_pct = normal_days / total_days * 100.0

    return (
        '<div class="monthly-insight-wrap">'
        '<div class="monthly-insight-card">'
        '<span>Total Bulan Ini</span>'
        f'<strong class="amber">{month_total}</strong>'
        '<small>Kejadian</small>'
        '</div>'
        '<div class="monthly-insight-card">'
        '<span>Avg / Hari</span>'
        f'<strong>{month_daily_average:.1f}</strong>'
        '<small>Kejadian / hari</small>'
        '</div>'
        '<div class="monthly-insight-card">'
        '<span>Peak Day</span>'
        f'<strong class="blue">{escape(peak_day_label)}</strong>'
        f'<small>{peak_day_value} kejadian</small>'
        '</div>'
        '<div class="monthly-insight-card">'
        '<span>Hari Normal</span>'
        f'<strong class="green">{normal_days}</strong>'
        f'<small>{normal_pct:.0f}% bulan berjalan</small>'
        '</div>'
        '<div class="monthly-insight-card">'
        '<span>Hari Terganggu</span>'
        f'<strong class="red">{disturbed_days}</strong>'
        '<small>Hari dengan gangguan</small>'
        '</div>'
        '</div>'
    )

def _recovery_bars(
    values: list[tuple[str, int]],
) -> str:
    max_value = max(
        max((value for _, value in values), default=0),
        1,
    )

    rows: list[str] = []

    for label, value in values:
        pct = value / max_value * 100

        rows.append(
            (
                '<div class="mini-bar-row">'
                f'<div class="mini-bar-label">{escape(label)}</div>'
                '<div class="mini-bar-track">'
                f'<div class="mini-bar-fill green" style="width:{pct:.1f}%"></div>'
                "</div>"
                f'<div class="mini-bar-value">{value}</div>'
                "</div>"
            )
        )

    return "".join(rows)


def _recurring_bars(
    values: list[tuple[str, int]],
) -> str:
    max_value = max(
        max((value for _, value in values), default=0),
        1,
    )

    rows: list[str] = []

    for label, value in values:
        pct = value / max_value * 100

        rows.append(
            (
                '<div class="rank-row">'
                f'<div class="rank-name">{escape(_short(label, 26))}</div>'
                '<div class="rank-track">'
                f'<div class="rank-fill" style="width:{pct:.1f}%"></div>'
                "</div>"
                f'<div class="rank-value">{value}</div>'
                "</div>"
            )
        )

    return "".join(rows)


def _fault_phase_rows(
    phase_values: dict[str, float],
) -> str:
    max_value = max(max(phase_values.values()), 1.0)

    ranked = sorted(
        phase_values.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    first = ranked[0][0] if ranked else ""
    second = ranked[1][0] if len(ranked) > 1 else ""

    rows: list[str] = []

    for phase, value in phase_values.items():
        pct = value / max_value * 100

        tone = "blue"

        if value > 0 and phase == first:
            tone = "red"
        elif value > 0 and phase == second:
            tone = "amber"

        rows.append(
            (
                '<div class="fault-row">'
                f'<div class="fault-phase">{phase}</div>'
                f'<div class="fault-amp">{value:,.0f} A</div>'
                '<div class="fault-track">'
                f'<div class="fault-fill {tone}" style="width:{pct:.1f}%"></div>'
                "</div>"
                "</div>"
            )
        )

    return "".join(rows)


# ==========================================================
# WALLBOARD CSS
# ==========================================================


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg: #07101c;
            --panel: #0d1827;
            --panel2: #101d2e;
            --border: #1f3b59;
            --soft-border: #182b41;
            --text: #f5f7fb;
            --muted: #91a3b8;
            --blue: #3b9cff;
            --green: #39d353;
            --amber: #ffb020;
            --red: #ff4d55;
            --purple: #b46cff;
        }

        html, body,
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"] {
            background: var(--bg) !important;
        }

        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        [data-testid="stStatusWidget"],
        [data-testid="collapsedControl"],
        section[data-testid="stSidebar"],
        footer {
            display: none !important;
        }

        [data-testid="stAppViewContainer"],
        [data-testid="stMain"] {
            overflow: hidden !important;
        }

        .block-container {
            width: 100vw !important;
            max-width: none !important;
            height: 100vh !important;
            max-height: 100vh !important;
            overflow: hidden !important;
            padding: 10px 12px !important;
        }

        [data-testid="stVerticalBlock"] {
            gap: 0 !important;
        }

        .wallboard {
            width: calc(100vw - 24px);
            height: calc(100vh - 86px);
            display: grid;
            grid-template-rows:
                98px
                minmax(300px, 1fr)
                218px
                62px;
            gap: 8px;
            color: var(--text);
            font-family:
                Inter,
                ui-sans-serif,
                system-ui,
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                sans-serif;
            overflow: hidden;
        }

        .panel,
        .header-block,
        .kpi-strip,
        .attention-bar {
            border: 1px solid var(--border);
            border-radius: 10px;
            background:
                linear-gradient(
                    145deg,
                    rgba(18,33,51,.98),
                    rgba(8,20,34,.98)
                );
            overflow: hidden;
        }

        /* HEADER */

        .brand {
            display: flex;
            align-items: center;
            gap: 14px;
            padding: 10px 15px;
        }

        .brand-omc {
            font-size: 31px;
            font-weight: 900;
            letter-spacing: -.05em;
            padding-right: 15px;
            border-right: 1px solid var(--border);
        }

        .brand-title {
            font-size: 18px;
            line-height: 1;
            font-weight: 850;
        }

        .brand-subtitle {
            color: var(--blue);
            font-size: 9px;
            font-weight: 800;
            margin-top: 7px;
            letter-spacing: .04em;
        }

        .head-card {
            padding: 8px 11px;
        }

        .head-label {
            color: var(--muted);
            font-size: 6.8px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: .08em;
        }

        .head-time {
            font-size: 17px;
            font-weight: 900;
            margin-top: 5px;
            line-height: 1;
        }

        .head-date {
            color: var(--text);
            font-size: 7px;
            font-weight: 700;
            margin-top: 2px;
        }

        .live {
            color: var(--green);
            font-size: 10px;
            font-weight: 900;
            margin-top: 7px;
        }

        .live::before {
            content: "";
            display: inline-block;
            width: 6px;
            height: 6px;
            border-radius: 50%;
            margin-right: 5px;
            background: var(--green);
            box-shadow: 0 0 7px rgba(57,211,83,.65);
        }

        .head-note {
            color: var(--muted);
            font-size: 6.3px;
            margin-top: 4px;
        }

        /* KPI */
        .kpi-strip {
            display: grid;
            grid-template-columns: repeat(7, minmax(0, 1fr));
        }

        .kpi {
            min-width: 0;
            padding: 10px 11px;
            border-right: 1px solid var(--border);
        }

        .kpi:last-child {
            border-right: 0;
        }

        .kpi-label {
            color: var(--muted);
            font-size: 8.5px;
            font-weight: 850;
            text-transform: uppercase;
            letter-spacing: .04em;
            white-space: nowrap;
        }

        .kpi-value {
            font-size: 27px;
            font-weight: 900;
            line-height: 1;
            margin-top: 7px;
        }

        .kpi-note {
            color: var(--muted);
            font-size: 7.4px;
            margin-top: 6px;
            line-height: 1.15;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .kpi-note strong {
            color: var(--text);
        }

        .kpi-dual {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-top: 8px;
        }

        .kpi-dual-item {
            min-width: 0;
        }

        .kpi-dual-label {
            color: var(--muted);
            font-size: 6.8px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: .035em;
        }

        .kpi-dual-value {
            color: var(--text);
            font-size: 15px;
            font-weight: 900;
            margin-top: 3px;
            line-height: 1;
        }

        .kpi-dual-value.red { color: var(--red); }
        .kpi-dual-value.blue { color: var(--blue); }
        .kpi-dual-value.green { color: var(--green); }
        .kpi-dual-value.amber { color: var(--amber); }
        .kpi-dual-value.purple { color: var(--purple); }

        .latest-history {
            margin-top: 8px;
            padding-top: 7px;
            border-top: 1px solid rgba(31,59,89,.55);
        }

        .latest-history-title {
            color: var(--muted);
            font-size: 7px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: .045em;
            margin-bottom: 4px;
        }

        .latest-history-row {
            display: grid;
            grid-template-columns: 52px minmax(0,1.05fr) minmax(0,.82fr) minmax(0,1.25fr) 74px 54px;
            gap: 7px;
            align-items: center;
            padding: 3px 0;
            border-bottom: 1px solid rgba(31,59,89,.28);
        }

        .latest-history-row:last-child {
            border-bottom: 0;
        }

        .latest-history-time {
            color: var(--blue);
            font-size: 7.4px;
            font-weight: 850;
        }

        .latest-history-feeder {
            color: var(--text);
            font-size: 7.4px;
            font-weight: 800;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .latest-history-relay {
            color: var(--blue);
            font-size: 7.2px;
            font-weight: 800;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .latest-history-area {
            color: #c3cfdd;
            font-size: 7px;
            line-height: 1.2;
            font-weight: 700;
            white-space: normal;
            overflow-wrap: anywhere;
            word-break: break-word;
        }

        .latest-insight-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 7px;
            margin-top: 10px;
            padding-top: 8px;
            border-top: 1px solid rgba(31,59,89,.45);
        }

        .latest-insight-card {
            border: 1px solid var(--soft-border);
            border-radius: 7px;
            padding: 8px 9px;
            background: rgba(4,13,23,.30);
            min-width: 0;
        }

        .latest-insight-label {
            color: var(--muted);
            font-size: 6.8px;
            text-transform: uppercase;
            letter-spacing: .035em;
            font-weight: 800;
        }

        .latest-insight-value {
            color: var(--text);
            font-size: 11px;
            font-weight: 900;
            margin-top: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .latest-insight-note {
            color: var(--muted);
            font-size: 6.2px;
            margin-top: 3px;
            line-height: 1.2;
        }


        .latest-history-status {
            font-size: 7px;
            font-weight: 850;
            text-align: center;
        }

        .latest-history-duration {
            color: var(--muted);
            font-size: 7px;
            text-align: right;
        }

        .red { color: var(--red) !important; }
        .blue { color: var(--blue) !important; }
        .green { color: var(--green) !important; }
        .amber { color: var(--amber) !important; }
        .purple { color: var(--purple) !important; }

        /* ROWS */
        .main-row {
            display: grid;
            grid-template-columns:
                minmax(0, .78fr)
                minmax(0, 1.22fr);
            gap: 8px;
            min-height: 0;
        }

        .lower-row {
            display: grid;
            grid-template-columns:
                minmax(0, 1.08fr)
                minmax(0, .78fr)
                minmax(0, 1.08fr);
            gap: 8px;
            min-height: 0;
        }

        .panel {
            min-height: 0;
            display: flex;
            flex-direction: column;
        }

        .panel-title {
            height: 30px;
            flex: 0 0 30px;
            display: flex;
            align-items: center;
            padding: 0 11px;
            color: var(--blue);
            font-size: 9px;
            font-weight: 900;
            text-transform: uppercase;
            letter-spacing: .04em;
            border-bottom: 1px solid rgba(31,59,89,.58);
        }

        .panel-title.red-title {
            color: var(--red);
        }

        .panel-body {
            min-height: 0;
            flex: 1 1 auto;
            height: 100%;
        }

        /* ACTIVE INCIDENT */
        .incident-body {
            padding: 8px 11px;
            display: grid;
            grid-template-rows: 50px auto 49px 1fr;
            align-content: stretch;
            gap: 6px;
        }

        .incident-top {
            display: grid;
            grid-template-columns: 49px 1fr;
            gap: 10px;
            align-items: center;
        }

        .incident-count {
            height: 46px;
            border: 1px solid rgba(255,77,85,.78);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            font-weight: 900;
            background: rgba(255,77,85,.045);
        }

        .incident-gi {
            font-size: 11px;
            font-weight: 900;
        }

        .incident-feeder {
            color: var(--red);
            font-size: 10px;
            font-weight: 900;
            margin-top: 4px;
        }

        .incident-normal {
            color: var(--green);
        }

        .incident-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            column-gap: 16px;
            min-height: 0;
            align-content: start;
        }

        .detail-row {
            display: grid;
            grid-template-columns: 1fr .9fr;
            gap: 6px;
            min-width: 0;
            padding: 5px 0;
            border-bottom: 1px solid rgba(31,59,89,.36);
        }

        .detail-label {
            color: var(--muted);
            font-size: 8px;
        }

        .detail-value {
            color: var(--text);
            font-size: 8px;
            font-weight: 850;
            text-align: right;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .incident-mini-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 6px;
        }

        .incident-mini {
            border: 1px solid var(--soft-border);
            border-radius: 7px;
            padding: 6px 7px;
            background: rgba(4,13,23,.35);
            min-width: 0;
        }

        .incident-mini-label {
            color: var(--muted);
            font-size: 7px;
        }

        .incident-mini-value {
            font-size: 12px;
            font-weight: 900;
            margin-top: 3px;
        }

        /* TREND */
        .trend-body {
            padding: 8px 10px 8px 10px;
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 132px;
            gap: 10px;
            align-items: stretch;
        }

        .trend-chart-box {
            min-width: 0;
            display: grid;
            grid-template-rows: 24px minmax(0, 1fr);
            border: 1px solid rgba(31,59,89,.46);
            border-radius: 9px;
            padding: 8px 10px 6px 10px;
            background: rgba(4,13,23,.26);
            overflow: hidden;
        }

        .trend-chart-label {
            color: var(--muted);
            font-size: 7.5px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: .04em;
        }

        .svg-chart {
            width: 100%;
            height: 100%;
            min-height: 0;
            display: block;
            overflow: visible;
        }

        .trend-summary {
            display: grid;
            grid-template-rows: repeat(3, 1fr);
            gap: 8px;
        }

        .trend-chart-label {
            color: #c7d3df;
            font-size: 8.6px;
            font-weight: 850;
            letter-spacing: .03em;
        }

        .trend-summary .summary-box {
            display: flex;
            flex-direction: column;
            justify-content: center;
        }


        .trend-body.version-a {
            display: grid;
            grid-template-rows: 58px minmax(230px, 1fr);
            gap: 8px;
            padding: 8px 10px 8px 10px;
            overflow: hidden;
            height: 100%;
            min-height: 0;
        }

        .trend-insight-strip {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 7px;
            min-height: 0;
        }

        .trend-insight-card {
            border: 1px solid var(--soft-border);
            border-radius: 8px;
            background: rgba(4,13,23,.34);
            padding: 7px 9px;
            min-width: 0;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }

        .trend-insight-card span {
            color: var(--muted);
            font-size: 6.4px;
            display: block;
        }

        .trend-insight-card strong {
            color: var(--text);
            font-size: 12px;
            font-weight: 900;
            line-height: 1;
            margin-top: 3px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .trend-insight-card small {
            color: var(--muted);
            font-size: 5.7px;
            display: block;
            margin-top: 3px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .trend-chart-grid {
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
            gap: 10px;
            min-height: 230px;
            height: 100%;
            overflow: hidden;
            align-items: stretch;
        }

        .trend-chart-grid .trend-metric-card {
            display: grid !important;
            grid-template-rows: 40px 1fr !important;
            min-height: 230px !important;
            height: 100% !important;
            overflow: hidden !important;
        }

        .trend-chart-grid .trend-metric-card > div:last-child {
            min-height: 0 !important;
            height: auto !important;
            overflow: hidden !important;
            display: flex !important;
            align-items: center !important;
        }

        .trend-chart-grid .svg-chart {
            width: 100% !important;
            height: 220px !important;
            min-height: 220px !important;
            max-height: 220px !important;
            display: block !important;
        }

        .trend-metric-card {
            height: 100%;
            min-height: 0;
        }

        .trend-metric-card > div:last-child {
            min-height: 150px;
            height: 100%;
            display: flex;
            align-items: stretch;
        }

        .trend-metric-card > div:last-child .svg-chart {
            width: 100%;
            height: 100%;
            min-height: 150px;
            display: block;
        }

        .trend-metric-card {
            min-width: 0;
            min-height: 0;
            display: grid;
            grid-template-rows: 34px minmax(0, 1fr);
            border: 1px solid rgba(31,59,89,.46);
            border-radius: 9px;
            padding: 8px 10px 6px 10px;
            background: rgba(4,13,23,.26);
            overflow: hidden;
        }

        .trend-metric-head {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 8px;
            min-width: 0;
        }

        .trend-metric-title {
            color: #c7d3df;
            font-size: 8.7px;
            font-weight: 900;
            text-transform: uppercase;
            letter-spacing: .035em;
        }

        .trend-metric-subtitle {
            color: var(--muted);
            font-size: 6.5px;
            margin-top: 3px;
        }

        .trend-metric-badge {
            flex: 0 0 auto;
            border: 1px solid var(--soft-border);
            border-radius: 7px;
            padding: 5px 7px;
            background: rgba(7,17,29,.52);
            text-align: right;
        }

        .trend-metric-badge span {
            color: var(--muted);
            display: block;
            font-size: 5.8px;
        }

        .trend-metric-badge strong {
            display: block;
            margin-top: 2px;
            font-size: 10px;
            line-height: 1;
        }

        .today-status-panel {
            height: 100%;
            border: 1px solid rgba(31,59,89,.46);
            border-radius: 9px;
            padding: 12px;
            background: rgba(4,13,23,.28);
            overflow: hidden;
        }

        .today-status-badge {
            display: inline-flex;
            align-items: center;
            min-height: 26px;
            padding: 0 10px;
            border-radius: 999px;
            font-size: 8.5px;
            font-weight: 900;
            letter-spacing: .05em;
            border: 1px solid currentColor;
            background: rgba(255,255,255,.02);
        }

        .today-status-note {
            color: var(--muted);
            font-size: 7.2px;
            margin-top: 8px;
        }

        .today-status-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 7px;
            margin-top: 10px;
        }

        .today-status-item {
            border: 1px solid var(--soft-border);
            border-radius: 7px;
            padding: 8px;
            background: rgba(7,17,29,.46);
            min-width: 0;
        }

        .today-status-item.wide {
            grid-column: 1 / -1;
        }

        .today-status-item span {
            color: var(--muted);
            font-size: 6.7px;
            display: block;
        }

        .today-status-item strong {
            color: var(--text);
            font-size: 13px;
            font-weight: 900;
            display: block;
            margin-top: 4px;
            line-height: 1.1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .today-status-item small {
            color: var(--muted);
            font-size: 5.8px;
            display: block;
            margin-top: 2px;
        }

        .monthly-chart-panel {
            height: 100%;
            border: 1px solid rgba(31,59,89,.46);
            border-radius: 9px;
            padding: 8px 10px 6px 10px;
            background: rgba(4,13,23,.26);
            display: grid;
            grid-template-rows: 24px minmax(0, 1fr);
            overflow: hidden;
        }

        .monthly-insight-wrap {
            height: 100%;
            display: grid;
            grid-template-rows: repeat(5, 1fr);
            gap: 7px;
        }

        .monthly-insight-card {
            border: 1px solid var(--soft-border);
            border-radius: 8px;
            padding: 8px 9px;
            background: rgba(4,13,23,.38);
            display: flex;
            flex-direction: column;
            justify-content: center;
            min-height: 0;
        }

        .monthly-insight-card span {
            color: var(--muted);
            font-size: 6.5px;
        }

        .monthly-insight-card strong {
            color: var(--text);
            font-size: 14px;
            font-weight: 900;
            margin-top: 3px;
            line-height: 1;
        }

        .monthly-insight-card small {
            color: var(--muted);
            font-size: 5.8px;
            margin-top: 3px;
        }

        .transformer-analysis {
            padding: 9px 11px;
        }

        .transformer-analysis-subtitle {
            color: var(--muted);
            font-size: 7.2px;
            line-height: 1.35;
            margin-bottom: 8px;
        }

        .trafo-frequency-row {
            display: grid;
            grid-template-columns: 145px 1fr 26px;
            gap: 8px;
            align-items: center;
            min-height: 30px;
            padding: 3px 0;
        }

        .trafo-frequency-name {
            min-width: 0;
        }

        .trafo-frequency-name strong {
            color: var(--text);
            font-size: 7.8px;
            display: block;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .trafo-frequency-name span {
            color: var(--muted);
            font-size: 6.3px;
            display: block;
            margin-top: 2px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .trafo-frequency-track {
            height: 12px;
            background: #07111d;
            border-radius: 4px;
            overflow: hidden;
        }

        .trafo-frequency-fill {
            height: 100%;
            border-radius: 4px;
            background: linear-gradient(90deg, #3b9cff, #27c5f9);
        }

        .trafo-frequency-value {
            color: var(--text);
            font-size: 9px;
            font-weight: 900;
            text-align: right;
        }

        .transformer-empty {
            color: var(--muted);
            font-size: 8px;
            line-height: 1.45;
            padding: 22px 8px;
            text-align: center;
        }

        .summary-box {
            border: 1px solid var(--soft-border);
            border-radius: 8px;
            padding: 10px;
            background: rgba(4,13,23,.38);
        }

        .summary-label {
            color: var(--muted);
            font-size: 7px;
        }

        .summary-value {
            font-size: 18px;
            font-weight: 900;
            margin-top: 4px;
        }

        .summary-unit {
            color: var(--muted);
            font-size: 6.8px;
            margin-top: 2px;
        }

        /* FAULT */
        .fault-body {
            padding: 9px 11px;
            display: grid;
            grid-template-columns: 1.12fr .82fr;
            gap: 12px;
        }

        .fault-row {
            display: grid;
            grid-template-columns: 14px 48px 1fr;
            gap: 6px;
            align-items: center;
            height: 29px;
        }

        .fault-phase {
            font-size: 9px;
            font-weight: 900;
        }

        .fault-amp {
            font-size: 8px;
            text-align: right;
        }

        .fault-track {
            height: 8px;
            border-radius: 4px;
            background: #07111d;
            overflow: hidden;
        }

        .fault-fill {
            height: 100%;
            border-radius: 4px;
        }

        .fault-fill.blue { background: var(--blue); }
        .fault-fill.red { background: var(--red); }
        .fault-fill.amber { background: var(--amber); }

        .fault-meta-row {
            display: grid;
            grid-template-columns: 1fr .9fr;
            gap: 6px;
            padding: 5px 0;
        }

        .fault-meta-label {
            color: var(--muted);
            font-size: 7.2px;
        }

        .fault-meta-value {
            font-size: 7.2px;
            font-weight: 850;
            text-align: right;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        /* RECOVERY */
        .mini-bars {
            padding: 9px 11px;
        }

        .mini-bar-row {
            display: grid;
            grid-template-columns: 71px 1fr 22px;
            gap: 7px;
            align-items: center;
            height: 32px;
        }

        .mini-bar-label {
            font-size: 8px;
            color: var(--text);
        }

        .mini-bar-track {
            height: 8px;
            background: #07111d;
            border-radius: 4px;
            overflow: hidden;
        }

        .mini-bar-fill {
            height: 100%;
            border-radius: 4px;
        }

        .mini-bar-fill.green {
            background: var(--green);
        }

        .mini-bar-value {
            font-size: 8px;
            font-weight: 900;
            text-align: right;
        }

        .recovery-foot {
            display: flex;
            justify-content: space-between;
            margin-top: 8px;
            padding-top: 7px;
            border-top: 1px solid rgba(31,59,89,.42);
            font-size: 7px;
        }

        /* RECURRING */
        .ranking {
            padding: 8px 11px;
        }

        .rank-row {
            display: grid;
            grid-template-columns: 112px 1fr 22px;
            gap: 7px;
            align-items: center;
            height: 32px;
        }

        .rank-name {
            font-size: 8px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .rank-track {
            height: 15px;
            background: #07111d;
            border-radius: 3px;
            overflow: hidden;
        }

        .rank-fill {
            height: 100%;
            background: var(--blue);
        }

        .rank-value {
            font-size: 8px;
            font-weight: 900;
            text-align: right;
        }

        /* ATTENTION */
        .attention-bar {
            display: grid;
            grid-template-columns: .8fr repeat(4, 1fr);
            min-height: 0;
        }

        .attention-title {
            padding: 9px 11px;
            color: var(--red);
            font-size: 10px;
            font-weight: 900;
            display: flex;
            align-items: center;
            border-right: 1px solid var(--border);
        }

        .attention-item {
            padding: 8px 11px;
            border-right: 1px solid var(--border);
            min-width: 0;
        }

        .attention-item:last-child {
            border-right: 0;
        }

        .attention-item strong {
            font-size: 7.6px;
            font-weight: 900;
            display: block;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .attention-item span {
            color: var(--muted);
            font-size: 6.6px;
            line-height: 1.25;
            margin-top: 4px;
            display: block;
        }

        @media (max-height: 900px) {
            .wallboard {
                grid-template-rows:
                    72px
                    minmax(225px, 1fr)
                    190px
                    48px;
                gap: 6px;
            }

            .header {
                gap: 6px;
            }

            .brand-omc {
                font-size: 26px;
            }

            .brand-title {
                font-size: 15px;
            }

            .kpi-value {
                font-size: 21px;
            }

            .panel-title {
                height: 24px;
                flex-basis: 24px;
            }

            .fault-row,
            .mini-bar-row,
            .rank-row {
                height: 26px;
            }

            .trend-body.version-a {
                grid-template-rows: 50px minmax(180px, 1fr);
            }

            .trend-chart-grid {
                min-height: 180px;
            }

            .trend-chart-grid .trend-metric-card {
                min-height: 180px !important;
            }

            .trend-chart-grid .svg-chart {
                height: 170px !important;
                min-height: 170px !important;
                max-height: 170px !important;
            }
        }

        /* =====================================================
           TREND RELIABILITY — PROPORTIONAL LAYOUT OVERRIDE
           Layout only; no content is added/removed.
           ===================================================== */

        .trend-body.version-a {
            display: flex !important;
            flex-direction: column !important;
            width: 100% !important;
            height: 100% !important;
            min-height: 0 !important;
            gap: 10px !important;
            padding: 8px 10px 10px 10px !important;
            overflow: hidden !important;
        }

        .trend-body.version-a > .trend-insight-strip {
            flex: 0 0 64px !important;
            width: 100% !important;
            min-width: 100% !important;
            display: grid !important;
            grid-template-columns: repeat(5, minmax(0, 1fr)) !important;
            gap: 8px !important;
        }

        .trend-body.version-a > .trend-chart-grid {
            flex: 1 1 auto !important;
            width: 100% !important;
            min-width: 100% !important;
            min-height: 0 !important;
            height: auto !important;
            display: grid !important;
            grid-template-columns:
                minmax(0, .78fr)
                minmax(0, 1.22fr) !important;
            grid-template-rows:
                minmax(0, 1fr)
                minmax(0, 1fr) !important;
            gap: 10px !important;
            align-items: stretch !important;
            overflow: hidden !important;
        }

        .trend-chart-grid .trend-slot-small-1 {
            grid-column: 1;
            grid-row: 1;
        }

        .trend-chart-grid .trend-slot-small-2 {
            grid-column: 1;
            grid-row: 2;
        }

        .trend-chart-grid .trend-slot-primary {
            grid-column: 2;
            grid-row: 1 / span 2;
        }

        .trend-chart-grid .trend-slot-primary .trend-metric-card {
            height: 100% !important;
        }

        .trend-chart-grid .trend-slot-small-1 .trend-metric-card,
        .trend-chart-grid .trend-slot-small-2 .trend-metric-card {
            height: 100% !important;
        }

        .trend-chart-slot {
            min-width: 0;
            min-height: 0;
            overflow: hidden;
        }

        .trend-body.version-a .trend-metric-card {
            min-width: 0 !important;
            min-height: 0 !important;
            height: 100% !important;
            display: flex !important;
            flex-direction: column !important;
            padding: 9px 11px 8px 11px !important;
            overflow: hidden !important;
        }

        .trend-body.version-a .trend-metric-head {
            flex: 0 0 38px !important;
            min-height: 38px !important;
        }

        .trend-body.version-a .trend-metric-card > div:last-child {
            flex: 1 1 auto !important;
            min-height: 0 !important;
            height: auto !important;
            width: 100% !important;
            display: flex !important;
            align-items: stretch !important;
            justify-content: stretch !important;
            overflow: hidden !important;
        }

        .trend-body.version-a .svg-chart {
            flex: 1 1 auto !important;
            width: 100% !important;
            height: 100% !important;
            min-width: 0 !important;
            min-height: 0 !important;
            max-height: none !important;
            display: block !important;
        }

        .trend-body.version-a .trend-insight-card {
            height: 64px !important;
            padding: 7px 9px !important;
        }

        .trend-body.version-a .trend-insight-card strong {
            font-size: 12px !important;
        }

        .trend-body.version-a .trend-metric-title {
            font-size: 9px !important;
        }

        .trend-body.version-a .trend-metric-subtitle {
            font-size: 6.8px !important;
        }

        @media (max-height: 900px) {
            .trend-body.version-a > .trend-insight-strip {
                flex-basis: 56px !important;
            }

            .trend-body.version-a .trend-insight-card {
                height: 56px !important;
            }

            .trend-body.version-a .trend-metric-head {
                flex-basis: 34px !important;
                min-height: 34px !important;
            }
        }


        .relay-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 5px 9px;
            margin-top: 4px;
            align-items: center;
        }

        .relay-legend-item {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            color: var(--muted);
            font-size: 6.2px;
            white-space: nowrap;
        }

        .relay-legend-dot {
            width: 7px;
            height: 7px;
            border-radius: 2px;
            flex: 0 0 auto;
        }

        .relay-legend-dot.ocr-inst { background: #ffb020; }
        .relay-legend-dot.ocr-td { background: #f59e0b; }
        .relay-legend-dot.gfr-inst { background: #ff4d55; }
        .relay-legend-dot.gfr-td { background: #ef6a6f; }
        .relay-legend-dot.system { background: #b46cff; }

        .trend-body.version-a .relay-chart-card .trend-metric-head {
            flex-basis: 52px !important;
            min-height: 52px !important;
        }


        .trend-slot-small-1 .trend-metric-card,
        .trend-slot-small-2 .trend-metric-card {
            padding: 7px 9px 5px 9px !important;
        }

        .trend-slot-small-1 .trend-metric-head,
        .trend-slot-small-2 .trend-metric-head {
            flex-basis: 32px !important;
            min-height: 32px !important;
        }

        .trend-slot-small-1 .trend-metric-title,
        .trend-slot-small-2 .trend-metric-title {
            font-size: 7.8px !important;
        }

        .trend-slot-small-1 .trend-metric-subtitle,
        .trend-slot-small-2 .trend-metric-subtitle {
            font-size: 5.9px !important;
        }

        .trend-slot-small-1 .svg-chart,
        .trend-slot-small-2 .svg-chart {
            height: 100% !important;
            min-height: 0 !important;
            max-height: none !important;
        }

        .trend-slot-primary .trend-metric-card {
            padding: 10px 12px 8px 12px !important;
        }

        .trend-slot-primary .trend-metric-head {
            flex-basis: 46px !important;
            min-height: 46px !important;
        }

        .trend-slot-primary .trend-metric-title {
            font-size: 9.5px !important;
        }

        .trend-slot-primary .trend-metric-subtitle {
            font-size: 6.9px !important;
        }

        .trend-slot-primary .svg-chart {
            height: 100% !important;
            min-height: 0 !important;
            max-height: none !important;
        }

        .trend-primary-badge {
            display: inline-flex;
            align-items: center;
            margin-left: 7px;
            padding: 2px 6px;
            border-radius: 999px;
            border: 1px solid var(--border);
            color: var(--blue);
            font-size: 5.8px;
            font-weight: 900;
            letter-spacing: .04em;
            vertical-align: middle;
        }

        .trend-slot-small-1 .relay-legend,
        .trend-slot-small-2 .relay-legend {
            gap: 3px 6px;
            margin-top: 2px;
        }

        .trend-slot-small-1 .relay-legend-item,
        .trend-slot-small-2 .relay-legend-item {
            font-size: 5.2px;
        }

        .trend-slot-primary .relay-legend {
            gap: 5px 10px;
            margin-top: 5px;
        }

        @media (max-height: 900px) {
            .trend-body.version-a > .trend-chart-grid {
                gap: 8px !important;
            }

            .trend-slot-small-1 .trend-metric-head,
            .trend-slot-small-2 .trend-metric-head {
                flex-basis: 28px !important;
                min-height: 28px !important;
            }

            .trend-slot-primary .trend-metric-head {
                flex-basis: 40px !important;
                min-height: 40px !important;
            }
        }


        /* COMPACT HEADER FILTERS */
        .header-filter-wrap {
            height: 100%;
            min-height: 0;
        }

        .header-filter-label {
            color: var(--muted);
            font-size: 6px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: .06em;
            margin: 0 0 3px 2px;
        }

        div[data-testid="stSelectbox"] {
            height: 100%;
            margin: 0 !important;
        }

        div[data-testid="stSelectbox"] label {
            display: none !important;
        }

        div[data-testid="stSelectbox"] > div {
            height: 100%;
        }


        div[data-testid="stSelectbox"] svg {
            fill: var(--muted) !important;
            width: 14px !important;
            height: 14px !important;
        }

        .compact-month-card {
            border: 1px solid var(--border);
            border-radius: 9px;
            background: linear-gradient(
                145deg,
                rgba(18,33,51,.98),
                rgba(8,20,34,.98)
            );
            padding: 7px 9px;
            height: 100%;
            min-height: 0;
            overflow: hidden;
        }

        .compact-month-label {
            color: var(--muted);
            font-size: 5.8px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: .06em;
        }

        .compact-month-value {
            color: var(--text);
            font-size: 9px;
            font-weight: 900;
            margin-top: 3px;
            line-height: 1;
        }

        .compact-month-note {
            color: var(--muted);
            font-size: 5.5px;
            margin-top: 3px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        @media (max-height: 900px) {
            div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
                height: 30px !important;
                min-height: 30px !important;
            }
        }


        /* =====================================================
           SINGLE HEADER — FINAL COMPACT OVERRIDE
           ===================================================== */

        .block-container {
            padding-top: 8px !important;
            padding-bottom: 8px !important;
        }

        /* Only the first Streamlit horizontal block is the header row. */
        [data-testid="stHorizontalBlock"]:has(.brand-title) {
            min-height: 82px !important;
            height: 82px !important;
            gap: 7px !important;
            margin-bottom: 6px !important;
            align-items: stretch !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"] {
            min-width: 0 !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stVerticalBlock"] {
            gap: 2px !important;
            height: 82px !important;
        }

        /* Compact selectbox header labels. */
        .header-filter-label {
            height: 13px;
            margin: 0 0 2px 2px !important;
            color: var(--muted) !important;
            font-size: 6px !important;
            font-weight: 850 !important;
            line-height: 13px !important;
        }

        /* Selectbox wrapper. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        div[data-testid="stSelectbox"] {
            height: 55px !important;
            min-height: 55px !important;
            margin: 0 !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        div[data-testid="stSelectbox"] > div {
            height: 38px !important;
            min-height: 38px !important;
        }

        /* BaseWeb select — force same dark theme as OMC panels. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-baseweb="select"] > div {
            height: 38px !important;
            min-height: 38px !important;
            background: #0d1827 !important;
            background-color: #0d1827 !important;
            border: 1px solid #1f3b59 !important;
            border-radius: 8px !important;
            box-shadow: none !important;
            color: #f5f7fb !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-baseweb="select"] input {
            color: #f5f7fb !important;
            caret-color: #f5f7fb !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-baseweb="select"] span,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-baseweb="select"] div {
            color: #f5f7fb !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-baseweb="select"] svg {
            fill: #91a3b8 !important;
            color: #91a3b8 !important;
        }

        /* Remove white focus/hover state. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-baseweb="select"] > div:hover,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-baseweb="select"] > div:focus-within {
            background: #101d2e !important;
            background-color: #101d2e !important;
            border-color: #2b5278 !important;
            box-shadow: 0 0 0 1px rgba(59,156,255,.12) !important;
        }

        /* Dropdown menu / option popup in dark mode. */
        [data-baseweb="popover"],
        [data-baseweb="menu"],
        [role="listbox"] {
            background: #0d1827 !important;
            background-color: #0d1827 !important;
            color: #f5f7fb !important;
            border-color: #1f3b59 !important;
        }

        [role="option"] {
            background: #0d1827 !important;
            color: #f5f7fb !important;
        }

        [role="option"]:hover,
        [aria-selected="true"][role="option"] {
            background: #15283e !important;
            color: #ffffff !important;
        }

        /* Header blocks use one consistent height. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        .header-block,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        .compact-month-card {
            height: 82px !important;
            min-height: 82px !important;
            box-sizing: border-box !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        .brand {
            padding: 8px 13px !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        .brand-omc {
            font-size: 27px !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        .brand-title {
            font-size: 15px !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        .brand-subtitle {
            font-size: 7px !important;
            margin-top: 5px !important;
        }

        /* Restore original wallboard density below header. */
        .wallboard {
            min-height: 0 !important;
            overflow: hidden !important;
        }

        @media (max-height: 900px) {
            .wallboard {
                height: calc(100vh - 88px) !important;
            }

            [data-testid="stHorizontalBlock"]:has(.brand-title) {
                min-height: 64px !important;
                height: 64px !important;
                margin-bottom: 5px !important;
            }

            [data-testid="stHorizontalBlock"]:has(.brand-title)
            [data-testid="stVerticalBlock"] {
                height: 64px !important;
            }

            [data-testid="stHorizontalBlock"]:has(.brand-title)
            .header-block,
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            .compact-month-card {
                height: 64px !important;
                min-height: 64px !important;
            }

            [data-testid="stHorizontalBlock"]:has(.brand-title)
            div[data-testid="stSelectbox"] {
                height: 49px !important;
                min-height: 49px !important;
            }

            [data-testid="stHorizontalBlock"]:has(.brand-title)
            [data-baseweb="select"] > div {
                height: 34px !important;
                min-height: 34px !important;
            }
        }


        /* =====================================================
           HEADER v19 — STACKED FILTERS + DARK THEME
           ===================================================== */

        [data-testid="stHorizontalBlock"]:has(.brand-title) {
            min-height: 82px !important;
            height: 82px !important;
            align-items: stretch !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stVerticalBlock"] {
            height: 82px !important;
            gap: 2px !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        .header-block,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        .compact-month-card {
            height: 82px !important;
            min-height: 82px !important;
        }

        /* Stacked ULTG + GI */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        [data-testid="stVerticalBlock"] {
            display: grid !important;
            grid-template-rows: 11px 27px 11px 27px !important;
            gap: 2px !important;
            align-content: center !important;
        }

        .header-filter-label {
            color: #91a3b8 !important;
            font-size: 5.8px !important;
            font-weight: 850 !important;
            height: 11px !important;
            line-height: 11px !important;
            margin: 0 0 0 2px !important;
        }

        .header-filter-label.gi-label {
            margin-top: 0 !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        div[data-testid="stSelectbox"] {
            min-height: 27px !important;
            height: 27px !important;
            margin: 0 !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        div[data-testid="stSelectbox"] > div {
            min-height: 27px !important;
            height: 27px !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-baseweb="select"] > div {
            min-height: 27px !important;
            height: 27px !important;
            background: #07101c !important;
            background-color: #07101c !important;
            border: 1px solid #1f3b59 !important;
            border-radius: 7px !important;
            color: #f5f7fb !important;
            box-shadow: none !important;
            padding-left: 8px !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-baseweb="select"] > div:hover,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-baseweb="select"] > div:focus-within {
            background: #0b1624 !important;
            background-color: #0b1624 !important;
            border-color: #2c5276 !important;
            box-shadow: 0 0 0 1px rgba(59,156,255,.10) !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-baseweb="select"] span,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-baseweb="select"] div,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-baseweb="select"] input {
            color: #f5f7fb !important;
            font-size: 7.5px !important;
            font-weight: 800 !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-baseweb="select"] svg {
            fill: #91a3b8 !important;
            color: #91a3b8 !important;
            width: 12px !important;
            height: 12px !important;
        }

        /* Month running card — larger typography */
        .compact-month-card {
            padding: 10px 11px !important;
            display: flex !important;
            flex-direction: column !important;
            justify-content: center !important;
        }

        .compact-month-label {
            font-size: 6.6px !important;
            font-weight: 850 !important;
            letter-spacing: .06em !important;
        }

        .compact-month-value {
            font-size: 11.5px !important;
            font-weight: 900 !important;
            margin-top: 5px !important;
            color: #f5f7fb !important;
        }

        .compact-month-note {
            font-size: 6.4px !important;
            margin-top: 5px !important;
            color: #91a3b8 !important;
        }

        /* Clock always white */
        .head-time {
            color: #ffffff !important;
            font-size: 18px !important;
            font-weight: 900 !important;
        }

        .head-time span {
            color: #c4cfdb !important;
        }

        .head-date {
            color: #f5f7fb !important;
        }

        /* Ensure dropdown popup stays black */
        [data-baseweb="popover"],
        [data-baseweb="menu"],
        [role="listbox"] {
            background: #07101c !important;
            background-color: #07101c !important;
            color: #f5f7fb !important;
            border: 1px solid #1f3b59 !important;
        }

        [role="option"] {
            background: #07101c !important;
            color: #f5f7fb !important;
        }

        [role="option"]:hover,
        [role="option"][aria-selected="true"] {
            background: #102033 !important;
            color: #ffffff !important;
        }

        @media (max-height: 900px) {
            .wallboard {
                height: calc(100vh - 102px) !important;
            }

            [data-testid="stHorizontalBlock"]:has(.brand-title),
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            [data-testid="stVerticalBlock"],
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            .header-block,
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            .compact-month-card {
                height: 76px !important;
                min-height: 76px !important;
            }

            [data-testid="stHorizontalBlock"]:has(.brand-title)
            [data-testid="stColumn"]:nth-child(2)
            [data-testid="stVerticalBlock"] {
                grid-template-rows: 10px 24px 10px 24px !important;
            }

            [data-testid="stHorizontalBlock"]:has(.brand-title)
            div[data-testid="stSelectbox"],
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            div[data-testid="stSelectbox"] > div,
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            [data-baseweb="select"] > div {
                height: 24px !important;
                min-height: 24px !important;
            }
        }


        /* =====================================================
           DROPDOWN v20 — DARK / COMPACT / GLOBAL OVERRIDE
           ===================================================== */

        [data-testid="stHorizontalBlock"]:has(.brand-title) {
            height: 72px !important;
            min-height: 72px !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stVerticalBlock"] {
            height: 72px !important;
            min-height: 72px !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        .header-block,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        .compact-month-card {
            height: 72px !important;
            min-height: 72px !important;
        }

        /* Filter column: 2 compact rows */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        [data-testid="stVerticalBlock"] {
            display: grid !important;
            grid-template-rows: 9px 22px 9px 22px !important;
            row-gap: 2px !important;
            align-content: center !important;
        }

        .header-filter-label {
            height: 9px !important;
            line-height: 9px !important;
            font-size: 5.4px !important;
            margin: 0 0 0 1px !important;
        }

        /* -------- SELECTBOX HEIGHT -------- */
        div[data-testid="stSelectbox"],
        div[data-testid="stSelectbox"] > div {
            height: 22px !important;
            min-height: 22px !important;
            margin: 0 !important;
            padding: 0 !important;
        }

        /* -------- SELECTBOX FIELD DARK -------- */
        div[data-baseweb="select"],
        div[data-baseweb="select"] > div,
        div[data-baseweb="select"] > div > div,
        div[data-baseweb="select"] [role="combobox"] {
            background: #07101c !important;
            background-color: #07101c !important;
            color: #f5f7fb !important;
        }

        div[data-baseweb="select"] > div {
            min-height: 22px !important;
            height: 22px !important;
            border: 1px solid #1f3b59 !important;
            border-radius: 6px !important;
            box-shadow: none !important;
            padding: 0 5px 0 7px !important;
        }

        /* Streamlit sometimes puts a separate white inner layer */
        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] * {
            background-color: transparent !important;
        }

        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] > div {
            background-color: #07101c !important;
        }

        /* Selected text */
        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] span,
        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] input,
        div[data-testid="stSelectbox"]
        [role="combobox"] {
            color: #f5f7fb !important;
            -webkit-text-fill-color: #f5f7fb !important;
            font-size: 6.8px !important;
            font-weight: 800 !important;
            line-height: 1 !important;
        }

        /* Arrow */
        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] svg {
            fill: #91a3b8 !important;
            color: #91a3b8 !important;
            width: 10px !important;
            height: 10px !important;
        }

        /* Hover/focus must remain dark */
        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] > div:hover,
        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] > div:focus,
        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] > div:focus-within {
            background: #0b1624 !important;
            background-color: #0b1624 !important;
            border-color: #2b5278 !important;
            box-shadow: 0 0 0 1px rgba(59,156,255,.10) !important;
        }

        /* Dropdown menu / options */
        body > div[data-baseweb="popover"],
        div[data-baseweb="popover"],
        div[data-baseweb="menu"],
        ul[role="listbox"] {
            background: #07101c !important;
            background-color: #07101c !important;
            border-color: #1f3b59 !important;
            color: #f5f7fb !important;
        }

        li[role="option"],
        div[role="option"] {
            background: #07101c !important;
            background-color: #07101c !important;
            color: #f5f7fb !important;
            font-size: 7.5px !important;
        }

        li[role="option"]:hover,
        div[role="option"]:hover,
        li[role="option"][aria-selected="true"],
        div[role="option"][aria-selected="true"] {
            background: #102033 !important;
            background-color: #102033 !important;
            color: #ffffff !important;
        }

        /* Keep month/time typography aligned to shorter header */
        .compact-month-card {
            padding: 7px 9px !important;
        }

        .compact-month-label {
            font-size: 6.1px !important;
        }

        .compact-month-value {
            font-size: 10.5px !important;
            margin-top: 4px !important;
        }

        .compact-month-note {
            font-size: 5.9px !important;
            margin-top: 4px !important;
        }

        .head-time {
            color: #ffffff !important;
            font-size: 17px !important;
        }

        @media (max-height: 900px) {
            .wallboard {
                height: calc(100vh - 90px) !important;
            }

            [data-testid="stHorizontalBlock"]:has(.brand-title),
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            [data-testid="stVerticalBlock"],
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            .header-block,
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            .compact-month-card {
                height: 66px !important;
                min-height: 66px !important;
            }

            [data-testid="stHorizontalBlock"]:has(.brand-title)
            [data-testid="stColumn"]:nth-child(2)
            [data-testid="stVerticalBlock"] {
                grid-template-rows: 8px 20px 8px 20px !important;
            }

            div[data-testid="stSelectbox"],
            div[data-testid="stSelectbox"] > div,
            div[data-baseweb="select"] > div {
                height: 20px !important;
                min-height: 20px !important;
            }
        }


        /* =====================================================
           DROPDOWN v21 — FORCE DARK FIELD + SHORT VERTICAL SIZE
           ===================================================== */

        /* Filter stack: keep width, shorten only vertically. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        [data-testid="stVerticalBlock"] {
            grid-template-rows: 8px 18px 8px 18px !important;
            row-gap: 2px !important;
            align-content: center !important;
        }

        .header-filter-label {
            height: 8px !important;
            line-height: 8px !important;
            font-size: 5.2px !important;
            margin: 0 0 0 1px !important;
        }

        /* Streamlit selectbox outer layers */
        div[data-testid="stSelectbox"],
        div[data-testid="stSelectbox"] > div,
        div[data-testid="stSelectbox"] > div > div,
        div[data-testid="stSelectbox"] div[data-baseweb="select"],
        div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
        div[data-testid="stSelectbox"] div[data-baseweb="select"] > div > div,
        div[data-testid="stSelectbox"] [role="combobox"] {
            min-height: 18px !important;
            height: 18px !important;
            max-height: 18px !important;
            background: #07101c !important;
            background-color: #07101c !important;
            color: #f5f7fb !important;
            border-color: #1f3b59 !important;
            box-shadow: none !important;
        }

        /* This catches the light input/selected-value layer. */
        div[data-testid="stSelectbox"] input,
        div[data-testid="stSelectbox"] input[aria-autocomplete],
        div[data-testid="stSelectbox"] [role="combobox"] input {
            min-height: 16px !important;
            height: 16px !important;
            background: #07101c !important;
            background-color: #07101c !important;
            color: #f5f7fb !important;
            -webkit-text-fill-color: #f5f7fb !important;
            caret-color: #f5f7fb !important;
            border: none !important;
            box-shadow: none !important;
            padding: 0 !important;
        }

        /* Preserve black only on structural layers; text layers stay transparent. */
        div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
            border: 1px solid #1f3b59 !important;
            border-radius: 5px !important;
            padding: 0 4px 0 7px !important;
            overflow: hidden !important;
        }

        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] > div > div {
            border: 0 !important;
            border-radius: 0 !important;
            padding: 0 !important;
        }

        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] span,
        div[data-testid="stSelectbox"]
        [role="combobox"],
        div[data-testid="stSelectbox"]
        [role="combobox"] * {
            color: #f5f7fb !important;
            -webkit-text-fill-color: #f5f7fb !important;
            font-size: 6.5px !important;
            font-weight: 800 !important;
            line-height: 16px !important;
        }

        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] svg {
            width: 9px !important;
            height: 9px !important;
            fill: #91a3b8 !important;
            color: #91a3b8 !important;
        }

        /* Kill the browser/BaseWeb light focus layer and red focus ring. */
        div[data-testid="stSelectbox"] *:focus,
        div[data-testid="stSelectbox"] *:focus-visible,
        div[data-testid="stSelectbox"] *:focus-within {
            outline: none !important;
            box-shadow: none !important;
        }

        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] > div:hover,
        div[data-testid="stSelectbox"]
        div[data-baseweb="select"] > div:focus-within {
            background: #0b1624 !important;
            background-color: #0b1624 !important;
            border-color: #2b5278 !important;
            box-shadow: none !important;
        }

        /* Dropdown popup remains dark. */
        div[data-baseweb="popover"],
        div[data-baseweb="menu"],
        ul[role="listbox"],
        div[role="listbox"] {
            background: #07101c !important;
            background-color: #07101c !important;
            border: 1px solid #1f3b59 !important;
            color: #f5f7fb !important;
        }

        li[role="option"],
        div[role="option"] {
            min-height: 24px !important;
            background: #07101c !important;
            background-color: #07101c !important;
            color: #f5f7fb !important;
            font-size: 7px !important;
        }

        li[role="option"]:hover,
        div[role="option"]:hover,
        li[role="option"][aria-selected="true"],
        div[role="option"][aria-selected="true"] {
            background: #102033 !important;
            background-color: #102033 !important;
            color: #ffffff !important;
        }

        @media (max-height: 900px) {
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            [data-testid="stColumn"]:nth-child(2)
            [data-testid="stVerticalBlock"] {
                grid-template-rows: 7px 17px 7px 17px !important;
            }

            div[data-testid="stSelectbox"],
            div[data-testid="stSelectbox"] > div,
            div[data-testid="stSelectbox"] div[data-baseweb="select"],
            div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
            div[data-testid="stSelectbox"] [role="combobox"] {
                min-height: 17px !important;
                height: 17px !important;
                max-height: 17px !important;
            }
        }


        /* =====================================================
           HEADER FILTER v22 — NO LABELS / PROPORTIONAL WIDTH
           ===================================================== */

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        [data-testid="stVerticalBlock"] {
            display: grid !important;
            grid-template-rows: 20px 20px !important;
            row-gap: 5px !important;
            align-content: center !important;
            height: 72px !important;
            min-height: 72px !important;
        }

        /* No visible dropdown labels */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        .header-filter-label {
            display: none !important;
        }

        /* Preserve horizontal width, only compact vertical height */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        div[data-testid="stSelectbox"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        div[data-testid="stSelectbox"] > div,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] > div {
            width: 100% !important;
            min-width: 100% !important;
            height: 20px !important;
            min-height: 20px !important;
            max-height: 20px !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] > div {
            padding-left: 8px !important;
            padding-right: 5px !important;
            border-radius: 5px !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] span,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        [role="combobox"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        input {
            font-size: 6.7px !important;
            line-height: 18px !important;
        }

        @media (max-height: 900px) {
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            [data-testid="stColumn"]:nth-child(2)
            [data-testid="stVerticalBlock"] {
                grid-template-rows: 18px 18px !important;
                row-gap: 4px !important;
                height: 66px !important;
                min-height: 66px !important;
            }

            [data-testid="stHorizontalBlock"]:has(.brand-title)
            [data-testid="stColumn"]:nth-child(2)
            div[data-testid="stSelectbox"],
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            [data-testid="stColumn"]:nth-child(2)
            div[data-testid="stSelectbox"] > div,
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            [data-testid="stColumn"]:nth-child(2)
            div[data-baseweb="select"],
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            [data-testid="stColumn"]:nth-child(2)
            div[data-baseweb="select"] > div {
                height: 18px !important;
                min-height: 18px !important;
                max-height: 18px !important;
            }
        }


        /* =====================================================
           HEADER v23 — PROPORTIONAL FILTER + WHITE BRAND
           ===================================================== */

        /* Brand text */
        .brand-omc,
        .brand-title {
            color: #ffffff !important;
            opacity: 1 !important;
        }

        .brand-subtitle {
            color: #3b9cff !important;
            opacity: 1 !important;
        }

        /* Give filter column enough width to visually match neighbors */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2) {
            min-width: 0 !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        div[data-testid="stSelectbox"] {
            width: 100% !important;
            min-width: 100% !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] > div {
            width: 100% !important;
            min-width: 100% !important;
        }

        /* Slightly stronger readable text inside compact fields */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] span,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        [role="combobox"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        [data-testid="stColumn"]:nth-child(2)
        input {
            font-size: 7px !important;
            font-weight: 850 !important;
        }


        /* =====================================================
           HEADER v24 — FORCE FILTER COLUMN WIDTH
           Streamlit column ratios were not affecting the
           selectbox width reliably, so force the 2nd header
           column and all nested select elements explicitly.
           ===================================================== */

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2) {
            flex: 0 0 230px !important;
            width: 230px !important;
            min-width: 230px !important;
            max-width: 230px !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        [data-testid="stVerticalBlock"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        [data-testid="stElementContainer"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-testid="stSelectbox"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-testid="stSelectbox"] > div,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] > div,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        [role="combobox"] {
            width: 100% !important;
            min-width: 100% !important;
            max-width: 100% !important;
            box-sizing: border-box !important;
        }

        /* Keep compact vertical dimensions. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-testid="stSelectbox"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-testid="stSelectbox"] > div,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] > div {
            height: 20px !important;
            min-height: 20px !important;
            max-height: 20px !important;
        }

        @media (max-width: 1600px) {
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2) {
                flex-basis: 205px !important;
                width: 205px !important;
                min-width: 205px !important;
                max-width: 205px !important;
            }
        }


        /* =====================================================
           HEADER v25 — PROPORTIONAL FILTER BOX
           ===================================================== */

        /* Let Streamlit column participate normally. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2) {
            flex: 1 1 0 !important;
            width: auto !important;
            min-width: 0 !important;
            max-width: none !important;
        }

        /* Center the stacked filter group within its column. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        > [data-testid="stVerticalBlock"] {
            width: 240px !important;
            min-width: 240px !important;
            max-width: 240px !important;
            margin-left: auto !important;
            margin-right: auto !important;

            display: grid !important;
            grid-template-rows: 20px 20px !important;
            row-gap: 5px !important;
            align-content: center !important;

            height: 72px !important;
            min-height: 72px !important;
        }

        /* Every nested wrapper follows the fixed visual width. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        [data-testid="stElementContainer"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-testid="stSelectbox"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-testid="stSelectbox"] > div,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] > div,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        [role="combobox"] {
            width: 240px !important;
            min-width: 240px !important;
            max-width: 240px !important;

            height: 20px !important;
            min-height: 20px !important;
            max-height: 20px !important;

            box-sizing: border-box !important;
        }

        /* Field styling stays compact and dark. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] > div {
            padding: 0 6px 0 9px !important;
            border-radius: 6px !important;
            background: #07101c !important;
            background-color: #07101c !important;
            border: 1px solid #1f3b59 !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] span,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        [role="combobox"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        input {
            font-size: 7px !important;
            font-weight: 850 !important;
            color: #f5f7fb !important;
            -webkit-text-fill-color: #f5f7fb !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] svg {
            width: 10px !important;
            height: 10px !important;
            fill: #91a3b8 !important;
            color: #91a3b8 !important;
        }

        /* Responsive widths, still proportional. */
        @media (max-width: 1700px) {
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            > [data-testid="stVerticalBlock"],
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            [data-testid="stElementContainer"],
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            div[data-testid="stSelectbox"],
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            div[data-testid="stSelectbox"] > div,
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            div[data-baseweb="select"],
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            div[data-baseweb="select"] > div,
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            [role="combobox"] {
                width: 220px !important;
                min-width: 220px !important;
                max-width: 220px !important;
            }
        }

        @media (max-width: 1450px) {
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            > [data-testid="stVerticalBlock"],
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            [data-testid="stElementContainer"],
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            div[data-testid="stSelectbox"],
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            div[data-testid="stSelectbox"] > div,
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            div[data-baseweb="select"],
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            div[data-baseweb="select"] > div,
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            [role="combobox"] {
                width: 200px !important;
                min-width: 200px !important;
                max-width: 200px !important;
            }
        }


        /* =====================================================
           HEADER v26 — OVERLAP SAFE FILTER WIDTH
           ===================================================== */

        /* Never let filter column overflow into the month card. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2) {
            min-width: 0 !important;
            overflow: hidden !important;
        }

        /* Parent filter stack follows the REAL Streamlit column width. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        > [data-testid="stVerticalBlock"] {
            width: 100% !important;
            min-width: 0 !important;
            max-width: 100% !important;
            margin: 0 !important;

            display: grid !important;
            grid-template-rows: 20px 20px !important;
            row-gap: 5px !important;
            align-content: center !important;

            height: 72px !important;
            min-height: 72px !important;
            overflow: hidden !important;
        }

        /* All wrappers fit inside the filter column. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        [data-testid="stElementContainer"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-testid="stSelectbox"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-testid="stSelectbox"] > div,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] > div,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        [role="combobox"] {
            width: 100% !important;
            min-width: 0 !important;
            max-width: 100% !important;

            height: 20px !important;
            min-height: 20px !important;
            max-height: 20px !important;

            box-sizing: border-box !important;
        }

        /* Give the visible select some inner breathing room. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] > div {
            padding: 0 6px 0 8px !important;
            border-radius: 6px !important;
            overflow: hidden !important;
        }

        /* Prevent selected text from pushing the field wider. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] span,
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        [role="combobox"] {
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            display: block !important;
        }

        /* Keep a clear gap before the month card. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(3) {
            min-width: 0 !important;
            overflow: hidden !important;
        }

        @media (max-width: 1550px) {
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            div[data-baseweb="select"] span,
            [data-testid="stHorizontalBlock"]:has(.brand-title)
            > [data-testid="stColumn"]:nth-child(2)
            [role="combobox"] {
                font-size: 6.4px !important;
            }
        }


        /* =====================================================
           HEADER v27 — WIDTH REBALANCE
           More room for ULTG/GI, less for Brand & Month
           ===================================================== */

        /* Brand block compact horizontally */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(1) {
            min-width: 0 !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        .brand {
            padding-left: 10px !important;
            padding-right: 10px !important;
            gap: 10px !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        .brand-omc {
            padding-right: 10px !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        .brand-subtitle {
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }

        /* Filter gets the room freed from brand/month */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2) {
            min-width: 0 !important;
            overflow: visible !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        > [data-testid="stVerticalBlock"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        [data-testid="stElementContainer"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-testid="stSelectbox"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] > div {
            width: 100% !important;
            max-width: 100% !important;
        }

        /* Month card compact horizontally */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(3) {
            min-width: 0 !important;
        }

        .compact-month-card {
            padding-left: 8px !important;
            padding-right: 8px !important;
        }

        .compact-month-note {
            white-space: nowrap !important;
        }


        /* =====================================================
           HEADER v28 — COMPACT CARDS, ORIGINAL TEXT SIZE
           ===================================================== */

        /* Brand card: reduce internal horizontal padding only. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        .brand {
            padding-left: 8px !important;
            padding-right: 8px !important;
            gap: 8px !important;
        }

        /* Month card: narrower card footprint, same typography. */
        .compact-month-card {
            padding-left: 7px !important;
            padding-right: 7px !important;
        }

        /* Keep original brand/month text sizing from earlier versions. */
        .brand-omc {
            font-size: 27px !important;
        }

        .brand-title {
            font-size: 15px !important;
        }

        .brand-subtitle {
            font-size: 7px !important;
        }

        .compact-month-label {
            font-size: 6.6px !important;
        }

        .compact-month-value {
            font-size: 11.5px !important;
        }

        .compact-month-note {
            font-size: 6.4px !important;
        }

        /* Filters use the extra horizontal space. */
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        > [data-testid="stVerticalBlock"] {
            width: 100% !important;
            max-width: 100% !important;
        }

        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-testid="stSelectbox"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"],
        [data-testid="stHorizontalBlock"]:has(.brand-title)
        > [data-testid="stColumn"]:nth-child(2)
        div[data-baseweb="select"] > div {
            width: 100% !important;
            max-width: 100% !important;
        }


        /* =====================================================
           HEADER v29 — TWO ROW / INLINE FILTER BAR
           ===================================================== */

        /* Main header row */
        [data-testid="stHorizontalBlock"]:has(.header-main-card) {
            height: 68px !important;
            min-height: 68px !important;
            gap: 7px !important;
            margin-bottom: 4px !important;
            align-items: stretch !important;
        }

        [data-testid="stHorizontalBlock"]:has(.header-main-card)
        [data-testid="stVerticalBlock"] {
            height: 68px !important;
            min-height: 68px !important;
        }

        .header-main-card {
            height: 68px !important;
            min-height: 68px !important;
            box-sizing: border-box !important;
        }

        .brand {
            padding: 8px 12px !important;
        }

        .brand-omc,
        .brand-title {
            color: #ffffff !important;
            opacity: 1 !important;
        }

        .brand-omc {
            font-size: 27px !important;
        }

        .brand-title {
            font-size: 15px !important;
        }

        .brand-subtitle {
            color: #3b9cff !important;
            font-size: 7px !important;
        }

        .head-time {
            color: #ffffff !important;
        }

        /* Inline filter row */
        [data-testid="stHorizontalBlock"]:has(.filter-inline-info) {
            height: 28px !important;
            min-height: 28px !important;
            gap: 7px !important;
            margin-bottom: 5px !important;
            align-items: stretch !important;
        }

        [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
        > [data-testid="stColumn"] {
            min-width: 0 !important;
        }

        [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
        [data-testid="stVerticalBlock"] {
            height: 28px !important;
            min-height: 28px !important;
            gap: 0 !important;
        }

        /* Dark compact dropdowns, inline */
        [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
        div[data-testid="stSelectbox"],
        [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
        div[data-testid="stSelectbox"] > div,
        [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
        div[data-baseweb="select"],
        [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
        div[data-baseweb="select"] > div,
        [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
        [role="combobox"] {
            width: 100% !important;
            min-width: 0 !important;
            max-width: 100% !important;
            height: 28px !important;
            min-height: 28px !important;
            max-height: 28px !important;
            box-sizing: border-box !important;
        }

        [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
        div[data-baseweb="select"] > div {
            background: #07101c !important;
            background-color: #07101c !important;
            border: 1px solid #1f3b59 !important;
            border-radius: 7px !important;
            padding: 0 7px 0 9px !important;
            box-shadow: none !important;
        }

        [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
        div[data-baseweb="select"] > div > div,
        [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
        div[data-baseweb="select"] * {
            background-color: transparent !important;
        }

        [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
        div[data-baseweb="select"] span,
        [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
        [role="combobox"],
        [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
        input {
            color: #f5f7fb !important;
            -webkit-text-fill-color: #f5f7fb !important;
            font-size: 7.2px !important;
            font-weight: 850 !important;
        }

        [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
        div[data-baseweb="select"] svg {
            width: 10px !important;
            height: 10px !important;
            fill: #91a3b8 !important;
            color: #91a3b8 !important;
        }

        /* Filter information fills the remaining horizontal row */
        .filter-inline-info {
            height: 28px;
            width: 100%;
            border: 1px solid #1f3b59;
            border-radius: 7px;
            background: linear-gradient(
                145deg,
                rgba(13,24,39,.98),
                rgba(7,16,28,.98)
            );
            padding: 0 10px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            box-sizing: border-box;
            overflow: hidden;
        }

        .filter-inline-left {
            min-width: 0;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .filter-inline-kicker {
            color: #3b9cff;
            font-size: 6.1px;
            font-weight: 900;
            letter-spacing: .05em;
            white-space: nowrap;
        }

        .filter-inline-left strong {
            color: #f5f7fb;
            font-size: 7.2px;
            font-weight: 900;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .filter-inline-right {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 14px;
            color: #91a3b8;
            font-size: 6.2px;
            white-space: nowrap;
        }

        .filter-live-dot {
            color: #39d353;
            font-weight: 850;
        }

        .filter-live-dot::before {
            content: "";
            display: inline-block;
            width: 5px;
            height: 5px;
            margin-right: 5px;
            border-radius: 50%;
            background: #39d353;
            box-shadow: 0 0 6px rgba(57,211,83,.55);
            vertical-align: middle;
        }

        /* Dark dropdown popup */
        div[data-baseweb="popover"],
        div[data-baseweb="menu"],
        ul[role="listbox"],
        div[role="listbox"] {
            background: #07101c !important;
            background-color: #07101c !important;
            border-color: #1f3b59 !important;
            color: #f5f7fb !important;
        }

        li[role="option"],
        div[role="option"] {
            background: #07101c !important;
            color: #f5f7fb !important;
        }

        li[role="option"]:hover,
        div[role="option"]:hover,
        li[role="option"][aria-selected="true"],
        div[role="option"][aria-selected="true"] {
            background: #102033 !important;
            color: #ffffff !important;
        }

        @media (max-height: 900px) {
            .wallboard {
                height: calc(100vh - 80px) !important;
            }

            [data-testid="stHorizontalBlock"]:has(.header-main-card),
            [data-testid="stHorizontalBlock"]:has(.header-main-card)
            [data-testid="stVerticalBlock"],
            .header-main-card {
                height: 62px !important;
                min-height: 62px !important;
            }

            [data-testid="stHorizontalBlock"]:has(.filter-inline-info),
            [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
            [data-testid="stVerticalBlock"],
            .filter-inline-info,
            [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
            div[data-testid="stSelectbox"],
            [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
            div[data-testid="stSelectbox"] > div,
            [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
            div[data-baseweb="select"],
            [data-testid="stHorizontalBlock"]:has(.filter-inline-info)
            div[data-baseweb="select"] > div {
                height: 25px !important;
                min-height: 25px !important;
                max-height: 25px !important;
            }
        }


        /* =====================================================
           HEADER v30 — NO FILTER ROW
           ===================================================== */

        /* No selectboxes are rendered on the wallboard. */
        .filter-inline-info,
        .header-filter-label {
            display: none !important;
        }

        [data-testid="stHorizontalBlock"]:has(.header-main-card) {
            height: 68px !important;
            min-height: 68px !important;
            margin-bottom: 6px !important;
            gap: 7px !important;
            align-items: stretch !important;
        }

        [data-testid="stHorizontalBlock"]:has(.header-main-card)
        [data-testid="stVerticalBlock"] {
            height: 68px !important;
            min-height: 68px !important;
        }

        .header-main-card {
            height: 68px !important;
            min-height: 68px !important;
        }

        .brand-omc,
        .brand-title {
            color: #ffffff !important;
            opacity: 1 !important;
        }

        .brand-subtitle {
            color: #3b9cff !important;
        }

        .head-time {
            color: #ffffff !important;
        }

        @media (max-height: 900px) {
            .wallboard {
                height: calc(100vh - 82px) !important;
            }

            [data-testid="stHorizontalBlock"]:has(.header-main-card),
            [data-testid="stHorizontalBlock"]:has(.header-main-card)
            [data-testid="stVerticalBlock"],
            .header-main-card {
                height: 62px !important;
                min-height: 62px !important;
            }
        }


        /* =====================================================
           HEADER v31 — FINAL POLISH
           ===================================================== */

        [data-testid="stHorizontalBlock"]:has(.header-main-card) {
            height: 70px !important;
            min-height: 70px !important;
            gap: 8px !important;
            margin-bottom: 6px !important;
            align-items: stretch !important;
        }

        [data-testid="stHorizontalBlock"]:has(.header-main-card)
        > [data-testid="stColumn"] {
            min-width: 0 !important;
        }

        [data-testid="stHorizontalBlock"]:has(.header-main-card)
        [data-testid="stVerticalBlock"] {
            height: 70px !important;
            min-height: 70px !important;
            gap: 0 !important;
        }

        .header-main-card {
            height: 70px !important;
            min-height: 70px !important;
            box-sizing: border-box !important;
            border-radius: 10px !important;
            display: flex !important;
            flex-direction: column !important;
            justify-content: center !important;
            overflow: hidden !important;
        }

        /* Brand card */
        .brand.header-main-card {
            flex-direction: row !important;
            align-items: center !important;
            justify-content: flex-start !important;
            gap: 12px !important;
            padding: 9px 14px !important;
        }

        .brand-omc {
            color: #ffffff !important;
            font-size: 26px !important;
            font-weight: 900 !important;
            line-height: 1 !important;
            padding-right: 12px !important;
            border-right: 1px solid #1f3b59 !important;
            letter-spacing: -.03em !important;
        }

        .brand-title {
            color: #ffffff !important;
            font-size: 14.5px !important;
            font-weight: 900 !important;
            line-height: 1.05 !important;
            letter-spacing: -.015em !important;
            white-space: nowrap !important;
        }

        .brand-subtitle {
            color: #3b9cff !important;
            font-size: 6.5px !important;
            font-weight: 850 !important;
            line-height: 1.2 !important;
            margin-top: 6px !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }

        /* Month card */
        .compact-month-card {
            padding: 9px 12px !important;
            align-items: flex-start !important;
        }

        .compact-month-label {
            color: #91a3b8 !important;
            font-size: 6.1px !important;
            font-weight: 850 !important;
            letter-spacing: .065em !important;
            line-height: 1 !important;
            white-space: nowrap !important;
        }

        .compact-month-value {
            color: #ffffff !important;
            font-size: 10.8px !important;
            font-weight: 900 !important;
            line-height: 1 !important;
            margin-top: 6px !important;
            white-space: nowrap !important;
            overflow: visible !important;
        }

        .compact-month-note {
            color: #91a3b8 !important;
            font-size: 5.9px !important;
            line-height: 1 !important;
            margin-top: 6px !important;
            white-space: nowrap !important;
        }

        /* Generic status cards */
        .head-card.header-main-card {
            padding: 9px 12px !important;
            align-items: flex-start !important;
        }

        .head-label {
            color: #91a3b8 !important;
            font-size: 6px !important;
            font-weight: 850 !important;
            letter-spacing: .065em !important;
            line-height: 1 !important;
            white-space: nowrap !important;
        }

        .head-date {
            color: #f5f7fb !important;
            font-size: 6.4px !important;
            font-weight: 800 !important;
            margin-top: 5px !important;
            line-height: 1 !important;
        }

        .head-time {
            color: #ffffff !important;
            font-size: 16.5px !important;
            font-weight: 900 !important;
            line-height: 1 !important;
            margin-top: 5px !important;
            white-space: nowrap !important;
        }

        .head-time span {
            color: #c4cfdb !important;
            font-size: 7px !important;
            font-weight: 800 !important;
        }

        .head-note {
            color: #61758d !important;
            font-size: 5.5px !important;
            line-height: 1 !important;
            margin-top: 6px !important;
            white-space: nowrap !important;
        }

        .live {
            color: #39d353 !important;
            font-size: 10px !important;
            font-weight: 900 !important;
            line-height: 1 !important;
            margin-top: 7px !important;
            white-space: nowrap !important;
        }

        .live::before {
            width: 6px !important;
            height: 6px !important;
            margin-right: 6px !important;
            box-shadow: 0 0 7px rgba(57,211,83,.55) !important;
        }

        /* Keep cards visually aligned */
        .compact-month-card,
        .header-block {
            border: 1px solid #1f3b59 !important;
            background: linear-gradient(
                145deg,
                rgba(13,24,39,.98),
                rgba(7,16,28,.98)
            ) !important;
        }

        @media (max-height: 900px) {
            [data-testid="stHorizontalBlock"]:has(.header-main-card),
            [data-testid="stHorizontalBlock"]:has(.header-main-card)
            [data-testid="stVerticalBlock"],
            .header-main-card {
                height: 64px !important;
                min-height: 64px !important;
            }

            .brand.header-main-card {
                padding-top: 7px !important;
                padding-bottom: 7px !important;
            }

            .brand-omc {
                font-size: 24px !important;
            }

            .brand-title {
                font-size: 13.5px !important;
            }

            .head-time {
                font-size: 15.5px !important;
            }
        }


        /* =====================================================
           HEADER v32 — PURE HTML GRID / TRUE PROPORTIONS
           ===================================================== */

        .omc-top-header {
            width: 100%;
            height: 70px;
            display: grid;
            grid-template-columns:
                minmax(0, 2.25fr)
                minmax(150px, .72fr)
                minmax(220px, 1.15fr)
                minmax(170px, .88fr)
                minmax(180px, .92fr);
            gap: 8px;
            margin-bottom: 6px;
            overflow: hidden;
        }

        .omc-top-card {
            min-width: 0;
            height: 70px;
            box-sizing: border-box;
            border: 1px solid #1f3b59;
            border-radius: 10px;
            background: linear-gradient(
                145deg,
                rgba(13,24,39,.98),
                rgba(7,16,28,.98)
            );
            overflow: hidden;
        }

        .omc-top-brand {
            display: flex;
            align-items: center;
            padding: 10px 14px;
            gap: 13px;
        }

        .omc-top-brand .brand-logo-wrap,
        .omc-top-brand .brand-omc {
            display: flex;
            align-items: center;
            justify-content: center;
            min-width: 64px;
            padding-right: 13px !important;
            border-right: 1px solid #1f3b59 !important;
            flex: 0 0 auto;
        }

        .omc-top-brand .brand-logo {
            display: block;
            height: 40px;
            width: auto;
            object-fit: contain;
            filter: drop-shadow(0 1px 1px rgba(0,0,0,.25));
        }

        .omc-top-brand .brand-omc {
            color: #ffffff !important;
            font-size: 22px !important;
            font-weight: 900 !important;
            line-height: 1 !important;
        }

        .brand-copy {
            min-width: 0;
        }

        .omc-top-brand .brand-title {
            color: #ffffff !important;
            font-size: 15px !important;
            font-weight: 900 !important;
            line-height: 1.05 !important;
            white-space: nowrap !important;
        }

        .omc-top-brand .brand-subtitle {
            color: #3b9cff !important;
            font-size: 6.8px !important;
            font-weight: 850 !important;
            margin-top: 6px !important;
            line-height: 1.1 !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }

        .omc-top-month,
        .omc-top-time,
        .omc-top-status {
            padding: 10px 12px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: flex-start;
        }

        .month-main {
            color: #ffffff;
            font-size: 11px;
            font-weight: 900;
            line-height: 1;
            margin-top: 6px;
            white-space: nowrap;
        }

        .omc-top-card .head-label {
            color: #91a3b8 !important;
            font-size: 6px !important;
            font-weight: 850 !important;
            letter-spacing: .06em !important;
            line-height: 1 !important;
            white-space: nowrap !important;
        }

        .omc-top-card .head-date {
            color: #f5f7fb !important;
            font-size: 6.4px !important;
            font-weight: 800 !important;
            line-height: 1 !important;
            margin-top: 5px !important;
            white-space: nowrap !important;
        }

        .omc-top-card .head-time {
            color: #ffffff !important;
            font-size: 16.5px !important;
            font-weight: 900 !important;
            line-height: 1 !important;
            margin-top: 5px !important;
            white-space: nowrap !important;
        }

        .omc-top-card .head-time span {
            color: #c4cfdb !important;
            font-size: 7px !important;
            font-weight: 800 !important;
            margin-left: 3px;
        }

        .omc-top-card .head-note {
            color: #61758d !important;
            font-size: 5.6px !important;
            line-height: 1 !important;
            margin-top: 6px !important;
            white-space: nowrap !important;
        }

        .omc-top-card .live {
            color: #39d353 !important;
            font-size: 10px !important;
            font-weight: 900 !important;
            line-height: 1 !important;
            margin-top: 7px !important;
            white-space: nowrap !important;
        }

        .omc-top-card .live::before {
            content: "";
            display: inline-block;
            width: 6px;
            height: 6px;
            margin-right: 6px;
            border-radius: 50%;
            background: #39d353;
            box-shadow: 0 0 7px rgba(57,211,83,.55);
            vertical-align: middle;
        }

        @media (max-width: 1600px) {
            .omc-top-header {
                grid-template-columns:
                    minmax(0, 2fr)
                    minmax(130px, .68fr)
                    minmax(190px, 1.05fr)
                    minmax(150px, .82fr)
                    minmax(155px, .86fr);
            }

            .omc-top-brand .brand-title {
                font-size: 14px !important;
            }
        }

        @media (max-height: 900px) {
            .omc-top-header,
            .omc-top-card {
                height: 64px;
            }

            .omc-top-brand,
            .omc-top-month,
            .omc-top-time,
            .omc-top-status {
                padding-top: 8px;
                padding-bottom: 8px;
            }

            .omc-top-brand .brand-omc {
                font-size: 24px !important;
            }

            .omc-top-card .head-time {
                font-size: 15px !important;
            }
        }


        /* =====================================================
           HEADER v34 — SINGLE HTML SHELL / NO OVERLAP
           ===================================================== */

        .omc-shell {
            width: calc(100vw - 24px);
            height: calc(100vh - 20px);
            display: grid;
            grid-template-rows: 66px minmax(0, 1fr);
            gap: 8px;
            overflow: hidden;
            box-sizing: border-box;
        }

        .omc-shell > .omc-top-header {
            width: 100% !important;
            height: 66px !important;
            min-height: 66px !important;
            margin: 0 !important;
            display: grid !important;
            grid-template-columns:
                minmax(0, 2.30fr)
                minmax(155px, .78fr)
                minmax(225px, 1.20fr)
                minmax(175px, .90fr)
                minmax(185px, .94fr) !important;
            gap: 8px !important;
            overflow: hidden !important;
            box-sizing: border-box !important;
        }

        .omc-shell .omc-top-card {
            height: 66px !important;
            min-height: 66px !important;
            max-height: 66px !important;
            box-sizing: border-box !important;
            margin: 0 !important;
        }

        .omc-shell > .wallboard {
            width: 100% !important;
            height: 100% !important;
            min-height: 0 !important;
            max-height: none !important;
            overflow: hidden !important;
        }

        .omc-shell .omc-top-brand {
            padding: 8px 14px !important;
        }

        .omc-shell .omc-top-month,
        .omc-shell .omc-top-time,
        .omc-shell .omc-top-status {
            padding: 8px 12px !important;
        }

        .omc-shell .brand-omc {
            font-size: 26px !important;
        }

        .omc-shell .brand-title {
            font-size: 14.5px !important;
        }

        .omc-shell .month-main {
            font-size: 10.8px !important;
        }

        .omc-shell .head-time {
            font-size: 16px !important;
        }

        @media (max-width: 1600px) {
            .omc-shell > .omc-top-header {
                grid-template-columns:
                    minmax(0, 2.05fr)
                    minmax(140px, .72fr)
                    minmax(200px, 1.08fr)
                    minmax(155px, .84fr)
                    minmax(165px, .88fr) !important;
            }
        }

        @media (max-height: 900px) {
            .omc-shell {
                height: calc(100vh - 16px);
                grid-template-rows: 60px minmax(0, 1fr);
                gap: 7px;
            }

            .omc-shell > .omc-top-header,
            .omc-shell .omc-top-card {
                height: 60px !important;
                min-height: 60px !important;
                max-height: 60px !important;
            }
        }


        /* =====================================================
           MANAGEMENT ATTENTION v37 — LARGER TYPOGRAPHY
           ===================================================== */

        .attention-title {
            font-size: 10.5px !important;
            font-weight: 900 !important;
            line-height: 1.15 !important;
            letter-spacing: .015em !important;
        }

        .attention-item {
            padding: 9px 12px !important;
        }

        .attention-item strong {
            font-size: 9.5px !important;
            font-weight: 900 !important;
            line-height: 1.1 !important;
        }

        .attention-item span {
            font-size: 8px !important;
            line-height: 1.25 !important;
            margin-top: 4px !important;
        }

        @media (max-height: 900px) {
            .attention-title {
                font-size: 9.5px !important;
            }

            .attention-item strong {
                font-size: 8.8px !important;
            }

            .attention-item span {
                font-size: 7.4px !important;
            }
        }


        /* =====================================================
           REFRESH v38 — NO FADE / REALTIME WALLBOARD
           Streamlit marks old fragment nodes as data-stale=true
           while rerunning. By default those nodes become faded.
           Keep them fully visible until new HTML replaces them.
           ===================================================== */

        [data-stale="true"],
        [data-testid="stElementContainer"][data-stale="true"],
        [data-testid="stMarkdownContainer"][data-stale="true"],
        [data-testid="stVerticalBlock"][data-stale="true"],
        [data-testid="stHorizontalBlock"][data-stale="true"] {
            opacity: 1 !important;
            filter: none !important;
            transition: none !important;
        }

        /* Prevent any inherited dimming/fade during fragment refresh. */
        [data-stale="true"] *,
        [data-testid="stElementContainer"][data-stale="true"] * {
            opacity: 1 !important;
            filter: none !important;
            transition: none !important;
        }

        /* Keep the wallboard visually stable during DOM replacement. */
        .omc-shell,
        .wallboard,
        .omc-top-header,
        .panel,
        .kpi-strip,
        .attention-bar {
            opacity: 1 !important;
            filter: none !important;
            transition: none !important;
        }

        /* Small LIVE indicator pulse gives a realtime cue without
           fading the whole dashboard. */
        .omc-top-card .live::before {
            animation: omc-live-pulse 1.8s ease-in-out infinite !important;
        }

        @keyframes omc-live-pulse {
            0%, 100% {
                opacity: .55;
                transform: scale(.82);
                box-shadow: 0 0 4px rgba(57,211,83,.35);
            }
            50% {
                opacity: 1;
                transform: scale(1);
                box-shadow: 0 0 9px rgba(57,211,83,.78);
            }
        }

        </style>
        """,
        unsafe_allow_html=True,
    )


# ==========================================================
# WALLBOARD DATA + SINGLE-PASS HTML
# ==========================================================


@st.fragment(run_every=REFRESH_SECONDS)
def _render_wallboard() -> None:
    now = datetime.now()
    today = now.date()
    month_start = today.replace(day=1)
    recurring_start = today - timedelta(days=29)

    try:
        today_reliability = _load_reliability(
            today,
            today,
        )
        today_operations = _load_operations(
            today,
            today,
        )
        month_operations = _load_operations(
            month_start,
            today,
        )
        month_reliability = _load_reliability(
            month_start,
            today,
        )
        recurring_rows = _load_reliability(
            recurring_start,
            today,
        )
        exposure_rows = _load_exposure(
            today,
            today,
        )
        month_exposure_rows = _load_exposure(
            month_start,
            today,
        )
        recent_gangguan = _load_recent_gangguan(
            month_start,
            today,
            500,
        )
    except Exception as exc:
        st.error(
            f"OMC Dashboard Gangguan tidak dapat dimuat: {exc}"
        )
        return

    # ------------------------------------------------------
    # ------------------------------------------------------
    # ACCESS SCOPE
    # ------------------------------------------------------
    # All loaded OMC datasets are already constrained by the
    # authenticated user's backend access scope.
    # No additional ULTG / GI UI filter is required.

    month_label = (
        f"{_month_name_id(today.month)} "
        f"{today.year}"
    )

    period_label = (
        f"01–{today.day:02d} "
        f"{_month_name_id(today.month)[:3]} "
        f"{today.year}"
    )

    scope_label = "SESUAI SCOPE AKSES LOGIN"

    rel_df = pd.DataFrame(today_reliability)
    ops_df = pd.DataFrame(today_operations)
    month_df = pd.DataFrame(month_reliability)
    recurring_df = pd.DataFrame(recurring_rows)

    # ------------------------------------------------------
    # TODAY KPI
    # ------------------------------------------------------

    total_today = len(rel_df)
    month_total = len(month_df)
    month_daily_average = (
        month_total / max(today.day, 1)
    )

    active_rows: list[dict[str, Any]] = []

    for row in today_operations:
        status = _as_text(
            row.get("record_status"),
            "",
        ).upper()

        if status == "ONGOING":
            active_rows.append(row)

    active_rows.sort(
        key=lambda row: _safe_float(
            row.get("aging_minutes")
        ),
        reverse=True,
    )

    active_count = len(active_rows)

    recovered_count = 0

    if (
        not ops_df.empty
        and "record_status" in ops_df.columns
    ):
        recovered_count = int(
            ops_df["record_status"]
            .fillna("")
            .astype(str)
            .str.upper()
            .eq("RECOVERED")
            .sum()
        )

    trip_today = 0

    if not ops_df.empty:
        pmt_column: str | None = None

        for candidate in [
            "pmt_status_code",
            "pmt_status",
            "status_pmt",
        ]:
            if candidate in ops_df.columns:
                pmt_column = candidate
                break

        if pmt_column is not None:
            trip_today = int(
                ops_df[pmt_column]
                .fillna("")
                .astype(str)
                .str.upper()
                .str.contains("TRIP")
                .sum()
            )

    if trip_today == 0 and total_today > 0:
        trip_today = total_today

    month_trip_total = 0
    month_recovered_total = 0
    month_open_total = 0

    if month_operations:
        month_ops_df = pd.DataFrame(month_operations)

        if "record_status" in month_ops_df.columns:
            month_status = (
                month_ops_df["record_status"]
                .fillna("")
                .astype(str)
                .str.upper()
            )
            month_recovered_total = int(
                month_status.eq("RECOVERED").sum()
            )
            month_open_total = int(
                month_status.eq("ONGOING").sum()
            )

        month_pmt_column: str | None = None

        for candidate in [
            "pmt_status_code",
            "pmt_status",
            "status_pmt",
        ]:
            if candidate in month_ops_df.columns:
                month_pmt_column = candidate
                break

        if month_pmt_column is not None:
            month_trip_total = int(
                month_ops_df[month_pmt_column]
                .fillna("")
                .astype(str)
                .str.upper()
                .str.contains("TRIP")
                .sum()
            )

    if month_trip_total == 0 and month_total > 0:
        month_trip_total = month_total

    recovery_column: str | None = None

    for candidate in [
        "customer_outage_duration_min",
        "outage_duration_min",
        "recovery_duration_min",
    ]:
        if candidate in rel_df.columns:
            recovery_column = candidate
            break

    recovery_series = pd.Series(
        dtype="float64"
    )

    if recovery_column is not None:
        recovery_series = pd.to_numeric(
            rel_df[recovery_column],
            errors="coerce",
        ).dropna()

    avg_recovery = (
        float(recovery_series.mean())
        if not recovery_series.empty
        else 0.0
    )

    month_recovery_series = pd.Series(dtype="float64")

    if (
        recovery_column is not None
        and not month_df.empty
        and recovery_column in month_df.columns
    ):
        month_recovery_series = pd.to_numeric(
            month_df[recovery_column],
            errors="coerce",
        ).dropna()

    month_avg_recovery = (
        float(month_recovery_series.mean())
        if not month_recovery_series.empty
        else 0.0
    )

    ens_today = 0.0

    if (
        not rel_df.empty
        and "ens_kwh" in rel_df.columns
    ):
        ens_today = float(
            pd.to_numeric(
                rel_df["ens_kwh"],
                errors="coerce",
            )
            .fillna(0)
            .sum()
        )

    ens_month = 0.0

    if (
        not month_df.empty
        and "ens_kwh" in month_df.columns
    ):
        ens_month = float(
            pd.to_numeric(
                month_df["ens_kwh"],
                errors="coerce",
            )
            .fillna(0)
            .sum()
        )

    # ------------------------------------------------------
    # LATEST INCIDENT
    # ------------------------------------------------------

    latest_candidates = (
        recent_gangguan
        if recent_gangguan
        else (
            today_operations
            if today_operations
            else month_operations
        )
    )

    latest_candidates = sorted(
        latest_candidates,
        key=lambda row: (
            _event_datetime(row)
            or datetime.min
        ),
        reverse=True,
    )

    incident = (
        latest_candidates[0]
        if latest_candidates
        else {}
    )

    incident_is_active = (
        _as_text(
            incident.get("record_status"),
            "",
        ).upper()
        == "ONGOING"
    )

    incident_ultg = _first_value(
        incident,
        "ultg_name",
        default="-",
    )

    incident_gi = _first_value(
        incident,
        "gi_name",
        "substation_name",
        default="BELUM ADA GANGGUAN",
    )

    incident_bay = _first_value(
        incident,
        "bay_name",
        default="-",
    )

    incident_wilayah_penyaluran = _first_value(
        incident,
        "wilayah_penyaluran",
        default="-",
    )

    incident_ulp_code = _first_value(
        incident,
        "ulp_code",
        default="-",
    )

    incident_up3_code = _first_value(
        incident,
        "up3_code",
        default="-",
    )

    impacted_area = " • ".join(
        part
        for part in [
            incident_wilayah_penyaluran,
            (
                f"{incident_ulp_code} / {incident_up3_code}"
                if (
                    incident_ulp_code != "-"
                    or incident_up3_code != "-"
                )
                else "-"
            ),
        ]
        if part and part != "-"
    ) or "-"

    incident_feeder = _first_value(
        incident,
        "penyulang_name",
        "feeder_name",
        default="Belum ada kejadian bulan ini",
    )

    incident_penyulang_id = _first_value(
        incident,
        "penyulang_id",
        default="",
    )

    latest_feeder_today_count = 0
    latest_feeder_month_count = 0

    if incident:
        for row in recent_gangguan:
            row_penyulang_id = _first_value(
                row,
                "penyulang_id",
                default="",
            )
            row_feeder_name = _first_value(
                row,
                "penyulang_name",
                "feeder_name",
                default="",
            )

            same_feeder = (
                (
                    incident_penyulang_id
                    and row_penyulang_id
                    and row_penyulang_id
                    == incident_penyulang_id
                )
                or (
                    not incident_penyulang_id
                    and row_feeder_name
                    == incident_feeder
                )
            )

            if not same_feeder:
                continue

            latest_feeder_month_count += 1

            row_dt = _event_datetime(row)

            if (
                row_dt is not None
                and row_dt.date() == today
            ):
                latest_feeder_today_count += 1

    incident_relay = _relay_label(incident)
    incident_phase = _phase_label(incident)
    incident_supply = _supply_label(incident)

    incident_pmt_counter_raw = (
        incident.get("pmt_counter_after")
        if incident
        else None
    )

    if incident_pmt_counter_raw is None:
        incident_pmt_counter = "-"
    else:
        try:
            incident_pmt_counter = (
                f"{int(incident_pmt_counter_raw):,}"
                .replace(",", ".")
            )
        except (
            TypeError,
            ValueError,
        ):
            incident_pmt_counter = _as_text(
                incident_pmt_counter_raw,
                "-",
            )

    incident_aging = _first_numeric(
        incident,
        "aging_minutes",
    )

    fault_source = incident

    if incident:
        reliability_source = (
            today_reliability
            if today_reliability
            else month_reliability
        )

        for row in reliability_source:
            if (
                _first_value(
                    row,
                    "penyulang_name",
                )
                == incident_feeder
            ):
                fault_source = row
                break

    phase_values = {
        "R": _first_numeric(
            fault_source,
            "fault_current_r_a",
        ),
        "S": _first_numeric(
            fault_source,
            "fault_current_s_a",
        ),
        "T": _first_numeric(
            fault_source,
            "fault_current_t_a",
        ),
        "N": _first_numeric(
            fault_source,
            "fault_current_n_a",
        ),
    }

    incident_fault = max(
        phase_values.values(),
        default=0.0,
    )

    incident_transformer = "-"
    fault_multiple = 0.0

    if incident and exposure_rows:
        top_exposure = max(
            exposure_rows,
            key=lambda row: _safe_float(
                row.get("max_fault_multiple")
            ),
        )

        incident_transformer = _first_value(
            top_exposure,
            "transformer_bay_name",
            "techidentno",
            default="-",
        )

        fault_multiple = _safe_float(
            top_exposure.get(
                "max_fault_multiple"
            )
        )

    # ------------------------------------------------------
    # TREND
    # ------------------------------------------------------

    hourly_values = [0] * 24

    for row in today_reliability:
        event_dt = _event_datetime(row)

        if event_dt is not None:
            hourly_values[event_dt.hour] += 1

    month_daily_values = [0] * today.day

    for row in month_reliability:
        event_dt = _event_datetime(row)

        if event_dt is not None:
            day_index = event_dt.day - 1

            if 0 <= day_index < len(month_daily_values):
                month_daily_values[day_index] += 1

    month_trend_svg = _month_trend_svg(
        month_daily_values
    )

    month_daily_ens = [0.0] * today.day

    for row in month_reliability:
        event_dt = _event_datetime(row)

        if event_dt is None:
            continue

        day_index = event_dt.day - 1

        if 0 <= day_index < len(month_daily_ens):
            month_daily_ens[day_index] += _safe_float(
                row.get("ens_kwh")
            )

    ens_trend_svg = _ens_daily_svg(
        month_daily_ens
    )

    relay_daily_rows: list[dict[str, int]] = [
        {
            "OCR_INST": 0,
            "OCR_TD": 0,
            "GFR_INST": 0,
            "GFR_TD": 0,
            "SYSTEM": 0,
        }
        for _ in range(today.day)
    ]

    for row in recent_gangguan:
        event_dt = _event_datetime(row)

        if event_dt is None:
            continue

        day_index = event_dt.day - 1

        if not (
            0 <= day_index < len(relay_daily_rows)
        ):
            continue

        relay_text = _relay_label(row).upper()

        for protection_code in (
            "OCR_INST",
            "OCR_TD",
            "GFR_INST",
            "GFR_TD",
        ):
            display_code = protection_code.replace("_", " ")

            if (
                protection_code in relay_text
                or display_code in relay_text
            ):
                relay_daily_rows[day_index][
                    protection_code
                ] += 1

        if any(
            code in relay_text
            for code in (
                "OLS",
                "UFR",
                "UVLS",
            )
        ):
            relay_daily_rows[day_index][
                "SYSTEM"
            ] += 1

    relay_trend_svg = _relay_stacked_svg(
        relay_daily_rows
    )

    peak_ens_value = max(
        month_daily_ens,
        default=0.0,
    )

    if peak_ens_value > 0:
        peak_ens_index = month_daily_ens.index(
            peak_ens_value
        )
        peak_ens_label = (
            f"{peak_ens_index + 1:02d} "
            f"{today.strftime('%b').upper()}"
        )
    else:
        peak_ens_label = "-"

    disturbed_days = sum(
        1
        for value in month_daily_values
        if value > 0
    )
    normal_days = max(today.day - disturbed_days, 0)

    normal_day_percent = (
        normal_days / max(today.day, 1) * 100.0
    )

    peak_day_value = max(
        month_daily_values,
        default=0,
    )

    if peak_day_value > 0:
        peak_day_index = month_daily_values.index(
            peak_day_value
        )
        peak_day_label = (
            f"{peak_day_index + 1:02d} "
            f"{today.strftime('%b').upper()}"
        )
    else:
        peak_day_label = "-"

    last_event_text = "-"

    if recent_gangguan:
        last_row = recent_gangguan[0]
        last_dt = _event_datetime(last_row)

        if last_dt is not None:
            last_event_text = (
                f"{last_dt.strftime('%d %b %H:%M')} • "
                f"{_first_value(last_row, 'penyulang_name', default='-')}"
            )

    # ------------------------------------------------------
    # RECOVERY
    # ------------------------------------------------------

    recovery_buckets = [
        (
            "≤ 5 menit",
            int(
                (
                    recovery_series <= 5
                ).sum()
            ),
        ),
        (
            "6–10 menit",
            int(
                (
                    (recovery_series > 5)
                    & (recovery_series <= 10)
                ).sum()
            ),
        ),
        (
            "11–30 menit",
            int(
                (
                    (recovery_series > 10)
                    & (recovery_series <= 30)
                ).sum()
            ),
        ),
        (
            "31–60 menit",
            int(
                (
                    (recovery_series > 30)
                    & (recovery_series <= 60)
                ).sum()
            ),
        ),
        (
            "> 60 menit",
            int(
                (
                    recovery_series > 60
                ).sum()
            ),
        ),
    ]

    recovery_html = _recovery_bars(
        recovery_buckets
    )

    # ------------------------------------------------------
    # RECURRING
    # ------------------------------------------------------

    recurring_values: list[
        tuple[str, int]
    ] = []

    if (
        not recurring_df.empty
        and "penyulang_name"
        in recurring_df.columns
    ):
        counts = (
            recurring_df[
                "penyulang_name"
            ]
            .fillna("-")
            .value_counts()
            .head(5)
        )

        recurring_values = [
            (
                str(label),
                int(value),
            )
            for label, value
            in counts.items()
        ]

    if not recurring_values:
        recurring_values = [
            ("Belum ada recurring", 0)
        ]

    recurring_html = _recurring_bars(
        recurring_values
    )

    transformer_frequency_html = _transformer_frequency_rows(
        month_exposure_rows
    )

    top_recurring = (
        recurring_values[0][0]
        if recurring_values
        else "-"
    )

    top_recurring_count = (
        recurring_values[0][1]
        if recurring_values
        else 0
    )

    relay_counter: dict[str, int] = {}
    area_counter: dict[str, int] = {}

    for row in recent_gangguan:
        relay_name = _relay_label(row)

        if relay_name and relay_name != "-":
            relay_counter[relay_name] = (
                relay_counter.get(relay_name, 0) + 1
            )

        wilayah = _first_value(
            row,
            "wilayah_penyaluran",
            default="-",
        )

        if wilayah != "-":
            area_counter[wilayah] = (
                area_counter.get(wilayah, 0) + 1
            )

    dominant_relay = (
        max(
            relay_counter.items(),
            key=lambda item: item[1],
        )[0]
        if relay_counter
        else "-"
    )

    dominant_relay_count = (
        relay_counter.get(dominant_relay, 0)
        if dominant_relay != "-"
        else 0
    )

    dominant_area = (
        max(
            area_counter.items(),
            key=lambda item: item[1],
        )[0]
        if area_counter
        else "-"
    )

    dominant_area_count = (
        area_counter.get(dominant_area, 0)
        if dominant_area != "-"
        else 0
    )

    # ------------------------------------------------------
    # PROTECTION KPI — TODAY / MONTH
    # ------------------------------------------------------

    protection_codes = {
        "OCR_INST": 0,
        "OCR_TD": 0,
        "GFR_INST": 0,
        "GFR_TD": 0,
        "SYSTEM": 0,
    }

    protection_codes_today = {
        "OCR_INST": 0,
        "OCR_TD": 0,
        "GFR_INST": 0,
        "GFR_TD": 0,
        "SYSTEM": 0,
    }

    for row in recent_gangguan:
        relay_text = _relay_label(row).upper()

        event_dt = _event_datetime(row)
        is_today_event = (
            event_dt is not None
            and event_dt.date() == today
        )

        for protection_code in (
            "OCR_INST",
            "OCR_TD",
            "GFR_INST",
            "GFR_TD",
        ):
            display_code = protection_code.replace("_", " ")

            if (
                protection_code in relay_text
                or display_code in relay_text
            ):
                protection_codes[protection_code] += 1

                if is_today_event:
                    protection_codes_today[protection_code] += 1

        is_system_event = any(
            code in relay_text
            for code in (
                "OLS",
                "UFR",
                "UVLS",
            )
        )

        if is_system_event:
            protection_codes["SYSTEM"] += 1

            if is_today_event:
                protection_codes_today["SYSTEM"] += 1

    # ------------------------------------------------------
    # RECENT INCIDENT HISTORY
    # ------------------------------------------------------

    recent_events = sorted(
        recent_gangguan,
        key=lambda row: (
            _event_datetime(row)
            or datetime.min
        ),
        reverse=True,
    )[:10]

    recent_history_parts: list[str] = []

    for row in recent_events:
        status_text = _as_text(
            row.get("record_status"),
            "",
        ).upper()

        is_open = status_text == "ONGOING"

        duration_value = _first_numeric(
            row,
            "customer_outage_duration_min",
            "outage_duration_min",
            "pmt_condition_duration_min",
            "aging_minutes",
        )

        history_wilayah = _first_value(
            row,
            "wilayah_penyaluran",
            default="-",
        )
        history_ulp = _first_value(
            row,
            "ulp_code",
            default="-",
        )
        history_up3 = _first_value(
            row,
            "up3_code",
            default="-",
        )

        history_area = " • ".join(
            part
            for part in [
                history_wilayah,
                (
                    f"{history_ulp} / {history_up3}"
                    if (
                        history_ulp != "-"
                        or history_up3 != "-"
                    )
                    else "-"
                ),
            ]
            if part and part != "-"
        ) or "-"

        recent_history_parts.append(
            (
                '<div class="latest-history-row">'
                f'<div class="latest-history-time">{escape(_event_clock(row))}</div>'
                f'<div class="latest-history-feeder">{escape(_short(_first_value(row, "penyulang_name", "feeder_name", default="-"), 28))}</div>'
                f'<div class="latest-history-relay">{escape(_short(_relay_label(row), 22))}</div>'
                f'<div class="latest-history-area">{escape(history_area)}</div>'
                f'<div class="latest-history-status {"red" if is_open else "green"}">'
                f'{"BELUM PULIH" if is_open else "SUDAH PULIH"}'
                '</div>'
                f'<div class="latest-history-duration">{duration_value:,.0f} min</div>'
                '</div>'
            )
        )

    recent_history_html = "".join(recent_history_parts)

    if not recent_history_html:
        recent_history_html = (
            '<div class="latest-history-row">'
            '<div class="latest-history-time">-</div>'
            '<div class="latest-history-feeder">Belum ada gangguan bulan ini</div>'
            '<div class="latest-history-relay">-</div>'
            '<div class="latest-history-area">-</div>'
            '<div class="latest-history-status green">NORMAL</div>'
            '<div class="latest-history-duration">-</div>'
            '</div>'
        )

    # ------------------------------------------------------
    # DATA QUALITY ATTENTION
    # ------------------------------------------------------

    no_fault_count = 0

    if not rel_df.empty:
        fault_columns = [
            column
            for column in [
                "fault_current_r_a",
                "fault_current_s_a",
                "fault_current_t_a",
                "fault_current_n_a",
            ]
            if column in rel_df.columns
        ]

        if fault_columns:
            matrix = (
                rel_df[fault_columns]
                .apply(
                    pd.to_numeric,
                    errors="coerce",
                )
                .fillna(0)
            )

            no_fault_count = int(
                matrix.max(
                    axis=1
                ).eq(0).sum()
            )

    # ------------------------------------------------------
    # STATUS / LABELS
    # ------------------------------------------------------

    if not incident:
        incident_supply = "-"

    supply_class = (
        "green"
        if incident_supply in {"NORMAL", "RECOVERED"}
        else "red"
        if incident
        else ""
    )

    incident_title_class = (
        "red"
        if incident_is_active
        else "green"
        if incident
        else ""
    )

    # ------------------------------------------------------
    # BUILD SINGLE HTML PAGE
    # ------------------------------------------------------

    kpi_html = "".join(
        [
            (
                '<div class="kpi">'
                '<div class="kpi-label">Gangguan</div>'
                '<div class="kpi-dual">'
                '<div class="kpi-dual-item">'
                '<div class="kpi-dual-label">Hari Ini</div>'
                f'<div class="kpi-dual-value blue">{total_today}</div>'
                '</div>'
                '<div class="kpi-dual-item">'
                '<div class="kpi-dual-label">Bulan Ini</div>'
                f'<div class="kpi-dual-value amber">{month_total}</div>'
                '</div>'
                '</div>'
                f'<div class="kpi-note">Avg {month_daily_average:.1f} kejadian / hari</div>'
                '</div>'
            ),
            (
                '<div class="kpi">'
                '<div class="kpi-label">Sudah Pulih</div>'
                '<div class="kpi-dual">'
                '<div class="kpi-dual-item">'
                '<div class="kpi-dual-label">Hari Ini</div>'
                f'<div class="kpi-dual-value green">{recovered_count}</div>'
                '</div>'
                '<div class="kpi-dual-item">'
                '<div class="kpi-dual-label">Bulan Ini</div>'
                f'<div class="kpi-dual-value green">{month_recovered_total}</div>'
                '</div>'
                '</div>'
                '<div class="kpi-note">Kejadian berhasil dipulihkan</div>'
                '</div>'
            ),
            (
                '<div class="kpi">'
                '<div class="kpi-label">OCR INST</div>'
                '<div class="kpi-dual">'
                '<div class="kpi-dual-item">'
                '<div class="kpi-dual-label">Hari Ini</div>'
                f'<div class="kpi-dual-value amber">{protection_codes_today["OCR_INST"]}</div>'
                '</div>'
                '<div class="kpi-dual-item">'
                '<div class="kpi-dual-label">Bulan Ini</div>'
                f'<div class="kpi-dual-value amber">{protection_codes["OCR_INST"]}</div>'
                '</div>'
                '</div>'
                '<div class="kpi-note">Instantaneous Overcurrent</div>'
                '</div>'
            ),
            (
                '<div class="kpi">'
                '<div class="kpi-label">OCR TD</div>'
                '<div class="kpi-dual">'
                '<div class="kpi-dual-item">'
                '<div class="kpi-dual-label">Hari Ini</div>'
                f'<div class="kpi-dual-value amber">{protection_codes_today["OCR_TD"]}</div>'
                '</div>'
                '<div class="kpi-dual-item">'
                '<div class="kpi-dual-label">Bulan Ini</div>'
                f'<div class="kpi-dual-value amber">{protection_codes["OCR_TD"]}</div>'
                '</div>'
                '</div>'
                '<div class="kpi-note">Time Delay Overcurrent</div>'
                '</div>'
            ),
            (
                '<div class="kpi">'
                '<div class="kpi-label">GFR INST</div>'
                '<div class="kpi-dual">'
                '<div class="kpi-dual-item">'
                '<div class="kpi-dual-label">Hari Ini</div>'
                f'<div class="kpi-dual-value red">{protection_codes_today["GFR_INST"]}</div>'
                '</div>'
                '<div class="kpi-dual-item">'
                '<div class="kpi-dual-label">Bulan Ini</div>'
                f'<div class="kpi-dual-value red">{protection_codes["GFR_INST"]}</div>'
                '</div>'
                '</div>'
                '<div class="kpi-note">Instantaneous Ground Fault</div>'
                '</div>'
            ),
            (
                '<div class="kpi">'
                '<div class="kpi-label">GFR TD</div>'
                '<div class="kpi-dual">'
                '<div class="kpi-dual-item">'
                '<div class="kpi-dual-label">Hari Ini</div>'
                f'<div class="kpi-dual-value red">{protection_codes_today["GFR_TD"]}</div>'
                '</div>'
                '<div class="kpi-dual-item">'
                '<div class="kpi-dual-label">Bulan Ini</div>'
                f'<div class="kpi-dual-value red">{protection_codes["GFR_TD"]}</div>'
                '</div>'
                '</div>'
                '<div class="kpi-note">Time Delay Ground Fault</div>'
                '</div>'
            ),
            (
                '<div class="kpi">'
                '<div class="kpi-label">Gangguan Sistem</div>'
                '<div class="kpi-dual">'
                '<div class="kpi-dual-item">'
                '<div class="kpi-dual-label">Hari Ini</div>'
                f'<div class="kpi-dual-value purple">{protection_codes_today["SYSTEM"]}</div>'
                '</div>'
                '<div class="kpi-dual-item">'
                '<div class="kpi-dual-label">Bulan Ini</div>'
                f'<div class="kpi-dual-value purple">{protection_codes["SYSTEM"]}</div>'
                '</div>'
                '</div>'
                '<div class="kpi-note">OLS / UFR / UVLS</div>'
                '</div>'
            ),
        ]
    )


    # Rotating primary chart:
    # 0 = Relay, 1 = Frequency, 2 = ENS.
    # It changes automatically with wallboard refresh time.
    primary_chart_index = (
        int(now.timestamp()) // REFRESH_SECONDS
    ) % 3

    frequency_chart_html = f"""
    <div class="trend-metric-card">
      <div class="trend-metric-head">
        <div>
          <div class="trend-metric-title">
            Frekuensi Gangguan Harian
          </div>
          <div class="trend-metric-subtitle">
            Distribusi jumlah gangguan per hari
          </div>
        </div>
      </div>
      <div>{month_trend_svg}</div>
    </div>
    """

    ens_chart_html = f"""
    <div class="trend-metric-card">
      <div class="trend-metric-head">
        <div>
          <div class="trend-metric-title">
            ENS Harian
          </div>
          <div class="trend-metric-subtitle">
            Distribusi Energy Not Supplied per hari
          </div>
        </div>
      </div>
      <div>{ens_trend_svg}</div>
    </div>
    """

    relay_chart_html = f"""
    <div class="trend-metric-card relay-chart-card">
      <div class="trend-metric-head">
        <div>
          <div class="trend-metric-title">
            Trend Relay Bekerja
          </div>
          <div class="trend-metric-subtitle">
            Distribusi relay bekerja per hari
          </div>
          <div class="relay-legend">
            <span class="relay-legend-item">
              <i class="relay-legend-dot ocr-inst"></i>OCR INST
            </span>
            <span class="relay-legend-item">
              <i class="relay-legend-dot ocr-td"></i>OCR TD
            </span>
            <span class="relay-legend-item">
              <i class="relay-legend-dot gfr-inst"></i>GFR INST
            </span>
            <span class="relay-legend-item">
              <i class="relay-legend-dot gfr-td"></i>GFR TD
            </span>
            <span class="relay-legend-item">
              <i class="relay-legend-dot system"></i>Sistem
            </span>
          </div>
        </div>
      </div>
      <div>{relay_trend_svg}</div>
    </div>
    """

    chart_items = [
        relay_chart_html,
        frequency_chart_html,
        ens_chart_html,
    ]

    primary_chart_html = chart_items[
        primary_chart_index
    ]

    secondary_chart_html = [
        chart
        for index, chart in enumerate(chart_items)
        if index != primary_chart_index
    ]

    fault_rows_html = _fault_phase_rows(
        phase_values
    )

    attention_one_title = (
        _short(
            incident_feeder,
            18,
        )
        if incident
        else "SYSTEM NORMAL"
    )

    attention_one_text = (
        (
            f"Aktif {incident_aging:,.0f} menit • Belum pulih"
        )
        if incident_is_active
        else (
            "Gangguan terbaru • Sudah pulih"
            if incident
            else "Tidak ada gangguan aktif"
        )
    )

    # ------------------------------------------------------
    # SINGLE COMPACT HEADER — FILTERS + STATUS
    # ------------------------------------------------------

    # ------------------------------------------------------
    # SINGLE PROFESSIONAL HEADER — PURE HTML GRID
    # ------------------------------------------------------

    pln_logo_uri = _load_pln_logo_data_uri()

    brand_logo_html = (
        f'<div class="brand-logo-wrap">'
        f'<img src="{pln_logo_uri}" alt="PLN" class="brand-logo" />'
        f'</div>'
        if pln_logo_uri
        else '<div class="brand-omc">PLN</div>'
    )

    header_html = f"""
    <div class="omc-top-header">

      <div class="omc-top-card omc-top-brand">
        {brand_logo_html}
        <div class="brand-copy">
          <div class="brand-title">DASHBOARD GANGGUAN</div>
          <div class="brand-subtitle">
            UPT PEMATANG SIANTAR • {escape(scope_label)}
          </div>
        </div>
      </div>

      <div class="omc-top-card omc-top-month">
        <div class="head-label">Bulan Berjalan</div>
        <div class="month-main">{escape(month_label)}</div>
        <div class="head-note">{escape(period_label)}</div>
      </div>

      <div class="omc-top-card omc-top-time">
        <div class="head-label">Tanggal / Waktu</div>
        <div class="head-date">{now.strftime("%d %b %Y").upper()}</div>
        <div class="head-time">
          {now.strftime("%H:%M:%S")}
          <span>WIB</span>
        </div>
      </div>

      <div class="omc-top-card omc-top-status">
        <div class="head-label">Data Status</div>
        <div class="live">LIVE</div>
        <div class="head-note">Update {now.strftime("%H:%M:%S")}</div>
      </div>

      <div class="omc-top-card omc-top-status">
        <div class="head-label">Koneksi Sistem</div>
        <div class="live">NORMAL</div>
        <div class="head-note">DB | APP OK</div>
      </div>

    </div>
    """

    dashboard_html = f"""
    <div class="omc-shell">
      {header_html}
      <div class="wallboard">

      <div class="kpi-strip">
        {kpi_html}
      </div>

      <div class="main-row">

        <div class="panel">
          <div class="panel-title">Gangguan Terbaru</div>
          <div class="panel-body incident-body">

            <div class="incident-top">
              <div class="incident-count">{1 if incident else 0}</div>
              <div>
                <div class="incident-gi {incident_title_class}">
                  {escape(_short(incident_gi, 42))}
                </div>
                <div class="incident-feeder">
                  {escape(_short(incident_feeder, 42))}
                  <span style="margin-left:8px;color:{'#ff4d55' if incident_is_active else '#39d353' if incident else '#91a3b8'};font-size:7px;">
                    {'BELUM PULIH' if incident_is_active else 'SUDAH PULIH' if incident else ''}
                  </span>
                </div>
              </div>
            </div>

            <div class="incident-grid">
              <div class="detail-row">
                <div class="detail-label">Waktu Trip</div>
                <div class="detail-value">{escape(_event_clock(incident))}</div>
              </div>
              <div class="detail-row">
                <div class="detail-label">Relay Indikasi</div>
                <div class="detail-value">{escape(incident_relay)}</div>
              </div>
              <div class="detail-row">
                <div class="detail-label">Phasa Terdampak</div>
                <div class="detail-value">{escape(incident_phase)}</div>
              </div>
              <div class="detail-row">
                <div class="detail-label">Arus Gangguan</div>
                <div class="detail-value">{incident_fault:,.0f} A</div>
              </div>
              <div class="detail-row">
                <div class="detail-label">Trafo Sumber</div>
                <div class="detail-value">{escape(_short(incident_transformer, 25))}</div>
              </div>
              <div class="detail-row">
                <div class="detail-label">Status Supply</div>
                <div class="detail-value {supply_class}">{escape(incident_supply)}</div>
              </div>
              <div class="detail-row">
                <div class="detail-label">Aging</div>
                <div class="detail-value {'red' if incident_is_active else 'green' if incident else ''}">{incident_aging:,.0f} menit</div>
              </div>
              <div class="detail-row">
                <div class="detail-label">Wilayah Terdampak</div>
                <div class="detail-value">{escape(_short(impacted_area, 42))}</div>
              </div>
            </div>

            <div class="incident-mini-grid">
              <div class="incident-mini">
                <div class="incident-mini-label">Status Kejadian</div>
                <div class="incident-mini-value {'red' if incident_is_active else 'green' if incident else ''}">
                  {'BELUM PULIH' if incident_is_active else 'SUDAH PULIH' if incident else '-'}
                </div>
              </div>
              <div class="incident-mini">
                <div class="incident-mini-label">Gangguan Penyulang Hari Ini</div>
                <div class="incident-mini-value blue">{latest_feeder_today_count}</div>
              </div>
              <div class="incident-mini">
                <div class="incident-mini-label">Gangguan Penyulang Bulan Ini</div>
                <div class="incident-mini-value amber">{latest_feeder_month_count}</div>
              </div>
              <div class="incident-mini">
                <div class="incident-mini-label">Counter PMT Terbaru</div>
                <div class="incident-mini-value blue">{escape(incident_pmt_counter)}</div>
              </div>
            </div>

            <div class="latest-history">
              <div class="latest-history-title">10 Gangguan Terakhir — Bulan Berjalan • Relay • Wilayah Terdampak</div>
              {recent_history_html}

              <div class="latest-insight-grid">
                <div class="latest-insight-card">
                  <div class="latest-insight-label">Penyulang Dominan</div>
                  <div class="latest-insight-value blue">{escape(_short(top_recurring, 20))}</div>
                  <div class="latest-insight-note">{top_recurring_count} gangguan / 30 hari</div>
                </div>

                <div class="latest-insight-card">
                  <div class="latest-insight-label">Relay Dominan</div>
                  <div class="latest-insight-value amber">{escape(_short(dominant_relay, 20))}</div>
                  <div class="latest-insight-note">{dominant_relay_count} kejadian bulan ini</div>
                </div>

                <div class="latest-insight-card">
                  <div class="latest-insight-label">Wilayah Dominan</div>
                  <div class="latest-insight-value">{escape(_short(dominant_area, 20))}</div>
                  <div class="latest-insight-note">{dominant_area_count} kejadian bulan ini</div>
                </div>

                <div class="latest-insight-card">
                  <div class="latest-insight-label">ENS Bulan Ini</div>
                  <div class="latest-insight-value purple">{ens_month:,.1f} kWh</div>
                  <div class="latest-insight-note">Dampak energi bulan berjalan</div>
                </div>
              </div>
            </div>

          </div>
        </div>

        <div class="panel">
          <div class="panel-title">Trend Reliability — Bulan Berjalan</div>
          <div class="panel-body trend-body version-a">

            <div class="trend-insight-strip">
              <div class="trend-insight-card">
                <span>Total Gangguan</span>
                <strong class="amber">{month_total}</strong>
                <small>{month_daily_average:.1f} kejadian / hari</small>
              </div>

              <div class="trend-insight-card">
                <span>Peak Gangguan</span>
                <strong class="blue">{escape(peak_day_label)}</strong>
                <small>{peak_day_value} kejadian</small>
              </div>

              <div class="trend-insight-card">
                <span>ENS Bulan Ini</span>
                <strong class="purple">{ens_month:,.1f} kWh</strong>
                <small>Energy Not Supplied</small>
              </div>

              <div class="trend-insight-card">
                <span>Peak ENS</span>
                <strong class="purple">{escape(peak_ens_label)}</strong>
                <small>{peak_ens_value:,.1f} kWh</small>
              </div>

              <div class="trend-insight-card">
                <span>Hari Normal</span>
                <strong class="green">{normal_days} / {today.day}</strong>
                <small>{normal_day_percent:.0f}% bulan berjalan</small>
              </div>
            </div>

            <div class="trend-chart-grid">

              <div class="trend-chart-slot trend-slot-small-1">
                {secondary_chart_html[0]}
              </div>

              <div class="trend-chart-slot trend-slot-small-2">
                {secondary_chart_html[1]}
              </div>

              <div class="trend-chart-slot trend-slot-primary">
                {primary_chart_html}
              </div>

            </div>

          </div>
        </div>

      </div>

      <div class="lower-row">

        <div class="panel">
          <div class="panel-title">Analisa — Frekuensi Gangguan per Trafo</div>
          <div class="panel-body transformer-analysis">
            <div class="transformer-analysis-subtitle">
              Jumlah gangguan downstream yang terpetakan ke setiap Trafo
              pada bulan berjalan.
            </div>
            {transformer_frequency_html}
          </div>
        </div>

        <div class="panel">
          <div class="panel-title">Recovery Performance — Hari Ini</div>
          <div class="panel-body mini-bars">
            {recovery_html}
            <div class="recovery-foot">
              <span style="color:#91a3b8">Average Recovery</span>
              <strong class="amber">{avg_recovery:.1f} menit</strong>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-title">Top Penyulang Recurring — 30 Hari</div>
          <div class="panel-body ranking">
            {recurring_html}
          </div>
        </div>

      </div>

      <div class="attention-bar">
        <div class="attention-title">
          MANAGEMENT<br>ATTENTION
        </div>

        <div class="attention-item">
          <strong class="{'red' if incident_is_active else 'green'}">
            {escape(attention_one_title)}
          </strong>
          <span>{escape(attention_one_text)}</span>
        </div>

        <div class="attention-item">
          <strong class="{'amber' if top_recurring_count >= 2 else ''}">
            {escape(_short(top_recurring, 18))}
          </strong>
          <span>Recurring {top_recurring_count}× dalam 30 hari</span>
        </div>

        <div class="attention-item">
          <strong class="{'red' if no_fault_count else 'green'}">
            {no_fault_count} KEJADIAN
          </strong>
          <span>Tanpa data arus gangguan • Perlu verifikasi</span>
        </div>

        <div class="attention-item">
          <strong class="purple">
            ENS HARI INI
          </strong>
          <span>{ens_today:,.1f} kWh • Monitoring dampak energi</span>
        </div>
      </div>

      </div>
    </div>
    """

    compact_html = " ".join(
        line.strip()
        for line in dashboard_html.splitlines()
        if line.strip()
    )

    st.markdown(
        compact_html,
        unsafe_allow_html=True,
    )

    _inject_live_browser_clock()


# ==========================================================
# PAGE ENTRY
# ==========================================================


def render() -> None:
    if not is_authenticated():
        st.error("Sesi login tidak tersedia.")
        st.stop()

    hide_sidebar()
    _inject_css()
    _render_wallboard()


if __name__ == "__main__":
    render()
