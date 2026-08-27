from __future__ import annotations

from datetime import date

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DASHBOARD_CACHE_TTL_SECONDS = 120

from components.sidebar import render_sidebar
from services.access_service import can_view
from services.dashboard_filter_service import (
    get_dashboard_filter_options,
)
from services.dashboard_transformer_service import (
    get_transformer_fault_exposure,
    get_transformer_fault_exposure_coverage,
)
from services.dashboard_reliability_service import (
    get_dashboard_reliability_events,
)
from services.dashboard_operations_service import (
    get_dashboard_operations_events,
)
from services.dashboard_governance_service import (
    get_dashboard_governance,
)


def _safe_float(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _safe_int(value: object) -> int:
    return int(round(_safe_float(value)))


def _month_start(value: date) -> date:
    return value.replace(day=1)


MONTH_NAMES_ID = {
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


def _month_label(year_value: object, month_value: object) -> str:
    year = _safe_int(year_value)
    month = _safe_int(month_value)
    month_name = MONTH_NAMES_ID.get(month, str(month))
    return f"{month_name} {year}" if year else month_name


def _format_filter_option(
    value: str,
    lookup: dict[str, str],
    all_label: str,
) -> str:
    if value == "ALL":
        return all_label

    return lookup.get(value, str(value))


def _inject_dashboard_style() -> None:
    st.markdown(
        """
        <style>
        /* ====== PAGE ====== */
        .block-container {
            padding-top: 3.6rem;
            padding-bottom: 2rem;
            max-width: 1500px;
        }

        /* ====== HEADER ====== */
        .dashboard-hero {
            padding: 0.35rem 0 1rem 0;
            position: relative;
            z-index: 1;
        }
        .dashboard-title {
            font-size: 2rem;
            font-weight: 800;
            line-height: 1.1;
            letter-spacing: -0.02em;
            margin: 0;
        }
        .dashboard-subtitle {
            margin-top: 0.35rem;
            opacity: 0.72;
            font-size: 0.95rem;
        }

        /* ====== FILTER PANEL ====== */
        div[data-testid="stExpander"] {
            border-radius: 14px;
            border: 1px solid rgba(128,128,128,.18);
            overflow: hidden;
        }

        /* ====== METRICS ====== */
        div[data-testid="stMetric"] {
            background: rgba(255,255,255,.03);
            border: 1px solid rgba(128,128,128,.18);
            border-radius: 14px;
            padding: 1rem 1rem .9rem 1rem;
            min-height: 118px;
            box-shadow: 0 1px 2px rgba(0,0,0,.03);
        }
        div[data-testid="stMetricLabel"] {
            font-size: .78rem;
            opacity: .72;
        }
        div[data-testid="stMetricValue"] {
            font-weight: 800;
            letter-spacing: -.02em;
        }

        /* ====== TABS ====== */
        button[data-baseweb="tab"] {
            font-weight: 700;
            padding-left: 1rem;
            padding-right: 1rem;
        }

        /* ====== SECTION CARD ====== */
        .section-card {
            border: 1px solid rgba(128,128,128,.18);
            border-radius: 14px;
            padding: 1rem 1.1rem;
            margin-bottom: .9rem;
            background: rgba(255,255,255,.02);
        }
        .section-kicker {
            font-size: .72rem;
            text-transform: uppercase;
            letter-spacing: .08em;
            opacity: .62;
            font-weight: 700;
            margin-bottom: .2rem;
        }
        .section-title {
            font-size: 1.05rem;
            font-weight: 800;
            margin-bottom: .2rem;
        }
        .section-note {
            font-size: .86rem;
            opacity: .68;
        }

        /* ====== DATAFRAME ====== */
        div[data-testid="stDataFrame"] {
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid rgba(128,128,128,.16);
        }

        /* ====== ALERTS ====== */
        div[data-testid="stAlert"] {
            border-radius: 12px;
        }

        /* ====== BUTTONS / INPUTS ====== */
        button[kind="primary"] {
            border-radius: 10px;
            font-weight: 700;
        }
        div[data-baseweb="select"] > div {
            border-radius: 10px;
        }

        /* ====== COMPACT PRESENTATION MODE ====== */
        @media (min-width: 1100px) {
            .block-container {
                padding-left: 1.5rem;
                padding-right: 1.5rem;
            }
        }



        /* ====== EXECUTIVE VISUAL PANELS ====== */
        .quality-mini-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: .7rem;
            margin-bottom: .8rem;
        }
        .quality-mini-card {
            border: 1px solid rgba(128,128,128,.15);
            border-radius: 13px;
            padding: .7rem .75rem;
            background: rgba(255,255,255,.015);
        }
        .quality-mini-label {
            font-size: .68rem;
            opacity: .6;
            margin-bottom: .25rem;
        }
        .quality-mini-value {
            font-size: 1rem;
            font-weight: 850;
        }
        @media (max-width: 900px) {
            .quality-mini-grid {
                grid-template-columns: 1fr;
            }
        }

        /* ====== RELIABILITY PRESENTATION ====== */
        .rel-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 14px;
            margin-bottom: 1rem;
        }
        .rel-card {
            border: 1px solid rgba(128,128,128,.18);
            border-radius: 16px;
            padding: .95rem 1rem;
            min-height: 118px;
            background: linear-gradient(145deg, rgba(255,255,255,.04), rgba(255,255,255,.012));
            box-shadow: 0 6px 20px rgba(0,0,0,.035);
        }
        .rel-card-label { font-size:.74rem; font-weight:750; opacity:.68; margin-bottom:.38rem; }
        .rel-card-value { font-size:1.55rem; font-weight:850; letter-spacing:-.03em; line-height:1.08; margin-bottom:.35rem; }
        .rel-card-meta { font-size:.73rem; opacity:.64; line-height:1.35; }
        .rel-sla-grid {
            display:grid;
            grid-template-columns:repeat(5,minmax(0,1fr));
            gap:.7rem;
            margin-bottom:1rem;
        }
        .rel-sla-card {
            border:1px solid rgba(128,128,128,.16);
            border-radius:13px;
            padding:.75rem .8rem;
            text-align:center;
            background:rgba(255,255,255,.015);
        }
        .rel-sla-label { font-size:.7rem; opacity:.62; margin-bottom:.2rem; }
        .rel-sla-value { font-size:1.15rem; font-weight:850; }
        .rel-insight-grid {
            display:grid;
            grid-template-columns:repeat(3,minmax(0,1fr));
            gap:.75rem;
            margin-bottom:1rem;
        }
        .rel-insight {
            border:1px solid rgba(128,128,128,.16);
            border-radius:14px;
            padding:.8rem .85rem;
            min-height:86px;
            background:rgba(255,255,255,.015);
        }
        .rel-insight-kicker { font-size:.68rem; text-transform:uppercase; letter-spacing:.07em; opacity:.56; font-weight:700; margin-bottom:.3rem; }
        .rel-insight-value { font-size:.95rem; font-weight:800; margin-bottom:.2rem; }
        .rel-insight-note { font-size:.72rem; opacity:.65; line-height:1.35; }
        @media (max-width:1100px) {
            .rel-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .rel-insight-grid { grid-template-columns:1fr; }
        }
        @media (max-width:800px) {
            .rel-sla-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
        }
        @media (max-width:650px) {
            .rel-grid { grid-template-columns:1fr; }
        }

        /* ====== MODERN FILTER BAR ====== */
        .filter-shell {
            border: 1px solid rgba(128,128,128,.18);
            border-radius: 16px;
            padding: .9rem 1rem .95rem 1rem;
            margin: .25rem 0 1rem 0;
            background:
                linear-gradient(
                    145deg,
                    rgba(255,255,255,.035),
                    rgba(255,255,255,.012)
                );
            box-shadow: 0 6px 20px rgba(0,0,0,.035);
        }
        .filter-shell-head {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            align-items: center;
            margin-bottom: .55rem;
        }
        .filter-shell-title {
            font-size: .88rem;
            font-weight: 800;
        }
        .filter-shell-subtitle {
            font-size: .72rem;
            opacity: .62;
        }
        .filter-summary {
            display: flex;
            gap: .38rem;
            flex-wrap: wrap;
            margin-top: .55rem;
        }
        .filter-summary-chip {
            border: 1px solid rgba(128,128,128,.16);
            border-radius: 999px;
            padding: .22rem .5rem;
            font-size: .69rem;
            opacity: .8;
        }
        .filter-shell div[data-baseweb="select"] > div,
        .filter-shell input {
            border-radius: 10px !important;
        }
        .filter-shell label {
            font-size: .76rem !important;
            font-weight: 700 !important;
        }







        /* ====== DASHBOARD SEGMENTED NAVIGATION ====== */
        div[data-testid="stSegmentedControl"] {
            margin: .2rem 0 .95rem 0;
        }

        div[data-testid="stSegmentedControl"] > div {
            display: inline-flex !important;
            width: auto !important;
            padding: .28rem !important;
            gap: .32rem !important;
            border: 1px solid rgba(128,128,128,.16) !important;
            border-radius: 12px !important;
            background: rgba(128,128,128,.045) !important;
        }

        div[data-testid="stSegmentedControl"] button {
            min-height: 36px !important;
            padding: .4rem .9rem !important;
            border-radius: 9px !important;
            border: 1px solid transparent !important;
            font-size: .76rem !important;
            font-weight: 650 !important;
            background: transparent !important;
            box-shadow: none !important;
        }

        div[data-testid="stSegmentedControl"] button:hover {
            background: rgba(128,128,128,.08) !important;
        }

        div[data-testid="stSegmentedControl"] button[aria-pressed="true"] {
            background: rgba(255,255,255,.98) !important;
            border-color: rgba(128,128,128,.20) !important;
            box-shadow: 0 1px 4px rgba(0,0,0,.06) !important;
            font-weight: 800 !important;
        }

        div[data-testid="stSegmentedControl"] button p {
            margin: 0 !important;
            white-space: nowrap !important;
        }

        /* ====== FINAL DASHBOARD POLISH ====== */
        .block-container {
            max-width: 1480px;
            padding-top: 3.2rem;
            padding-bottom: 2.2rem;
        }

        h1, h2, h3 {
            letter-spacing: -0.02em;
        }

        div[data-testid="stCaptionContainer"] {
            margin-bottom: .6rem;
        }

        .section-card {
            margin-top: .15rem;
            margin-bottom: .55rem;
        }

        .section-card .section-kicker {
            font-size: .64rem;
            letter-spacing: .08em;
        }

        .section-card .section-title {
            font-size: .93rem;
            line-height: 1.2;
        }

        .section-card .section-note {
            font-size: .7rem;
            line-height: 1.35;
        }

        div[data-testid="stPlotlyChart"] {
            border: 1px solid rgba(128,128,128,.11);
            border-radius: 14px;
            padding: .15rem .2rem .05rem .2rem;
            background: rgba(255,255,255,.008);
        }

        div[data-testid="stDataFrame"] {
            border-radius: 12px;
            overflow: hidden;
        }

        div[data-testid="stExpander"] {
            border-radius: 12px;
            border-color: rgba(128,128,128,.15);
        }

        div[data-testid="stHorizontalBlock"] {
            gap: .8rem;
        }

        .clean-kpi-grid,
        .eng-kpi-grid,
        .ops-kpi-grid,
        .gov-kpi-grid,
        .rel-grid {
            gap: 10px;
        }

        .clean-kpi,
        .eng-kpi,
        .ops-kpi,
        .gov-kpi,
        .rel-card {
            box-shadow: none;
        }

        .clean-kpi-value,
        .eng-kpi-value,
        .ops-kpi-value,
        .gov-kpi-value,
        .rel-card-value {
            font-variant-numeric: tabular-nums;
        }

        .filter-shell {
            margin-top: .1rem;
            margin-bottom: .9rem;
        }

        .filter-summary {
            margin-top: .45rem;
        }

        @media (max-width: 900px) {
            .block-container {
                padding-top: 2.7rem;
            }
        }

        /* ====== CLEAN GOVERNANCE LAYOUT ====== */
        .gov-kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin: .2rem 0 .9rem 0;
        }
        .gov-kpi {
            border: 1px solid rgba(128,128,128,.16);
            border-radius: 14px;
            padding: .82rem .9rem;
            min-height: 104px;
            background: rgba(255,255,255,.016);
        }
        .gov-kpi-label {
            font-size: .69rem;
            opacity: .62;
            font-weight: 700;
            margin-bottom: .25rem;
        }
        .gov-kpi-value {
            font-size: 1.35rem;
            font-weight: 850;
            letter-spacing: -.025em;
            line-height: 1.08;
        }
        .gov-kpi-note {
            margin-top: .3rem;
            font-size: .67rem;
            opacity: .58;
            line-height: 1.3;
        }
        .gov-attention-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
            margin-bottom: .9rem;
        }
        .gov-attention-card {
            border: 1px solid rgba(128,128,128,.14);
            border-radius: 12px;
            padding: .72rem .8rem;
            background: rgba(255,255,255,.012);
            min-height: 84px;
        }
        .gov-attention-title {
            font-size: .7rem;
            font-weight: 800;
            margin-bottom: .18rem;
        }
        .gov-attention-text {
            font-size: .69rem;
            opacity: .68;
            line-height: 1.35;
        }
        @media (max-width: 1100px) {
            .gov-kpi-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .gov-attention-grid {
                grid-template-columns: 1fr;
            }
        }
        @media (max-width: 650px) {
            .gov-kpi-grid {
                grid-template-columns: 1fr;
            }
        }

        /* ====== CLEAN OPERATIONS LAYOUT ====== */
        .ops-kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin: .2rem 0 .9rem 0;
        }
        .ops-kpi {
            border: 1px solid rgba(128,128,128,.16);
            border-radius: 14px;
            padding: .82rem .9rem;
            min-height: 104px;
            background: rgba(255,255,255,.016);
        }
        .ops-kpi-label {
            font-size: .69rem;
            opacity: .62;
            font-weight: 700;
            margin-bottom: .25rem;
        }
        .ops-kpi-value {
            font-size: 1.35rem;
            font-weight: 850;
            letter-spacing: -.025em;
            line-height: 1.08;
        }
        .ops-kpi-note {
            margin-top: .3rem;
            font-size: .67rem;
            opacity: .58;
            line-height: 1.3;
        }
        .ops-mini-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px;
            margin-bottom: .9rem;
        }
        .ops-mini {
            border: 1px solid rgba(128,128,128,.14);
            border-radius: 12px;
            padding: .7rem .8rem;
            background: rgba(255,255,255,.012);
        }
        .ops-mini-label {
            font-size: .66rem;
            opacity: .58;
            margin-bottom: .18rem;
        }
        .ops-mini-value {
            font-size: .98rem;
            font-weight: 820;
        }
        @media (max-width: 1100px) {
            .ops-kpi-grid,
            .ops-mini-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        @media (max-width: 650px) {
            .ops-kpi-grid,
            .ops-mini-grid {
                grid-template-columns: 1fr;
            }
        }

        /* ====== CLEAN ANALISA LAYOUT ====== */
        .eng-kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin: .2rem 0 .9rem 0;
        }
        .eng-kpi {
            border: 1px solid rgba(128,128,128,.16);
            border-radius: 14px;
            padding: .82rem .9rem;
            min-height: 104px;
            background: rgba(255,255,255,.016);
        }
        .eng-kpi-label {
            font-size: .69rem;
            opacity: .62;
            font-weight: 700;
            margin-bottom: .25rem;
        }
        .eng-kpi-value {
            font-size: 1.35rem;
            font-weight: 850;
            letter-spacing: -.025em;
            line-height: 1.08;
        }
        .eng-kpi-note {
            margin-top: .3rem;
            font-size: .67rem;
            opacity: .58;
            line-height: 1.3;
        }
        .eng-status-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
            margin-bottom: .9rem;
        }
        .eng-status-card {
            border: 1px solid rgba(128,128,128,.14);
            border-radius: 12px;
            padding: .7rem .8rem;
            background: rgba(255,255,255,.012);
        }
        .eng-status-label {
            font-size: .66rem;
            opacity: .58;
            margin-bottom: .18rem;
        }
        .eng-status-value {
            font-size: .98rem;
            font-weight: 820;
        }
        @media (max-width: 1100px) {
            .eng-kpi-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .eng-status-grid {
                grid-template-columns: 1fr;
            }
        }
        @media (max-width: 650px) {
            .eng-kpi-grid {
                grid-template-columns: 1fr;
            }
        }


        /* ====== EXECUTIVE NARRATIVE ====== */
        .exec-narrative {
            border: 1px solid rgba(128,128,128,.15);
            border-radius: 14px;
            padding: .9rem 1rem;
            background: rgba(255,255,255,.014);
            margin: .25rem 0 .9rem 0;
        }
        .exec-narrative-title {
            font-size: .76rem;
            font-weight: 800;
            margin-bottom: .45rem;
        }
        .exec-narrative-list {
            margin: 0;
            padding-left: 1.05rem;
        }
        .exec-narrative-list li {
            margin-bottom: .34rem;
            font-size: .72rem;
            line-height: 1.42;
            opacity: .76;
        }
        .exec-narrative-list li:last-child {
            margin-bottom: 0;
        }

        /* ====== CLEAN EXECUTIVE LAYOUT ====== */
        .clean-kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin: .2rem 0 .8rem 0;
        }
        .clean-kpi {
            border: 1px solid rgba(128,128,128,.16);
            border-radius: 14px;
            padding: .85rem .9rem;
            background: rgba(255,255,255,.018);
            min-height: 108px;
        }
        .clean-kpi-label {
            font-size: .7rem;
            font-weight: 700;
            opacity: .62;
            margin-bottom: .28rem;
        }
        .clean-kpi-value {
            font-size: 1.45rem;
            font-weight: 850;
            letter-spacing: -.025em;
            line-height: 1.1;
        }
        .clean-kpi-note {
            margin-top: .3rem;
            font-size: .68rem;
            opacity: .58;
            line-height: 1.3;
        }
        .clean-secondary-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px;
            margin-bottom: 1rem;
        }
        .clean-secondary {
            border: 1px solid rgba(128,128,128,.13);
            border-radius: 12px;
            padding: .7rem .8rem;
            background: rgba(255,255,255,.012);
        }
        .clean-secondary-label {
            font-size: .66rem;
            opacity: .58;
            margin-bottom: .2rem;
        }
        .clean-secondary-value {
            font-size: 1rem;
            font-weight: 820;
        }
        .clean-attention-grid {
            display:grid;
            grid-template-columns:repeat(3,minmax(0,1fr));
            gap:.65rem;
            margin-bottom: .8rem;
        }
        .clean-attention-card {
            border:1px solid rgba(128,128,128,.15);
            border-radius:12px;
            padding:.72rem .8rem;
            background:rgba(255,255,255,.012);
            min-height:82px;
        }
        .clean-attention-title {
            font-size:.72rem;
            font-weight:800;
            margin-bottom:.2rem;
        }
        .clean-attention-text {
            font-size:.7rem;
            opacity:.68;
            line-height:1.35;
        }
        @media (max-width:1100px) {
            .clean-kpi-grid,
            .clean-secondary-grid {
                grid-template-columns:repeat(2,minmax(0,1fr));
            }
            .clean-attention-grid {
                grid-template-columns:1fr;
            }
        }
        @media (max-width:650px) {
            .clean-kpi-grid,
            .clean-secondary-grid {
                grid-template-columns:1fr;
            }
        }

        /* ====== EXECUTIVE PRESENTATION CARDS ====== */
        .exec-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 14px;
            margin: .25rem 0 1rem 0;
        }
        .exec-card {
            border: 1px solid rgba(128,128,128,.18);
            border-radius: 16px;
            padding: 1rem 1rem .95rem 1rem;
            min-height: 132px;
            background:
                linear-gradient(
                    145deg,
                    rgba(255,255,255,.045),
                    rgba(255,255,255,.012)
                );
            box-shadow: 0 8px 24px rgba(0,0,0,.045);
        }
        .exec-card-label {
            font-size: .76rem;
            font-weight: 700;
            opacity: .68;
            margin-bottom: .45rem;
            letter-spacing: .01em;
        }
        .exec-card-value {
            font-size: 1.65rem;
            line-height: 1.08;
            font-weight: 850;
            letter-spacing: -.035em;
            margin-bottom: .45rem;
        }
        .exec-card-meta {
            font-size: .76rem;
            opacity: .68;
            line-height: 1.35;
        }
        .exec-delta {
            display: inline-block;
            margin-top: .25rem;
            padding: .2rem .48rem;
            border-radius: 999px;
            font-size: .72rem;
            font-weight: 750;
            border: 1px solid rgba(128,128,128,.18);
        }
        .exec-delta-good {
            background: rgba(34,197,94,.10);
        }
        .exec-delta-bad {
            background: rgba(239,68,68,.10);
        }
        .exec-delta-neutral {
            background: rgba(148,163,184,.10);
        }

        .exec-panel-grid {
            display: grid;
            grid-template-columns: 1.2fr .8fr;
            gap: 14px;
            margin-bottom: 1rem;
        }
        .exec-panel {
            border: 1px solid rgba(128,128,128,.18);
            border-radius: 16px;
            padding: 1rem 1.05rem;
            background: rgba(255,255,255,.018);
        }
        .exec-panel-title {
            font-size: .96rem;
            font-weight: 800;
            margin-bottom: .7rem;
        }
        .exec-list {
            display: grid;
            gap: .58rem;
        }
        .exec-list-row {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 1rem;
            align-items: center;
            padding-bottom: .5rem;
            border-bottom: 1px solid rgba(128,128,128,.12);
            font-size: .83rem;
        }
        .exec-list-row:last-child {
            border-bottom: 0;
            padding-bottom: 0;
        }
        .exec-list-key {
            opacity: .68;
        }
        .exec-list-val {
            font-weight: 800;
            text-align: right;
        }

        .exec-attention {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: .75rem;
            margin-bottom: 1rem;
        }
        .exec-attention-item {
            border-radius: 14px;
            padding: .9rem .95rem;
            border: 1px solid rgba(128,128,128,.16);
            min-height: 96px;
            display: flex;
            gap: .75rem;
            align-items: flex-start;
            background: rgba(255,255,255,.02);
        }
        .exec-attention-icon {
            font-size: 1.15rem;
            line-height: 1;
            margin-top: .08rem;
        }
        .exec-attention-body {
            min-width: 0;
        }
        .exec-attention-title {
            font-size: .76rem;
            font-weight: 800;
            margin-bottom: .28rem;
        }
        .exec-attention-text {
            font-size: .78rem;
            line-height: 1.42;
            opacity: .78;
        }
        .exec-attention-high {
            background: rgba(239,68,68,.07);
            border-color: rgba(239,68,68,.22);
        }
        .exec-attention-medium {
            background: rgba(245,158,11,.07);
            border-color: rgba(245,158,11,.22);
        }
        .exec-attention-info {
            background: rgba(59,130,246,.06);
            border-color: rgba(59,130,246,.18);
        }
        .exec-attention-ok {
            background: rgba(34,197,94,.07);
            border-color: rgba(34,197,94,.22);
        }

        .scope-chip-row {
            display: flex;
            gap: .4rem;
            flex-wrap: wrap;
            margin: .15rem 0 .95rem 0;
        }
        .scope-chip {
            border: 1px solid rgba(128,128,128,.17);
            border-radius: 999px;
            padding: .25rem .58rem;
            font-size: .72rem;
            opacity: .82;
        }

        @media (max-width: 1100px) {
            .exec-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .exec-panel-grid {
                grid-template-columns: 1fr;
            }
        }
        @media (max-width: 900px) {
            .exec-attention {
                grid-template-columns: 1fr;
            }
        }
        @media (max-width: 700px) {
            .exec-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _html_escape(value: object) -> str:
    text = str(value if value is not None else "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _delta_badge(
    current: float,
    previous: float,
    *,
    lower_is_better: bool = True,
) -> str:
    if previous == 0:
        if current == 0:
            return '<span class="exec-delta exec-delta-neutral">0.0%</span>'
        return '<span class="exec-delta exec-delta-neutral">periode baru</span>'

    pct = ((current - previous) / previous) * 100.0
    is_good = pct < 0 if lower_is_better else pct > 0
    css = "exec-delta-good" if is_good else "exec-delta-bad"
    sign = "+" if pct > 0 else ""

    return (
        f'<span class="exec-delta {css}">'
        f'{sign}{pct:.1f}% vs periode lalu'
        f'</span>'
    )


def _exec_card(
    label: str,
    value: str,
    *,
    meta: str = "",
    badge_html: str = "",
) -> str:
    # HTML dibuat satu baris agar Markdown Streamlit tidak
    # menganggap indentasi sebagai code block.
    return (
        '<div class="exec-card">'
        f'<div class="exec-card-label">{_html_escape(label)}</div>'
        f'<div class="exec-card-value">{_html_escape(value)}</div>'
        f'<div class="exec-card-meta">{_html_escape(meta)}</div>'
        f'{badge_html}'
        '</div>'
    )


def _section_header(
    title: str,
    *,
    kicker: str | None = None,
    note: str | None = None,
) -> None:
    kicker_html = (
        f'<div class="section-kicker">{kicker}</div>'
        if kicker
        else ""
    )
    note_html = (
        f'<div class="section-note">{note}</div>'
        if note
        else ""
    )
    st.markdown(
        f"""
        <div class="section-card">
            {kicker_html}
            <div class="section-title">{title}</div>
            {note_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=60, show_spinner=False)
def _load_transformer_exposure(
    start_date: date,
    end_date: date,
    ultg_flc: str | None,
    gi_flc: str | None,
    bay_flc: str | None,
    penyulang_id: str | None,
) -> list[dict[str, object]]:
    return get_transformer_fault_exposure(
        start_date=start_date,
        end_date=end_date,
        ultg_flc=ultg_flc,
        gi_flc=gi_flc,
        bay_flc=bay_flc,
        penyulang_id=penyulang_id,
    )


@st.cache_data(ttl=60, show_spinner=False)
def _load_transformer_coverage(
    start_date: date,
    end_date: date,
    ultg_flc: str | None,
    gi_flc: str | None,
    bay_flc: str | None,
    penyulang_id: str | None,
) -> dict[str, object]:
    return get_transformer_fault_exposure_coverage(
        start_date=start_date,
        end_date=end_date,
        ultg_flc=ultg_flc,
        gi_flc=gi_flc,
        bay_flc=bay_flc,
        penyulang_id=penyulang_id,
    )


@st.cache_data(ttl=60, show_spinner=False)
def _load_reliability_events(
    start_date: date,
    end_date: date,
    ultg_flc: str | None,
    gi_flc: str | None,
    bay_flc: str | None,
    penyulang_id: str | None,
) -> list[dict[str, object]]:
    return get_dashboard_reliability_events(
        start_date=start_date,
        end_date=end_date,
        ultg_flc=ultg_flc,
        gi_flc=gi_flc,
        bay_flc=bay_flc,
        penyulang_id=penyulang_id,
    )


@st.cache_data(ttl=60, show_spinner=False)
def _load_dashboard_filter_options() -> list[dict[str, object]]:
    return get_dashboard_filter_options()


@st.cache_data(ttl=30, show_spinner=False)
def _load_operations_events(
    start_date: date,
    end_date: date,
    ultg_flc: str | None,
    gi_flc: str | None,
    bay_flc: str | None,
    penyulang_id: str | None,
) -> list[dict[str, object]]:
    return get_dashboard_operations_events(
        start_date=start_date,
        end_date=end_date,
        ultg_flc=ultg_flc,
        gi_flc=gi_flc,
        bay_flc=bay_flc,
        penyulang_id=penyulang_id,
    )


@st.cache_data(ttl=60, show_spinner=False)
def _load_governance(
    start_date: date,
    end_date: date,
    ultg_flc: str | None,
    gi_flc: str | None,
    bay_flc: str | None,
    penyulang_id: str | None,
) -> dict[str, object]:
    return get_dashboard_governance(
        start_date=start_date,
        end_date=end_date,
        ultg_flc=ultg_flc,
        gi_flc=gi_flc,
        bay_flc=bay_flc,
        penyulang_id=penyulang_id,
    )


def _render_engineering_tab(
    start_date: date,
    end_date: date,
    ultg_flc: str | None,
    gi_flc: str | None,
    bay_flc: str | None,
    penyulang_id: str | None,
) -> None:
    st.subheader("Analisa")
    st.caption(
        "Analisa paparan arus gangguan terhadap Trafo Daya berdasarkan "
        "mapping Trafo → Bay Penyulang → Penyulang."
    )

    try:
        exposure = _load_transformer_exposure(
            start_date,
            end_date,
            ultg_flc,
            gi_flc,
            bay_flc,
            penyulang_id,
        )
        coverage = _load_transformer_coverage(
            start_date,
            end_date,
            ultg_flc,
            gi_flc,
            bay_flc,
            penyulang_id,
        )
    except Exception as exc:
        st.error(f"Data analisa tidak dapat dimuat: {exc}")
        return

    total_gangguan = _safe_int(coverage.get("total_gangguan"))
    mapped_gangguan = _safe_int(coverage.get("mapped_gangguan"))
    unmapped_gangguan = _safe_int(coverage.get("unmapped_gangguan"))
    coverage_percent = _safe_float(coverage.get("coverage_percent"))

    rows_with_events = [
        row
        for row in exposure
        if _safe_int(row.get("event_count")) > 0
    ]

    max_fault_row = max(
        rows_with_events,
        key=lambda row: _safe_float(row.get("max_fault_current_a")),
        default=None,
    )
    max_multiple_row = max(
        rows_with_events,
        key=lambda row: _safe_float(row.get("max_fault_multiple")),
        default=None,
    )

    max_fault = (
        _safe_float(max_fault_row.get("max_fault_current_a"))
        if max_fault_row is not None
        else 0.0
    )
    max_fault_trafo = (
        str(max_fault_row.get("transformer_bay_name") or "-")
        if max_fault_row is not None
        else "-"
    )

    max_multiple = (
        _safe_float(max_multiple_row.get("max_fault_multiple"))
        if max_multiple_row is not None
        else 0.0
    )
    max_multiple_trafo = (
        str(max_multiple_row.get("transformer_bay_name") or "-")
        if max_multiple_row is not None
        else "-"
    )

    total_ens = sum(
        _safe_float(row.get("total_ens_kwh"))
        for row in rows_with_events
    )

    # Primary Engineering KPI
    eng_kpis = [
        (
            "Gangguan Terpetakan",
            f"{mapped_gangguan}",
            f"dari {total_gangguan} gangguan",
        ),
        (
            "Coverage Mapping",
            f"{coverage_percent:.1f}%",
            "Trafo ↔ Bay ↔ Penyulang",
        ),
        (
            "Max Fault Current",
            f"{max_fault:,.0f} A",
            max_fault_trafo,
        ),
        (
            "Max Fault Multiple",
            f"{max_multiple:.2f} × In",
            max_multiple_trafo,
        ),
    ]

    eng_html = "".join(
        (
            '<div class="eng-kpi">'
            f'<div class="eng-kpi-label">{_html_escape(label)}</div>'
            f'<div class="eng-kpi-value">{_html_escape(value)}</div>'
            f'<div class="eng-kpi-note">{_html_escape(note)}</div>'
            '</div>'
        )
        for label, value, note in eng_kpis
    )
    st.markdown(
        f'<div class="eng-kpi-grid">{eng_html}</div>',
        unsafe_allow_html=True,
    )

    status_items = [
        ("Trafo Terdampak", f"{len(rows_with_events)}"),
        ("Belum Terpetakan", f"{unmapped_gangguan}"),
        ("ENS Downstream", f"{total_ens:,.1f} kWh"),
    ]
    status_html = "".join(
        (
            '<div class="eng-status-card">'
            f'<div class="eng-status-label">{_html_escape(label)}</div>'
            f'<div class="eng-status-value">{_html_escape(value)}</div>'
            '</div>'
        )
        for label, value in status_items
    )
    st.markdown(
        f'<div class="eng-status-grid">{status_html}</div>',
        unsafe_allow_html=True,
    )

    if total_gangguan > 0 and unmapped_gangguan > 0:
        st.warning(
            f"{unmapped_gangguan} gangguan pada periode ini belum dapat "
            "dikaitkan ke Trafo berdasarkan histori mapping."
        )

    if not rows_with_events:
        st.info(
            "Belum ada gangguan terpetakan ke Trafo pada periode yang dipilih."
        )
        return

    df = pd.DataFrame(rows_with_events)

    # Row 1 — Fault Multiple vs Frequency
    left, right = st.columns(2)

    with left:
        _section_header(
            "Fault Multiple per Trafo",
            kicker="Analisa",
            note="Perbandingan arus gangguan maksimum terhadap arus nominal sekunder Trafo.",
        )

        fault_df = pd.DataFrame(
            [
                {
                    "Trafo": str(
                        row.get("transformer_bay_name")
                        or row.get("techidentno")
                        or "-"
                    ),
                    "Fault Multiple": _safe_float(
                        row.get("max_fault_multiple")
                    ),
                }
                for row in rows_with_events
            ]
        )
        fault_df = (
            fault_df[fault_df["Fault Multiple"] > 0]
            .sort_values("Fault Multiple", ascending=True)
            .tail(8)
        )

        if fault_df.empty:
            st.info("Belum ada data Fault Multiple yang dapat ditampilkan.")
        else:
            fig = px.bar(
                fault_df,
                x="Fault Multiple",
                y="Trafo",
                orientation="h",
                text=fault_df["Fault Multiple"].map(
                    lambda x: f"{x:.2f} × In"
                ),
            )
            fig.update_traces(
                textposition="outside",
                cliponaxis=False,
            )
            fig.update_layout(
                height=285,
                margin=dict(l=10, r=20, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                xaxis_title="× In",
                yaxis_title=None,
                font=dict(size=10),
            )
            fig.update_xaxes(
                rangemode="tozero",
                gridcolor="rgba(128,128,128,.12)",
            )
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False},
            )

    with right:
        _section_header(
            "Frekuensi Gangguan per Trafo",
            kicker="Analisa",
            note="Jumlah gangguan downstream yang terpetakan ke setiap Trafo.",
        )

        freq_df = pd.DataFrame(
            [
                {
                    "Trafo": str(
                        row.get("transformer_bay_name")
                        or row.get("techidentno")
                        or "-"
                    ),
                    "Gangguan": _safe_int(row.get("event_count")),
                }
                for row in rows_with_events
            ]
        )
        freq_df = (
            freq_df.sort_values("Gangguan", ascending=True)
            .tail(8)
        )

        fig = px.bar(
            freq_df,
            x="Gangguan",
            y="Trafo",
            orientation="h",
            text="Gangguan",
        )
        fig.update_traces(
            textposition="outside",
            cliponaxis=False,
        )
        fig.update_layout(
            height=285,
            margin=dict(l=10, r=20, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
            xaxis_title=None,
            yaxis_title=None,
            font=dict(size=10),
        )
        fig.update_xaxes(
            rangemode="tozero",
            gridcolor="rgba(128,128,128,.12)",
            dtick=1,
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False},
        )

    # Row 2 — Phase fault profile + ENS
    left2, right2 = st.columns(2)

    with left2:
        _section_header(
            "Fault Current per Phasa",
            kicker="Analisa",
            note="Arus gangguan maksimum R/S/T/N pada Trafo dengan paparan tertinggi.",
        )

        phase_rows = []
        for row in rows_with_events:
            phase_rows.append(
                {
                    "Trafo": str(
                        row.get("transformer_bay_name")
                        or row.get("techidentno")
                        or "-"
                    ),
                    "R": _safe_float(row.get("max_fault_current_r_a")),
                    "S": _safe_float(row.get("max_fault_current_s_a")),
                    "T": _safe_float(row.get("max_fault_current_t_a")),
                    "N": _safe_float(row.get("max_fault_current_n_a")),
                }
            )

        phase_df = pd.DataFrame(phase_rows)
        phase_df["Max"] = phase_df[["R", "S", "T", "N"]].max(axis=1)
        phase_df = (
            phase_df.sort_values("Max", ascending=False)
            .head(6)
            .drop(columns=["Max"])
        )

        phase_long = phase_df.melt(
            id_vars="Trafo",
            var_name="Phasa",
            value_name="Arus (A)",
        )

        fig = px.bar(
            phase_long,
            x="Trafo",
            y="Arus (A)",
            color="Phasa",
            barmode="group",
        )
        fig.update_layout(
            height=285,
            margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
            ),
            xaxis_title=None,
            yaxis_title="A",
            font=dict(size=10),
        )
        fig.update_yaxes(
            rangemode="tozero",
            gridcolor="rgba(128,128,128,.12)",
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False},
        )

    with right2:
        _section_header(
            "ENS Downstream per Trafo",
            kicker="Analisa",
            note="Akumulasi ENS dari penyulang downstream pada periode terpilih.",
        )

        ens_df = pd.DataFrame(
            [
                {
                    "Trafo": str(
                        row.get("transformer_bay_name")
                        or row.get("techidentno")
                        or "-"
                    ),
                    "ENS (kWh)": _safe_float(row.get("total_ens_kwh")),
                }
                for row in rows_with_events
            ]
        )
        ens_df = (
            ens_df.sort_values("ENS (kWh)", ascending=True)
            .tail(8)
        )

        fig = px.bar(
            ens_df,
            x="ENS (kWh)",
            y="Trafo",
            orientation="h",
            text=ens_df["ENS (kWh)"].map(lambda x: f"{x:,.1f}"),
        )
        fig.update_traces(
            textposition="outside",
            cliponaxis=False,
        )
        fig.update_layout(
            height=285,
            margin=dict(l=10, r=20, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
            xaxis_title="kWh",
            yaxis_title=None,
            font=dict(size=10),
        )
        fig.update_xaxes(
            rangemode="tozero",
            gridcolor="rgba(128,128,128,.12)",
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False},
        )

    # Detail table is kept available but not dominant.
    with st.expander("Detail Transformer Fault Exposure", expanded=False):
        display_columns = [
            "gi_name",
            "transformer_bay_name",
            "rated_power_mva",
            "rated_secondary_current_a",
            "event_count",
            "feeder_count",
            "total_ens_kwh",
            "max_fault_current_r_a",
            "max_fault_current_s_a",
            "max_fault_current_t_a",
            "max_fault_current_n_a",
            "max_fault_current_a",
            "max_fault_multiple",
            "top_feeder_name",
            "top_feeder_event_count",
        ]

        available_columns = [
            column
            for column in display_columns
            if column in df.columns
        ]

        rename = {
            "gi_name": "Gardu Induk",
            "transformer_bay_name": "Trafo Daya",
            "rated_power_mva": "Daya (MVA)",
            "rated_secondary_current_a": "In Sekunder (A)",
            "event_count": "Gangguan",
            "feeder_count": "Penyulang Terdampak",
            "total_ens_kwh": "ENS (kWh)",
            "max_fault_current_r_a": "Max R (A)",
            "max_fault_current_s_a": "Max S (A)",
            "max_fault_current_t_a": "Max T (A)",
            "max_fault_current_n_a": "Max N (A)",
            "max_fault_current_a": "Max Fault (A)",
            "max_fault_multiple": "Fault Multiple (×In)",
            "top_feeder_name": "Penyulang Dominan",
            "top_feeder_event_count": "Gangguan Penyulang Dominan",
        }

        st.dataframe(
            df[available_columns].rename(columns=rename),
            use_container_width=True,
            hide_index=True,
            height=430,
        )

    st.info(
        "I²t belum dihitung karena clearing time proteksi belum tersedia. "
        "Durasi padam pelanggan / waktu pemulihan tidak digunakan sebagai clearing time."
    )

def _build_executive_narrative(
    *,
    current_events: int,
    previous_events: int,
    current_ens: float,
    previous_ens: float,
    current_recovery: float,
    previous_recovery: float,
    active_events: int,
    top_feeder: str,
    top_feeder_count: int,
    max_fault_current: float,
    max_fault_multiple: float,
    max_fault_transformer: str,
    completeness_pct: float,
    report_period_label: str,
    report_compliance_pct: float,
) -> list[str]:
    items: list[str] = []

    if previous_events > 0:
        event_delta_pct = (
            (current_events - previous_events)
            / previous_events
            * 100
        )
        if event_delta_pct > 0:
            items.append(
                f"Jumlah gangguan meningkat {event_delta_pct:.1f}% "
                f"dibanding periode sebelumnya "
                f"({previous_events} menjadi {current_events} kejadian)."
            )
        elif event_delta_pct < 0:
            items.append(
                f"Jumlah gangguan menurun {abs(event_delta_pct):.1f}% "
                f"dibanding periode sebelumnya "
                f"({previous_events} menjadi {current_events} kejadian)."
            )
        else:
            items.append(
                f"Jumlah gangguan tetap {current_events} kejadian "
                "dibanding periode sebelumnya."
            )
    else:
        items.append(
            f"Tercatat {current_events} gangguan pada periode terpilih."
        )

    if current_ens > 0:
        if previous_ens > 0:
            ens_delta_pct = (
                (current_ens - previous_ens)
                / previous_ens
                * 100
            )
            direction = (
                "meningkat"
                if ens_delta_pct > 0
                else "menurun"
                if ens_delta_pct < 0
                else "tetap"
            )
            if direction == "tetap":
                items.append(
                    f"ENS tercatat {current_ens:,.1f} kWh "
                    "dan relatif tetap dibanding periode sebelumnya."
                )
            else:
                items.append(
                    f"ENS {direction} {abs(ens_delta_pct):.1f}% "
                    f"menjadi {current_ens:,.1f} kWh."
                )
        else:
            items.append(
                f"ENS pada periode ini sebesar {current_ens:,.1f} kWh."
            )

    if current_recovery > 0:
        if previous_recovery > 0:
            recovery_delta = current_recovery - previous_recovery
            if recovery_delta > 0:
                items.append(
                    f"Rata-rata pemulihan menjadi {current_recovery:,.1f} menit, "
                    f"lebih lama {abs(recovery_delta):,.1f} menit "
                    "dibanding periode sebelumnya."
                )
            elif recovery_delta < 0:
                items.append(
                    f"Rata-rata pemulihan membaik menjadi "
                    f"{current_recovery:,.1f} menit, "
                    f"lebih cepat {abs(recovery_delta):,.1f} menit."
                )
            else:
                items.append(
                    f"Rata-rata pemulihan tetap "
                    f"{current_recovery:,.1f} menit."
                )
        else:
            items.append(
                f"Rata-rata pemulihan pada periode ini "
                f"{current_recovery:,.1f} menit."
            )

    if top_feeder != "-" and top_feeder_count > 0:
        items.append(
            f"Penyulang dengan frekuensi gangguan tertinggi adalah "
            f"{top_feeder} dengan {top_feeder_count} kejadian."
        )

    if max_fault_multiple > 0:
        items.append(
            f"Paparan arus gangguan tertinggi teridentifikasi pada "
            f"{max_fault_transformer} sebesar {max_fault_current:,.0f} A "
            f"atau {max_fault_multiple:.2f} x In."
        )

    if active_events > 0:
        items.append(
            f"Terdapat {active_events} kejadian yang masih aktif "
            "dan memerlukan monitoring sampai proses pemulihan selesai."
        )

    if completeness_pct < 95:
        items.append(
            f"Data completeness saat ini {completeness_pct:.1f}%, "
            "masih di bawah target internal 95%."
        )
    else:
        items.append(
            f"Data completeness mencapai {completeness_pct:.1f}%."
        )

    if report_compliance_pct < 100:
        items.append(
            f"Compliance laporan {report_period_label} baru "
            f"{report_compliance_pct:.1f}% dan masih memerlukan penyelesaian "
            "proses verifikasi."
        )
    else:
        items.append(
            f"Compliance laporan {report_period_label} telah mencapai 100%."
        )

    return items[:6]


def _build_executive_pdf(
    *,
    start_date: date,
    end_date: date,
    scope_labels: list[str],
    current_events: int,
    current_ens: float,
    current_recovery: float,
    affected_feeders: int,
    active_events: int,
    max_fault_current: float,
    max_fault_multiple: float,
    completeness_pct: float,
    report_period_label: str,
    report_compliance_pct: float,
    daily_trend: list[tuple[str, int]],
    cause_data: list[tuple[str, int]],
    feeder_data: list[tuple[str, int]],
    transformer_data: list[tuple[str, float]],
    narrative_items: list[str],
    attention_items: list[tuple[str, str]],
) -> bytes:
    buffer = BytesIO()

    page_width, page_height = landscape(A4)
    pdf = canvas.Canvas(
        buffer,
        pagesize=(page_width, page_height),
    )
    pdf.setTitle("Dashboard Gangguan Penyulang 20 kV")
    pdf.setAuthor("Gangguan Penyulang 20 kV")

    # ---- Palette ----
    bg = colors.HexColor("#F7F8FA")
    card = colors.white
    border = colors.HexColor("#E5E7EB")
    text = colors.HexColor("#111827")
    muted = colors.HexColor("#6B7280")
    grid = colors.HexColor("#E5E7EB")
    accent = colors.HexColor("#2563EB")
    accent_2 = colors.HexColor("#0EA5E9")
    alert_bg = colors.HexColor("#FFF7ED")
    alert_border = colors.HexColor("#FED7AA")

    pdf.setFillColor(bg)
    pdf.rect(0, 0, page_width, page_height, fill=1, stroke=0)

    margin_x = 22
    top = page_height - 20

    # ---- Header ----
    pdf.setFillColor(text)
    pdf.setFont("Helvetica-Bold", 17)
    pdf.drawString(
        margin_x,
        top,
        "Dashboard Gangguan Penyulang 20 kV",
    )

    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 7.8)
    pdf.drawString(
        margin_x,
        top - 15,
        "Executive Monitoring | Reliability | Analisa | Operations | Governance",
    )

    period_text = (
        f"{start_date.strftime('%d %b %Y')} - "
        f"{end_date.strftime('%d %b %Y')}"
    )
    scope_text = " | ".join(scope_labels)

    pdf.setFont("Helvetica", 7.5)
    pdf.drawRightString(
        page_width - margin_x,
        top,
        period_text,
    )
    pdf.drawRightString(
        page_width - margin_x,
        top - 15,
        scope_text[:130],
    )

    # ---- Helpers ----
    def rounded_card(
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill_color=card,
        stroke_color=border,
        radius: float = 8,
    ) -> None:
        pdf.setFillColor(fill_color)
        pdf.setStrokeColor(stroke_color)
        pdf.setLineWidth(0.6)
        pdf.roundRect(
            x,
            y,
            w,
            h,
            radius,
            fill=1,
            stroke=1,
        )

    def draw_kpi(
        x: float,
        y: float,
        w: float,
        h: float,
        label: str,
        value: str,
        note: str,
    ) -> None:
        rounded_card(x, y, w, h)

        pdf.setFillColor(muted)
        pdf.setFont("Helvetica-Bold", 6.6)
        pdf.drawString(x + 9, y + h - 13, label[:34])

        value_font = 13.5
        if len(value) > 14:
            value_font = 11.5

        pdf.setFillColor(text)
        pdf.setFont("Helvetica-Bold", value_font)
        pdf.drawString(x + 9, y + h - 31, value[:28])

        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 5.9)
        note_lines = wrap_text(note, max_chars=38, max_lines=2)

        if len(note_lines) == 1:
            pdf.drawString(x + 9, y + 8, note_lines[0])
        else:
            pdf.drawString(x + 9, y + 12, note_lines[0])
            pdf.drawString(x + 9, y + 5, note_lines[1])

    def wrap_text(
        value: str,
        *,
        max_chars: int,
        max_lines: int = 2,
    ) -> list[str]:
        words = str(value).split()
        if not words:
            return [""]

        lines: list[str] = []
        current = ""

        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word

                if len(lines) >= max_lines - 1:
                    break

        if current and len(lines) < max_lines:
            lines.append(current)

        if len(lines) > max_lines:
            lines = lines[:max_lines]

        return lines or [""]


    def panel_title(
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        note: str,
    ) -> None:
        pdf.setFillColor(text)
        pdf.setFont("Helvetica-Bold", 8.5)
        pdf.drawString(x + 10, y + h - 14, title)
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 6.3)
        pdf.drawString(x + 10, y + h - 25, note[:68])

    def draw_line_chart(
        x: float,
        y: float,
        w: float,
        h: float,
        data: list[tuple[str, int]],
    ) -> None:
        rounded_card(x, y, w, h)
        panel_title(
            x, y, w, h,
            "Trend Gangguan Harian",
            "Jumlah gangguan per hari pada periode terpilih.",
        )

        chart_x = x + 30
        chart_y = y + 24
        chart_w = w - 42
        chart_h = h - 58

        pdf.setStrokeColor(grid)
        pdf.setLineWidth(0.4)
        for step in range(4):
            gy = chart_y + (chart_h * step / 3)
            pdf.line(chart_x, gy, chart_x + chart_w, gy)

        if not data:
            pdf.setFillColor(muted)
            pdf.setFont("Helvetica", 7)
            pdf.drawCentredString(
                chart_x + chart_w / 2,
                chart_y + chart_h / 2,
                "Belum ada data",
            )
            return

        values = [max(0, int(v)) for _, v in data]
        max_v = max(max(values), 1)
        count = len(data)
        step_x = chart_w / max(count - 1, 1)

        points: list[tuple[float, float]] = []
        for idx, (_, value) in enumerate(data):
            px = chart_x + idx * step_x
            py = chart_y + (value / max_v) * chart_h
            points.append((px, py))

        pdf.setStrokeColor(accent)
        pdf.setLineWidth(1.6)
        for idx in range(len(points) - 1):
            pdf.line(
                points[idx][0],
                points[idx][1],
                points[idx + 1][0],
                points[idx + 1][1],
            )

        pdf.setFillColor(accent)
        for px, py in points:
            pdf.circle(px, py, 1.8, fill=1, stroke=0)

        # Sparse date labels to avoid crowding.
        label_every = max(1, count // 6)
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 5.8)
        for idx, (label, _) in enumerate(data):
            if idx % label_every == 0 or idx == count - 1:
                px = chart_x + idx * step_x
                pdf.drawCentredString(px, chart_y - 10, label[:6])

    def draw_donut(
        x: float,
        y: float,
        w: float,
        h: float,
        data: list[tuple[str, int]],
    ) -> None:
        rounded_card(x, y, w, h)
        panel_title(
            x, y, w, h,
            "Komposisi Penyebab",
            "Proporsi penyebab gangguan.",
        )

        total = sum(max(0, int(v)) for _, v in data)
        if total <= 0:
            pdf.setFillColor(muted)
            pdf.setFont("Helvetica", 7)
            pdf.drawCentredString(
                x + w / 2,
                y + h / 2,
                "Belum ada data",
            )
            return

        cx = x + 68
        cy = y + (h - 18) / 2
        radius = min(36, h * 0.27)
        inner = radius * 0.55

        palette = [
            colors.HexColor("#2563EB"),
            colors.HexColor("#0EA5E9"),
            colors.HexColor("#14B8A6"),
            colors.HexColor("#F59E0B"),
            colors.HexColor("#EF4444"),
            colors.HexColor("#8B5CF6"),
        ]

        start_angle = 90.0
        for idx, (_, value) in enumerate(data[:6]):
            extent = (max(0, int(value)) / total) * 360
            pdf.setFillColor(palette[idx % len(palette)])
            pdf.wedge(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                start_angle,
                extent,
                fill=1,
                stroke=0,
            )
            start_angle += extent

        pdf.setFillColor(card)
        pdf.circle(cx, cy, inner, fill=1, stroke=0)
        pdf.setFillColor(text)
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawCentredString(cx, cy + 1, str(total))
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 5.8)
        pdf.drawCentredString(cx, cy - 9, "gangguan")

        legend_x = x + 118
        legend_y = y + h - 48
        pdf.setFont("Helvetica", 6.1)
        for idx, (label, value) in enumerate(data[:5]):
            ly = legend_y - idx * 15
            pdf.setFillColor(palette[idx % len(palette)])
            pdf.roundRect(
                legend_x,
                ly - 2,
                6,
                6,
                2,
                fill=1,
                stroke=0,
            )
            pdf.setFillColor(text)
            pdf.drawString(
                legend_x + 10,
                ly - 1,
                f"{label[:22]} ({value})",
            )

    def draw_horizontal_bars(
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        title: str,
        note: str,
        data: list[tuple[str, float]],
        value_suffix: str = "",
    ) -> None:
        rounded_card(x, y, w, h)
        panel_title(x, y, w, h, title, note)

        items = data[:6]
        if not items:
            pdf.setFillColor(muted)
            pdf.setFont("Helvetica", 7)
            pdf.drawCentredString(
                x + w / 2,
                y + h / 2,
                "Belum ada data",
            )
            return

        max_value = max(max(float(v), 0.0) for _, v in items)
        max_value = max(max_value, 1.0)

        label_w = 82
        bar_x = x + label_w + 12
        bar_w = w - label_w - 36
        base_y = y + h - 47
        gap = max(13, (h - 58) / max(len(items), 1))

        for idx, (label, value) in enumerate(items):
            row_y = base_y - idx * gap

            pdf.setFillColor(text)
            pdf.setFont("Helvetica", 6.1)
            label_lines = wrap_text(label, max_chars=24, max_lines=2)
            if len(label_lines) == 1:
                pdf.drawRightString(
                    bar_x - 6,
                    row_y,
                    label_lines[0],
                )
            else:
                pdf.drawRightString(
                    bar_x - 6,
                    row_y + 3,
                    label_lines[0],
                )
                pdf.setFont("Helvetica", 5.7)
                pdf.drawRightString(
                    bar_x - 6,
                    row_y - 4,
                    label_lines[1],
                )

            pdf.setFillColor(colors.HexColor("#E5E7EB"))
            pdf.roundRect(
                bar_x,
                row_y - 2,
                bar_w,
                6,
                2,
                fill=1,
                stroke=0,
            )

            fill_w = bar_w * max(float(value), 0.0) / max_value
            pdf.setFillColor(accent_2)
            pdf.roundRect(
                bar_x,
                row_y - 2,
                fill_w,
                6,
                2,
                fill=1,
                stroke=0,
            )

            pdf.setFillColor(muted)
            pdf.setFont("Helvetica", 5.8)
            if value_suffix:
                value_text = f"{float(value):.2f}{value_suffix}"
            elif float(value).is_integer():
                value_text = f"{int(value)}"
            else:
                value_text = f"{float(value):.1f}"
            pdf.drawString(
                bar_x + bar_w + 4,
                row_y,
                value_text,
            )

    # ---- KPI rows ----
    kpi_top = top - 43
    gap = 8
    kpi_w = (page_width - 2 * margin_x - 3 * gap) / 4
    kpi_h = 47

    primary = [
        ("Gangguan", f"{current_events}", "Total kejadian"),
        ("ENS", f"{current_ens:,.1f} kWh", "Energy Not Supplied"),
        (
            "Rata-rata Pemulihan",
            f"{current_recovery:,.1f} min",
            "Durasi padam pelanggan",
        ),
        ("Kejadian Aktif", f"{active_events}", "Perlu monitoring"),
    ]

    for idx, item in enumerate(primary):
        draw_kpi(
            margin_x + idx * (kpi_w + gap),
            kpi_top - kpi_h,
            kpi_w,
            kpi_h,
            *item,
        )

    secondary_h = 44
    secondary_y = kpi_top - kpi_h - gap - secondary_h
    secondary = [
        ("Penyulang Terdampak", f"{affected_feeders}", "Penyulang unik"),
        (
            "Max Fault Current",
            f"{max_fault_current:,.0f} A",
            "Arus gangguan tertinggi",
        ),
        (
            "Max Fault Multiple",
            f"{max_fault_multiple:.2f} x In",
            "Paparan terhadap In",
        ),
        (
            "Data Completeness",
            f"{completeness_pct:.1f}%",
            f"Report {report_period_label}: {report_compliance_pct:.1f}%",
        ),
    ]

    for idx, item in enumerate(secondary):
        draw_kpi(
            margin_x + idx * (kpi_w + gap),
            secondary_y,
            kpi_w,
            secondary_h,
            *item,
        )

    # ---- Charts area ----
    charts_top = secondary_y - 10
    panel_gap = 10
    panel_w = (page_width - 2 * margin_x - panel_gap) / 2
    panel_h = 118

    draw_line_chart(
        margin_x,
        charts_top - panel_h,
        panel_w,
        panel_h,
        daily_trend,
    )
    draw_donut(
        margin_x + panel_w + panel_gap,
        charts_top - panel_h,
        panel_w,
        panel_h,
        cause_data,
    )

    second_row_y = charts_top - panel_h - panel_gap - panel_h

    draw_horizontal_bars(
        margin_x,
        second_row_y,
        panel_w,
        panel_h,
        title="Top Recurring Feeder",
        note="Penyulang dengan frekuensi gangguan tertinggi.",
        data=[
            (label, float(value))
            for label, value in feeder_data
        ],
    )
    draw_horizontal_bars(
        margin_x + panel_w + panel_gap,
        second_row_y,
        panel_w,
        panel_h,
        title="Transformer Fault Exposure",
        note="Top Trafo berdasarkan fault multiple.",
        data=transformer_data,
        value_suffix=" x In",
    )

    # ---- Bottom insights: narrative + management attention ----
    bottom_y = 22
    bottom_h = max(second_row_y - bottom_y - 8, 74)
    bottom_gap = 10
    left_bottom_w = (page_width - 2 * margin_x - bottom_gap) * 0.58
    right_bottom_w = (
        page_width - 2 * margin_x - bottom_gap - left_bottom_w
    )

    # Executive Narrative
    rounded_card(
        margin_x,
        bottom_y,
        left_bottom_w,
        bottom_h,
        fill_color=card,
        stroke_color=border,
    )

    pdf.setFillColor(text)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(
        margin_x + 10,
        bottom_y + bottom_h - 13,
        "Executive Narrative",
    )

    narrative_y = bottom_y + bottom_h - 27
    narrative_to_show = narrative_items[:4]

    if not narrative_to_show:
        narrative_to_show = [
            "Belum ada narasi eksekutif pada periode terpilih."
        ]

    for idx, item in enumerate(narrative_to_show, start=1):
        lines = wrap_text(item, max_chars=72, max_lines=2)
        pdf.setFillColor(text)
        pdf.setFont("Helvetica-Bold", 5.8)
        pdf.drawString(
            margin_x + 11,
            narrative_y,
            f"{idx}.",
        )

        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 5.7)
        pdf.drawString(
            margin_x + 21,
            narrative_y,
            lines[0],
        )
        if len(lines) > 1:
            pdf.drawString(
                margin_x + 21,
                narrative_y - 7,
                lines[1],
            )

        narrative_y -= 17

    # Management Attention
    attention_x = margin_x + left_bottom_w + bottom_gap

    rounded_card(
        attention_x,
        bottom_y,
        right_bottom_w,
        bottom_h,
        fill_color=alert_bg,
        stroke_color=alert_border,
    )

    pdf.setFillColor(text)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(
        attention_x + 10,
        bottom_y + bottom_h - 13,
        "Management Attention",
    )

    notes = attention_items[:3]
    if not notes:
        notes = [
            (
                "Kondisi Terkendali",
                "Tidak ada perhatian utama pada periode terpilih.",
            )
        ]

    note_y = bottom_y + bottom_h - 29

    for idx, (title, message) in enumerate(notes):
        pdf.setFillColor(text)
        pdf.setFont("Helvetica-Bold", 6.1)
        pdf.drawString(
            attention_x + 10,
            note_y,
            title[:31],
        )

        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 5.6)
        msg_lines = wrap_text(
            message,
            max_chars=52,
            max_lines=2,
        )
        pdf.drawString(
            attention_x + 10,
            note_y - 8,
            msg_lines[0],
        )
        if len(msg_lines) > 1:
            pdf.drawString(
                attention_x + 10,
                note_y - 15,
                msg_lines[1],
            )

        note_y -= 24

    # ---- Footer ----
    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 5.8)
    pdf.drawRightString(
        page_width - margin_x,
        8,
        "Dashboard Gangguan Penyulang 20 kV",
    )

    pdf.showPage()
    pdf.save()

    buffer.seek(0)
    return buffer.getvalue()



def _render_executive_tab(
    start_date: date,
    end_date: date,
    ultg_flc: str | None,
    gi_flc: str | None,
    bay_flc: str | None,
    penyulang_id: str | None,
) -> None:
    st.subheader("Executive Summary")
    st.caption(
        "Ringkasan kondisi operasional dan reliability pada periode serta scope terpilih."
    )

    period_days = max((end_date - start_date).days + 1, 1)
    previous_end = start_date.fromordinal(start_date.toordinal() - 1)
    previous_start = previous_end.fromordinal(
        previous_end.toordinal() - period_days + 1
    )

    try:
        current_reliability = _load_reliability_events(
            start_date,
            end_date,
            ultg_flc,
            gi_flc,
            bay_flc,
            penyulang_id,
        )
        previous_reliability = _load_reliability_events(
            previous_start,
            previous_end,
            ultg_flc,
            gi_flc,
            bay_flc,
            penyulang_id,
        )
        operations = _load_operations_events(
            start_date,
            end_date,
            ultg_flc,
            gi_flc,
            bay_flc,
            penyulang_id,
        )
        exposure = _load_transformer_exposure(
            start_date,
            end_date,
            ultg_flc,
            gi_flc,
            bay_flc,
            penyulang_id,
        )
        governance = _load_governance(
            start_date,
            end_date,
            ultg_flc,
            gi_flc,
            bay_flc,
            penyulang_id,
        )
    except Exception as exc:
        st.error(f"Executive Summary tidak dapat dimuat: {exc}")
        return

    current_df = pd.DataFrame(current_reliability)
    previous_df = pd.DataFrame(previous_reliability)
    operations_df = pd.DataFrame(operations)

    def _sum_numeric(frame: pd.DataFrame, column: str) -> float:
        if frame.empty or column not in frame.columns:
            return 0.0
        return float(
            pd.to_numeric(
                frame[column],
                errors="coerce",
            ).fillna(0).sum()
        )

    def _mean_numeric(frame: pd.DataFrame, column: str) -> float:
        if frame.empty or column not in frame.columns:
            return 0.0
        series = pd.to_numeric(
            frame[column],
            errors="coerce",
        ).dropna()
        return float(series.mean()) if not series.empty else 0.0

    current_events = len(current_df)
    previous_events = len(previous_df)
    current_ens = _sum_numeric(current_df, "ens_kwh")
    previous_ens = _sum_numeric(previous_df, "ens_kwh")
    current_recovery = _mean_numeric(
        current_df,
        "customer_outage_duration_min",
    )
    previous_recovery = _mean_numeric(
        previous_df,
        "customer_outage_duration_min",
    )

    affected_feeders = (
        int(current_df["penyulang_id"].nunique())
        if not current_df.empty and "penyulang_id" in current_df.columns
        else 0
    )

    active_events = 0
    if not operations_df.empty and "record_status" in operations_df.columns:
        active_events = int(
            operations_df["record_status"]
            .astype(str)
            .str.upper()
            .eq("ONGOING")
            .sum()
        )

    completeness_raw = governance.get("completeness", {})
    reports_raw = governance.get("reports", {})
    completeness = (
        completeness_raw if isinstance(completeness_raw, dict) else {}
    )
    reports = reports_raw if isinstance(reports_raw, dict) else {}

    completeness_pct = _safe_float(
        completeness.get("core_completeness_percent")
    )
    report_compliance_pct = _safe_float(
        reports.get("verification_percent")
    )
    report_period_label = _month_label(
        reports.get("report_period_year"),
        reports.get("report_period_month"),
    )

    exposure_with_events = [
        row
        for row in exposure
        if _safe_int(row.get("event_count")) > 0
    ]

    max_fault_multiple = 0.0
    max_fault_current = 0.0
    max_fault_transformer = "-"

    if exposure_with_events:
        max_multiple_row = max(
            exposure_with_events,
            key=lambda row: _safe_float(row.get("max_fault_multiple")),
        )
        max_fault_multiple = _safe_float(
            max_multiple_row.get("max_fault_multiple")
        )
        max_fault_transformer = str(
            max_multiple_row.get("transformer_bay_name") or "-"
        )

        max_current_row = max(
            exposure_with_events,
            key=lambda row: _safe_float(row.get("max_fault_current_a")),
        )
        max_fault_current = _safe_float(
            max_current_row.get("max_fault_current_a")
        )

    # ===== PRIMARY KPI =====
    primary_kpis = [
        ("Gangguan", f"{current_events}", "Total kejadian pada periode"),
        ("ENS", f"{current_ens:,.1f} kWh", "Energy Not Supplied"),
        (
            "Rata-rata Pemulihan",
            f"{current_recovery:,.1f} min",
            "Durasi padam pelanggan",
        ),
        ("Kejadian Aktif", f"{active_events}", "Masih membutuhkan monitoring"),
    ]

    primary_html = "".join(
        (
            '<div class="clean-kpi">'
            f'<div class="clean-kpi-label">{_html_escape(label)}</div>'
            f'<div class="clean-kpi-value">{_html_escape(value)}</div>'
            f'<div class="clean-kpi-note">{_html_escape(note)}</div>'
            '</div>'
        )
        for label, value, note in primary_kpis
    )
    st.markdown(
        f'<div class="clean-kpi-grid">{primary_html}</div>',
        unsafe_allow_html=True,
    )

    # ===== SECONDARY KPI =====
    secondary_kpis = [
        ("Penyulang Terdampak", f"{affected_feeders}"),
        ("Max Fault Current", f"{max_fault_current:,.0f} A"),
        ("Max Fault Multiple", f"{max_fault_multiple:.2f} × In"),
        ("Data Completeness", f"{completeness_pct:.1f}%"),
    ]

    secondary_html = "".join(
        (
            '<div class="clean-secondary">'
            f'<div class="clean-secondary-label">{_html_escape(label)}</div>'
            f'<div class="clean-secondary-value">{_html_escape(value)}</div>'
            '</div>'
        )
        for label, value in secondary_kpis
    )
    st.markdown(
        f'<div class="clean-secondary-grid">{secondary_html}</div>',
        unsafe_allow_html=True,
    )

    # ===== ROW 1: DAILY TREND + CAUSE =====
    left, right = st.columns([1.35, 0.65])

    with left:
        _section_header(
            "Trend Gangguan Harian",
            kicker="Executive",
            note="Jumlah gangguan per hari dari tanggal mulai sampai tanggal akhir.",
        )

        full_days = pd.date_range(
            start=pd.Timestamp(start_date),
            end=pd.Timestamp(end_date),
            freq="D",
        )

        if not current_df.empty and "event_date" in current_df.columns:
            trend_df = current_df.copy()
            trend_df["event_date"] = pd.to_datetime(
                trend_df["event_date"],
                errors="coerce",
            ).dt.normalize()
            trend_df = trend_df.dropna(subset=["event_date"])
            daily_counts = (
                trend_df.groupby("event_date")
                .size()
                .reindex(full_days, fill_value=0)
            )
        else:
            daily_counts = pd.Series(
                [0] * len(full_days),
                index=full_days,
                dtype="int64",
            )

        trend_chart = pd.DataFrame(
            {
                "Tanggal": [item.strftime("%d %b") for item in full_days],
                "Gangguan": daily_counts.astype(int).tolist(),
            }
        )

        fig = px.line(
            trend_chart,
            x="Tanggal",
            y="Gangguan",
            markers=True,
        )
        fig.update_layout(
            height=285,
            margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
            xaxis_title=None,
            yaxis_title=None,
            font=dict(size=11),
        )
        fig.update_yaxes(
            rangemode="tozero",
            gridcolor="rgba(128,128,128,.12)",
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False},
        )

    with right:
        _section_header(
            "Komposisi Penyebab",
            kicker="Executive",
            note="Proporsi penyebab gangguan.",
        )

        if not current_df.empty and "cause_name" in current_df.columns:
            cause_chart_df = (
                current_df["cause_name"]
                .fillna("Belum Ditentukan")
                .replace("", "Belum Ditentukan")
                .value_counts()
                .rename_axis("Penyebab")
                .reset_index(name="Gangguan")
            )

            fig = px.pie(
                cause_chart_df,
                names="Penyebab",
                values="Gangguan",
                hole=0.58,
            )
            fig.update_traces(
                textinfo="percent",
                textposition="inside",
            )
            fig.update_layout(
                height=285,
                margin=dict(l=5, r=5, t=10, b=45),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                legend=dict(
                    orientation="h",
                    yanchor="top",
                    y=-0.05,
                    xanchor="center",
                    x=0.5,
                    font=dict(size=9),
                ),
                font=dict(size=10),
            )
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False},
            )
        else:
            st.info("Belum ada data penyebab.")

    # ===== ROW 2: FEEDER + TRANSFORMER =====
    left2, right2 = st.columns(2)

    with left2:
        _section_header(
            "Top Recurring Feeder",
            kicker="Reliability",
            note="Penyulang dengan frekuensi gangguan tertinggi.",
        )

        if not current_df.empty and "penyulang_name" in current_df.columns:
            feeder_chart_df = (
                current_df["penyulang_name"]
                .fillna("-")
                .value_counts()
                .head(6)
                .rename_axis("Penyulang")
                .reset_index(name="Gangguan")
                .sort_values("Gangguan", ascending=True)
            )

            fig = px.bar(
                feeder_chart_df,
                x="Gangguan",
                y="Penyulang",
                orientation="h",
                text="Gangguan",
            )
            fig.update_traces(
                textposition="outside",
                cliponaxis=False,
            )
            fig.update_layout(
                height=275,
                margin=dict(l=10, r=20, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                xaxis_title=None,
                yaxis_title=None,
                font=dict(size=10),
            )
            fig.update_xaxes(
                rangemode="tozero",
                gridcolor="rgba(128,128,128,.12)",
            )
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False},
            )
        else:
            st.info("Belum ada data feeder.")

    with right2:
        _section_header(
            "Transformer Fault Exposure",
            kicker="Analisa",
            note="Top Trafo berdasarkan fault multiple.",
        )

        exposure_chart_rows = [
            row
            for row in exposure_with_events
            if _safe_float(row.get("max_fault_multiple")) > 0
        ]

        if exposure_chart_rows:
            exposure_chart_df = pd.DataFrame(
                [
                    {
                        "Trafo": str(
                            row.get("transformer_bay_name")
                            or row.get("techidentno")
                            or "-"
                        ),
                        "Fault Multiple": _safe_float(
                            row.get("max_fault_multiple")
                        ),
                    }
                    for row in exposure_chart_rows
                ]
            ).sort_values(
                "Fault Multiple",
                ascending=True,
            ).tail(6)

            fig = px.bar(
                exposure_chart_df,
                x="Fault Multiple",
                y="Trafo",
                orientation="h",
                text=exposure_chart_df["Fault Multiple"].map(
                    lambda x: f"{x:.2f} × In"
                ),
            )
            fig.update_traces(
                textposition="outside",
                cliponaxis=False,
            )
            fig.update_layout(
                height=275,
                margin=dict(l=10, r=20, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                xaxis_title="× In",
                yaxis_title=None,
                font=dict(size=10),
            )
            fig.update_xaxes(
                rangemode="tozero",
                gridcolor="rgba(128,128,128,.12)",
            )
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False},
            )
        else:
            st.info("Belum ada data fault exposure Trafo.")

    top_feeder = "-"
    top_feeder_count = 0
    if not current_df.empty and "penyulang_name" in current_df.columns:
        feeder_counts = current_df["penyulang_name"].fillna("-").value_counts()
        if not feeder_counts.empty:
            top_feeder = str(feeder_counts.index[0])
            top_feeder_count = int(feeder_counts.iloc[0])

    narrative_items = _build_executive_narrative(
        current_events=current_events,
        previous_events=previous_events,
        current_ens=current_ens,
        previous_ens=previous_ens,
        current_recovery=current_recovery,
        previous_recovery=previous_recovery,
        active_events=active_events,
        top_feeder=top_feeder,
        top_feeder_count=top_feeder_count,
        max_fault_current=max_fault_current,
        max_fault_multiple=max_fault_multiple,
        max_fault_transformer=max_fault_transformer,
        completeness_pct=completeness_pct,
        report_period_label=report_period_label,
        report_compliance_pct=report_compliance_pct,
    )

    _section_header(
        "Executive Narrative",
        kicker="Executive",
        note="Kesimpulan otomatis berdasarkan indikator pada periode dan scope terpilih.",
    )

    narrative_html = "".join(
        f"<li>{_html_escape(item)}</li>"
        for item in narrative_items
    )
    st.markdown(
        (
            '<div class="exec-narrative">'
            '<div class="exec-narrative-title">Ringkasan Manajemen</div>'
            f'<ul class="exec-narrative-list">{narrative_html}</ul>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )

    # ===== MANAGEMENT ATTENTION =====
    _section_header(
        "Management Attention",
        kicker="Executive",
        note="Prioritas tindak lanjut pada periode terpilih.",
    )

    attention_items: list[tuple[str, str]] = []
    incomplete = _safe_int(completeness.get("gangguan_incomplete"))
    no_fault = _safe_int(
        completeness.get("gangguan_without_fault_current")
    )

    if active_events > 0:
        attention_items.append(
            ("Kejadian Aktif", f"{active_events} kejadian masih aktif.")
        )
    if incomplete > 0:
        attention_items.append(
            ("Data Belum Lengkap", f"{incomplete} gangguan perlu dilengkapi.")
        )
    if no_fault > 0:
        attention_items.append(
            (
                "Arus Gangguan",
                f"{no_fault} gangguan belum memiliki data arus gangguan.",
            )
        )
    if report_compliance_pct < 100:
        attention_items.append(
            (
                f"Laporan {report_period_label}",
                f"Compliance saat ini {report_compliance_pct:.1f}%.",
            )
        )
    if max_fault_multiple >= 10:
        attention_items.append(
            (
                "Transformer Exposure",
                f"{max_fault_transformer}: {max_fault_multiple:.2f} × In.",
            )
        )

    if not attention_items:
        attention_items = [
            ("Kondisi Terkendali", "Tidak ada perhatian utama pada periode ini.")
        ]

    attention_html = "".join(
        (
            '<div class="clean-attention-card">'
            f'<div class="clean-attention-title">{_html_escape(title)}</div>'
            f'<div class="clean-attention-text">{_html_escape(text)}</div>'
            '</div>'
        )
        for title, text in attention_items[:3]
    )

    st.markdown(
        f'<div class="clean-attention-grid">{attention_html}</div>',
        unsafe_allow_html=True,
    )


    # ===== EXECUTIVE PDF EXPORT =====
    scope_labels = [
        (
            "Semua ULTG dalam Scope"
            if ultg_flc is None
            else str(ultg_flc)
        ),
        (
            "Semua GI"
            if gi_flc is None
            else str(gi_flc)
        ),
        (
            "Semua Bay"
            if bay_flc is None
            else str(bay_flc)
        ),
        (
            "Semua Penyulang"
            if penyulang_id is None
            else str(penyulang_id)
        ),
    ]

    # Dataset yang sama dengan visual dashboard untuk PDF.
    full_days_pdf = pd.date_range(
        start=pd.Timestamp(start_date),
        end=pd.Timestamp(end_date),
        freq="D",
    )
    if not current_df.empty and "event_date" in current_df.columns:
        pdf_trend_df = current_df.copy()
        pdf_trend_df["event_date"] = pd.to_datetime(
            pdf_trend_df["event_date"],
            errors="coerce",
        ).dt.normalize()
        pdf_trend_df = pdf_trend_df.dropna(subset=["event_date"])
        pdf_daily_counts = (
            pdf_trend_df.groupby("event_date")
            .size()
            .reindex(full_days_pdf, fill_value=0)
        )
    else:
        pdf_daily_counts = pd.Series(
            [0] * len(full_days_pdf),
            index=full_days_pdf,
            dtype="int64",
        )

    daily_trend_pdf = [
        (day.strftime("%d %b"), int(pdf_daily_counts.loc[day]))
        for day in full_days_pdf
    ]

    if not current_df.empty and "cause_name" in current_df.columns:
        cause_pdf_series = (
            current_df["cause_name"]
            .fillna("Belum Ditentukan")
            .replace("", "Belum Ditentukan")
            .value_counts()
            .head(6)
        )
        cause_data_pdf = [
            (str(label), int(value))
            for label, value in cause_pdf_series.items()
        ]
    else:
        cause_data_pdf = []

    if not current_df.empty and "penyulang_name" in current_df.columns:
        feeder_pdf_series = (
            current_df["penyulang_name"]
            .fillna("-")
            .value_counts()
            .head(6)
        )
        feeder_data_pdf = [
            (str(label), int(value))
            for label, value in feeder_pdf_series.items()
        ]
    else:
        feeder_data_pdf = []

    transformer_data_pdf = [
        (
            str(
                row.get("transformer_bay_name")
                or row.get("techidentno")
                or "-"
            ),
            _safe_float(row.get("max_fault_multiple")),
        )
        for row in sorted(
            exposure_with_events,
            key=lambda row: _safe_float(
                row.get("max_fault_multiple")
            ),
            reverse=True,
        )
        if _safe_float(row.get("max_fault_multiple")) > 0
    ][:6]

    pdf_bytes = _build_executive_pdf(
        start_date=start_date,
        end_date=end_date,
        scope_labels=scope_labels,
        current_events=current_events,
        current_ens=current_ens,
        current_recovery=current_recovery,
        affected_feeders=affected_feeders,
        active_events=active_events,
        max_fault_current=max_fault_current,
        max_fault_multiple=max_fault_multiple,
        completeness_pct=completeness_pct,
        report_period_label=report_period_label,
        report_compliance_pct=report_compliance_pct,
        daily_trend=daily_trend_pdf,
        cause_data=cause_data_pdf,
        feeder_data=feeder_data_pdf,
        transformer_data=transformer_data_pdf,
        narrative_items=narrative_items,
        attention_items=attention_items,
    )


    export_col, _ = st.columns([0.22, 0.78])
    with export_col:
        st.download_button(
            "Download Dashboard PDF",
            data=pdf_bytes,
            file_name=(
                "dashboard_executive_"
                f"{start_date:%Y%m%d}_{end_date:%Y%m%d}.pdf"
            ),
            mime="application/pdf",
            use_container_width=True,
            key="download_executive_pdf",
        )

def _render_reliability_tab(
    start_date: date,
    end_date: date,
    ultg_flc: str | None,
    gi_flc: str | None,
    bay_flc: str | None,
    penyulang_id: str | None,
) -> None:
    st.subheader("Reliability Performance")
    st.caption(
        "Frekuensi gangguan, ENS, kecepatan pemulihan, recurring feeder, "
        "dan distribusi penyebab pada periode terpilih."
    )

    try:
        rows = _load_reliability_events(
            start_date,
            end_date,
            ultg_flc,
            gi_flc,
            bay_flc,
            penyulang_id,
        )
    except Exception as exc:
        st.error(f"Data reliability tidak dapat dimuat: {exc}")
        return

    if not rows:
        st.info("Belum ada data gangguan pada periode yang dipilih.")
        return

    df = pd.DataFrame(rows)

    for column in [
        "customer_outage_duration_min",
        "outage_duration_min",
        "ens_kwh",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    total_events = len(df)
    affected_feeders = (
        int(df["penyulang_id"].nunique())
        if "penyulang_id" in df.columns
        else 0
    )
    total_ens = (
        float(df["ens_kwh"].fillna(0).sum())
        if "ens_kwh" in df.columns
        else 0.0
    )
    duration_series = (
        df["customer_outage_duration_min"].dropna()
        if "customer_outage_duration_min" in df.columns
        else pd.Series(dtype="float64")
    )
    avg_recovery = float(duration_series.mean()) if not duration_series.empty else 0.0
    median_recovery = float(duration_series.median()) if not duration_series.empty else 0.0
    max_recovery = float(duration_series.max()) if not duration_series.empty else 0.0

    recurring_count = 0
    top_feeder = "-"
    top_feeder_count = 0
    if "penyulang_name" in df.columns:
        feeder_counts = df["penyulang_name"].fillna("-").value_counts()
        if not feeder_counts.empty:
            recurring_count = int((feeder_counts >= 2).sum())
            top_feeder = str(feeder_counts.index[0])
            top_feeder_count = int(feeder_counts.iloc[0])

    top_cause = "-"
    top_cause_count = 0
    if "cause_name" in df.columns:
        cause_counts = (
            df["cause_name"]
            .fillna("Belum Ditentukan")
            .replace("", "Belum Ditentukan")
            .value_counts()
        )
        if not cause_counts.empty:
            top_cause = str(cause_counts.index[0])
            top_cause_count = int(cause_counts.iloc[0])

    rel_cards = [
        ("Total Gangguan", f"{total_events}", "Jumlah kejadian dalam periode"),
        ("Penyulang Terdampak", f"{affected_feeders}", "Penyulang unik terdampak"),
        ("ENS", f"{total_ens:,.1f} kWh", "Energy Not Supplied"),
        ("Rata-rata Pemulihan", f"{avg_recovery:,.1f} min", "Durasi padam pelanggan"),
    ]
    rel_html = "".join(
        '<div class="rel-card">'
        f'<div class="rel-card-label">{_html_escape(label)}</div>'
        f'<div class="rel-card-value">{_html_escape(value)}</div>'
        f'<div class="rel-card-meta">{_html_escape(meta)}</div>'
        '</div>'
        for label, value, meta in rel_cards
    )
    st.markdown(f'<div class="rel-grid">{rel_html}</div>', unsafe_allow_html=True)

    insight_items = [
        (
            "Recurring Feeder",
            f"{recurring_count} penyulang",
            f"Penyulang dominan: {top_feeder} ({top_feeder_count} kejadian)",
        ),
        (
            "Penyebab Dominan",
            top_cause,
            f"{top_cause_count} kejadian pada periode terpilih",
        ),
        (
            "Recovery Profile",
            f"Median {median_recovery:,.1f} min",
            f"Durasi terlama {max_recovery:,.1f} menit",
        ),
    ]
    insight_html = "".join(
        '<div class="rel-insight">'
        f'<div class="rel-insight-kicker">{_html_escape(kicker)}</div>'
        f'<div class="rel-insight-value">{_html_escape(value)}</div>'
        f'<div class="rel-insight-note">{_html_escape(note)}</div>'
        '</div>'
        for kicker, value, note in insight_items
    )
    st.markdown(
        f'<div class="rel-insight-grid">{insight_html}</div>',
        unsafe_allow_html=True,
    )

    _section_header(
        "Recovery SLA",
        kicker="Reliability",
        note="Distribusi waktu pemulihan pelanggan pada periode terpilih.",
    )

    sla_total = int(duration_series.count())
    sla_values = [
        ("≤ 5 menit", int((duration_series <= 5).sum()) if sla_total else 0),
        (
            "6–10 menit",
            int(((duration_series > 5) & (duration_series <= 10)).sum())
            if sla_total else 0,
        ),
        (
            "11–30 menit",
            int(((duration_series > 10) & (duration_series <= 30)).sum())
            if sla_total else 0,
        ),
        (
            "31–60 menit",
            int(((duration_series > 30) & (duration_series <= 60)).sum())
            if sla_total else 0,
        ),
        ("> 60 menit", int((duration_series > 60).sum()) if sla_total else 0),
    ]
    sla_html = "".join(
        '<div class="rel-sla-card">'
        f'<div class="rel-sla-label">{_html_escape(label)}</div>'
        f'<div class="rel-sla-value">{value}</div>'
        '</div>'
        for label, value in sla_values
    )
    st.markdown(
        f'<div class="rel-sla-grid">{sla_html}</div>',
        unsafe_allow_html=True,
    )

    trend_df = df.copy()
    trend_df["event_date"] = pd.to_datetime(
        trend_df["event_date"],
        errors="coerce",
    ).dt.normalize()
    trend_df = trend_df.dropna(subset=["event_date"])

    full_days = pd.date_range(
        start=pd.Timestamp(start_date),
        end=pd.Timestamp(end_date),
        freq="D",
    )

    chart_left, chart_right = st.columns([1.15, 0.85])

    with chart_left:
        _section_header(
            "Trend Gangguan Harian",
            kicker="Reliability",
            note="Jumlah gangguan per hari dari tanggal mulai sampai tanggal akhir.",
        )

        daily_counts = (
            trend_df.groupby("event_date")
            .size()
            .reindex(full_days, fill_value=0)
        )
        trend = pd.DataFrame(
            {
                "Tanggal": [item.strftime("%d %b") for item in full_days],
                "Gangguan": daily_counts.astype(int).tolist(),
            }
        ).set_index("Tanggal")

        st.line_chart(trend, use_container_width=True, height=285)

    with chart_right:
        _section_header(
            "ENS Harian",
            kicker="Reliability",
            note="Distribusi Energy Not Supplied per hari.",
        )

        if "ens_kwh" in trend_df.columns:
            daily_ens = (
                trend_df.groupby("event_date")["ens_kwh"]
                .sum()
                .reindex(full_days, fill_value=0)
            )
            ens_chart = pd.DataFrame(
                {
                    "Tanggal": [item.strftime("%d %b") for item in full_days],
                    "ENS (kWh)": daily_ens.tolist(),
                }
            ).set_index("Tanggal")
            st.bar_chart(ens_chart, use_container_width=True, height=285)
        else:
            st.info("Belum ada data ENS pada periode ini.")

    lower_left, lower_right = st.columns(2)

    with lower_left:
        _section_header(
            "Recurring Feeder",
            kicker="Reliability",
            note="Penyulang dengan gangguan berulang pada periode terpilih.",
        )

        feeder_freq = (
            df.groupby("penyulang_name", dropna=False)
            .size()
            .reset_index(name="Gangguan")
            .sort_values(
                ["Gangguan", "penyulang_name"],
                ascending=[False, True],
            )
        )
        recurring = feeder_freq[feeder_freq["Gangguan"] >= 2].copy()

        if recurring.empty:
            st.success("Tidak ada penyulang dengan ≥ 2 gangguan pada periode yang dipilih.")
        else:
            st.dataframe(
                recurring.rename(columns={"penyulang_name": "Penyulang"}),
                use_container_width=True,
                hide_index=True,
                height=275,
            )

    with lower_right:
        _section_header(
            "Pareto Penyebab Gangguan",
            kicker="Reliability",
            note="Penyebab dengan kontribusi kejadian terbesar.",
        )

        cause_series = (
            df["cause_name"]
            .fillna("Belum Ditentukan")
            .replace("", "Belum Ditentukan")
        )
        cause_df = (
            cause_series.value_counts()
            .rename_axis("Penyebab")
            .reset_index(name="Gangguan")
        )
        total_cause = max(int(cause_df["Gangguan"].sum()), 1)
        cause_df["Persentase (%)"] = (
            cause_df["Gangguan"] / total_cause * 100
        ).round(1)

        st.dataframe(
            cause_df,
            use_container_width=True,
            hide_index=True,
            height=275,
        )

    with st.expander("Detail Gangguan", expanded=False):
        detail_columns = [
            "event_date",
            "event_time",
            "ultg_name",
            "gi_name",
            "penyulang_name",
            "cause_name",
            "customer_outage_duration_min",
            "ens_kwh",
            "record_status",
        ]
        available = [column for column in detail_columns if column in df.columns]
        rename = {
            "event_date": "Tanggal",
            "event_time": "Jam",
            "ultg_name": "ULTG",
            "gi_name": "Gardu Induk",
            "penyulang_name": "Penyulang",
            "cause_name": "Penyebab",
            "customer_outage_duration_min": "Padam Pelanggan (menit)",
            "ens_kwh": "ENS (kWh)",
            "record_status": "Status",
        }

        st.dataframe(
            df[available]
            .sort_values(["event_date", "event_time"], ascending=[False, False])
            .rename(columns=rename),
            use_container_width=True,
            hide_index=True,
            height=420,
        )

def _render_operations_tab(
    start_date: date,
    end_date: date,
    ultg_flc: str | None,
    gi_flc: str | None,
    bay_flc: str | None,
    penyulang_id: str | None,
) -> None:
    st.subheader("Operations")
    st.caption(
        "Monitoring kejadian aktif, proses pemulihan, efektivitas manuver, "
        "dan normalisasi sistem pada periode terpilih."
    )

    try:
        rows = _load_operations_events(
            start_date,
            end_date,
            ultg_flc,
            gi_flc,
            bay_flc,
            penyulang_id,
        )
    except Exception as exc:
        st.error(f"Data operasi tidak dapat dimuat: {exc}")
        return

    if not rows:
        st.info("Belum ada data operasi pada periode yang dipilih.")
        return

    df = pd.DataFrame(rows)

    for column in [
        "aging_minutes",
        "customer_outage_duration_min",
        "pmt_condition_duration_min",
        "maneuvered_current_a",
        "remaining_current_a",
        "maneuvered_current_r_a",
        "maneuvered_current_s_a",
        "maneuvered_current_t_a",
        "remaining_current_r_a",
        "remaining_current_s_a",
        "remaining_current_t_a",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    total_events = len(df)

    status_series = (
        df["record_status"].fillna("").astype(str).str.upper()
        if "record_status" in df.columns
        else pd.Series(dtype="string")
    )
    active_events = int(status_series.eq("ONGOING").sum())
    recovered_events = int(status_series.eq("RECOVERED").sum())

    active_df = (
        df[status_series.eq("ONGOING")].copy()
        if not status_series.empty
        else pd.DataFrame()
    )

    highest_aging = (
        float(active_df["aging_minutes"].fillna(0).max())
        if not active_df.empty and "aging_minutes" in active_df.columns
        else 0.0
    )

    maneuvered_total = (
        float(df["maneuvered_current_a"].dropna().sum())
        if "maneuvered_current_a" in df.columns
        else 0.0
    )
    remaining_total = (
        float(df["remaining_current_a"].dropna().sum())
        if "remaining_current_a" in df.columns
        else 0.0
    )

    final_normal_count = 0
    if "final_supply_normalized" in df.columns:
        normalized = df["final_supply_normalized"]
        final_normal_count = int(
            normalized.fillna(False).astype(bool).sum()
        )

    # Primary KPI
    ops_kpis = [
        (
            "Total Kejadian",
            f"{total_events}",
            "Gangguan dan manuver pada periode",
        ),
        (
            "Kejadian Aktif",
            f"{active_events}",
            "Masih membutuhkan monitoring",
        ),
        (
            "Sudah Pulih",
            f"{recovered_events}",
            "Record berstatus recovered",
        ),
        (
            "Aging Aktif Tertinggi",
            f"{highest_aging:,.0f} min",
            "Durasi kejadian aktif terlama",
        ),
    ]

    kpi_html = "".join(
        (
            '<div class="ops-kpi">'
            f'<div class="ops-kpi-label">{_html_escape(label)}</div>'
            f'<div class="ops-kpi-value">{_html_escape(value)}</div>'
            f'<div class="ops-kpi-note">{_html_escape(note)}</div>'
            '</div>'
        )
        for label, value, note in ops_kpis
    )
    st.markdown(
        f'<div class="ops-kpi-grid">{kpi_html}</div>',
        unsafe_allow_html=True,
    )

    mini_items = [
        ("Arus Termanuver", f"{maneuvered_total:,.1f} A"),
        ("Arus Tersisa", f"{remaining_total:,.1f} A"),
        ("Supply Normal", f"{final_normal_count} kejadian"),
        (
            "Recovery Rate",
            (
                f"{(recovered_events / total_events * 100):.1f}%"
                if total_events > 0
                else "0.0%"
            ),
        ),
    ]

    mini_html = "".join(
        (
            '<div class="ops-mini">'
            f'<div class="ops-mini-label">{_html_escape(label)}</div>'
            f'<div class="ops-mini-value">{_html_escape(value)}</div>'
            '</div>'
        )
        for label, value in mini_items
    )
    st.markdown(
        f'<div class="ops-mini-grid">{mini_html}</div>',
        unsafe_allow_html=True,
    )

    # Row 1 — Status & aging
    left, right = st.columns([0.9, 1.1])

    with left:
        _section_header(
            "Status Pemulihan",
            kicker="Operasional",
            note="Distribusi status record pada periode terpilih.",
        )

        status_counts = (
            df["record_status"]
            .fillna("UNKNOWN")
            .astype(str)
            .value_counts()
            .rename_axis("Status")
            .reset_index(name="Jumlah")
        )

        fig = px.pie(
            status_counts,
            names="Status",
            values="Jumlah",
            hole=0.58,
        )
        fig.update_traces(
            textinfo="percent+value",
            textposition="inside",
        )
        fig.update_layout(
            height=285,
            margin=dict(l=5, r=5, t=10, b=45),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.05,
                xanchor="center",
                x=0.5,
                font=dict(size=9),
            ),
            font=dict(size=10),
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False},
        )

    with right:
        _section_header(
            "Aging Kejadian Aktif",
            kicker="Operasional",
            note="Prioritas monitoring berdasarkan lama kejadian masih aktif.",
        )

        if active_df.empty:
            st.success("Tidak ada kejadian aktif pada scope dan periode terpilih.")
        else:
            active_chart = active_df.copy()
            if "penyulang_name" not in active_chart.columns:
                active_chart["penyulang_name"] = "-"
            if "aging_minutes" not in active_chart.columns:
                active_chart["aging_minutes"] = 0

            active_chart["aging_minutes"] = (
                pd.to_numeric(
                    active_chart["aging_minutes"],
                    errors="coerce",
                )
                .fillna(0)
            )

            active_chart = (
                active_chart[
                    ["penyulang_name", "aging_minutes"]
                ]
                .sort_values("aging_minutes", ascending=True)
                .tail(10)
                .rename(
                    columns={
                        "penyulang_name": "Penyulang",
                        "aging_minutes": "Aging (min)",
                    }
                )
            )

            fig = px.bar(
                active_chart,
                x="Aging (min)",
                y="Penyulang",
                orientation="h",
                text=active_chart["Aging (min)"].map(
                    lambda x: f"{x:,.0f} min"
                ),
            )
            fig.update_traces(
                textposition="outside",
                cliponaxis=False,
            )
            fig.update_layout(
                height=285,
                margin=dict(l=10, r=25, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                xaxis_title="menit",
                yaxis_title=None,
                font=dict(size=10),
            )
            fig.update_xaxes(
                rangemode="tozero",
                gridcolor="rgba(128,128,128,.12)",
            )
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False},
            )

    # Row 2 — Aging bucket & maneuver effectiveness
    left2, right2 = st.columns(2)

    with left2:
        _section_header(
            "Aging Bucket",
            kicker="Operasional",
            note="Distribusi durasi kejadian aktif.",
        )

        if active_df.empty or "aging_minutes" not in active_df.columns:
            aging_bucket_df = pd.DataFrame(
                {
                    "Bucket": ["≤ 15", "16–30", "31–60", "> 60"],
                    "Jumlah": [0, 0, 0, 0],
                }
            )
        else:
            aging = pd.to_numeric(
                active_df["aging_minutes"],
                errors="coerce",
            ).fillna(0)

            aging_bucket_df = pd.DataFrame(
                {
                    "Bucket": ["≤ 15", "16–30", "31–60", "> 60"],
                    "Jumlah": [
                        int((aging <= 15).sum()),
                        int(((aging > 15) & (aging <= 30)).sum()),
                        int(((aging > 30) & (aging <= 60)).sum()),
                        int((aging > 60).sum()),
                    ],
                }
            )

        fig = px.bar(
            aging_bucket_df,
            x="Bucket",
            y="Jumlah",
            text="Jumlah",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(
            height=285,
            margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
            xaxis_title="Menit",
            yaxis_title=None,
            font=dict(size=10),
        )
        fig.update_yaxes(
            rangemode="tozero",
            gridcolor="rgba(128,128,128,.12)",
            dtick=1,
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False},
        )

    with right2:
        _section_header(
            "Efektivitas Manuver",
            kicker="Operasional",
            note="Perbandingan arus termanuver dan arus tersisa setelah manuver.",
        )

        maneuver_summary = pd.DataFrame(
            {
                "Parameter": ["Termanuver", "Tersisa"],
                "Arus (A)": [maneuvered_total, remaining_total],
            }
        )

        fig = px.bar(
            maneuver_summary,
            x="Parameter",
            y="Arus (A)",
            text=maneuver_summary["Arus (A)"].map(
                lambda x: f"{x:,.1f} A"
            ),
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(
            height=285,
            margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
            xaxis_title=None,
            yaxis_title="A",
            font=dict(size=10),
        )
        fig.update_yaxes(
            rangemode="tozero",
            gridcolor="rgba(128,128,128,.12)",
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False},
        )

    # Row 3 — R/S/T current profile
    _section_header(
        "Profil Arus Manuver R / S / T",
        kicker="Operasional",
        note="Perbandingan arus termanuver dan arus tersisa per phasa.",
    )

    phase_values = []
    for phase in ["R", "S", "T"]:
        maneuver_col = f"maneuvered_current_{phase.lower()}_a"
        remaining_col = f"remaining_current_{phase.lower()}_a"

        maneuver_value = (
            float(df[maneuver_col].dropna().sum())
            if maneuver_col in df.columns
            else 0.0
        )
        remaining_value = (
            float(df[remaining_col].dropna().sum())
            if remaining_col in df.columns
            else 0.0
        )

        phase_values.append(
            {
                "Phasa": phase,
                "Kategori": "Termanuver",
                "Arus (A)": maneuver_value,
            }
        )
        phase_values.append(
            {
                "Phasa": phase,
                "Kategori": "Tersisa",
                "Arus (A)": remaining_value,
            }
        )

    phase_df = pd.DataFrame(phase_values)

    fig = px.bar(
        phase_df,
        x="Phasa",
        y="Arus (A)",
        color="Kategori",
        barmode="group",
    )
    fig.update_layout(
        height=285,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        xaxis_title=None,
        yaxis_title="A",
        font=dict(size=10),
    )
    fig.update_yaxes(
        rangemode="tozero",
        gridcolor="rgba(128,128,128,.12)",
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displayModeBar": False},
    )

    # Active event details
    if not active_df.empty:
        with st.expander("Detail Kejadian Aktif", expanded=False):
            active_columns = [
                "event_date",
                "event_time",
                "ultg_name",
                "gi_name",
                "penyulang_name",
                "event_type_code",
                "pmt_status_code",
                "aging_minutes",
                "operator_name",
                "dispatcher_name",
            ]
            available = [
                column for column in active_columns if column in active_df.columns
            ]
            rename = {
                "event_date": "Tanggal",
                "event_time": "Jam",
                "ultg_name": "ULTG",
                "gi_name": "Gardu Induk",
                "penyulang_name": "Penyulang",
                "event_type_code": "Jenis",
                "pmt_status_code": "Status PMT",
                "aging_minutes": "Aging (menit)",
                "operator_name": "Operator",
                "dispatcher_name": "Dispatcher",
            }

            st.dataframe(
                active_df[available].rename(columns=rename),
                use_container_width=True,
                hide_index=True,
                height=360,
            )

    with st.expander("Detail Operasi", expanded=False):
        detail_columns = [
            "event_date",
            "event_time",
            "ultg_name",
            "gi_name",
            "penyulang_name",
            "event_type_code",
            "record_status",
            "customer_outage_duration_min",
            "pmt_condition_duration_min",
            "maneuvered_current_a",
            "remaining_current_a",
            "final_supply_normalized",
        ]
        available = [
            column for column in detail_columns if column in df.columns
        ]
        rename = {
            "event_date": "Tanggal",
            "event_time": "Jam",
            "ultg_name": "ULTG",
            "gi_name": "Gardu Induk",
            "penyulang_name": "Penyulang",
            "event_type_code": "Jenis",
            "record_status": "Status Record",
            "customer_outage_duration_min": "Padam Pelanggan (menit)",
            "pmt_condition_duration_min": "Kondisi PMT (menit)",
            "maneuvered_current_a": "Arus Termanuver (A)",
            "remaining_current_a": "Arus Tersisa (A)",
            "final_supply_normalized": "Supply Normal",
        }

        st.dataframe(
            df[available].rename(columns=rename),
            use_container_width=True,
            hide_index=True,
            height=420,
        )

def _render_governance_tab(
    start_date: date,
    end_date: date,
    ultg_flc: str | None,
    gi_flc: str | None,
    bay_flc: str | None,
    penyulang_id: str | None,
) -> None:
    st.subheader("Governance")
    st.caption(
        "Kontrol kualitas data operasional dan kepatuhan laporan bulanan "
        "berdasarkan scope serta periode terpilih."
    )

    try:
        data = _load_governance(
            start_date,
            end_date,
            ultg_flc,
            gi_flc,
            bay_flc,
            penyulang_id,
        )
    except Exception as exc:
        st.error(f"Data governance tidak dapat dimuat: {exc}")
        return

    completeness_raw = data.get("completeness", {})
    reports_raw = data.get("reports", {})
    report_rows_raw = data.get("report_rows", [])

    completeness = (
        completeness_raw
        if isinstance(completeness_raw, dict)
        else {}
    )
    reports = (
        reports_raw
        if isinstance(reports_raw, dict)
        else {}
    )
    report_rows = (
        report_rows_raw
        if isinstance(report_rows_raw, list)
        else []
    )

    total_events = _safe_int(completeness.get("total_events"))
    core_complete = _safe_int(completeness.get("core_complete"))
    completeness_pct = _safe_float(
        completeness.get("core_completeness_percent")
    )
    gangguan_incomplete = _safe_int(
        completeness.get("gangguan_incomplete")
    )
    ongoing_events = _safe_int(
        completeness.get("ongoing_events")
    )
    recovered_missing = _safe_int(
        completeness.get("recovered_missing_recovery")
    )
    no_fault_current = _safe_int(
        completeness.get("gangguan_without_fault_current")
    )

    total_reports = _safe_int(reports.get("total_reports"))
    verified_reports = _safe_int(reports.get("verified_reports"))
    pending_reports = _safe_int(reports.get("pending_verification"))
    draft_reports = _safe_int(reports.get("draft_reports"))
    verification_pct = _safe_float(
        reports.get("verification_percent")
    )

    report_period_label = _month_label(
        reports.get("report_period_year"),
        reports.get("report_period_month"),
    )
    approval_period_label = _month_label(
        reports.get("approval_year"),
        reports.get("approval_month"),
    )

    # KPI utama
    gov_kpis = [
        (
            "Data Completeness",
            f"{completeness_pct:.1f}%",
            f"{core_complete} dari {total_events} kejadian lengkap",
        ),
        (
            "Data Belum Lengkap",
            f"{gangguan_incomplete}",
            "Gangguan dengan field penting belum lengkap",
        ),
        (
            "Tanpa Arus Gangguan",
            f"{no_fault_current}",
            "Gangguan tanpa data arus R/S/T/N",
        ),
        (
            f"Report {report_period_label}",
            f"{verification_pct:.1f}%",
            f"Approval / verifikasi {approval_period_label}",
        ),
    ]

    kpi_html = "".join(
        (
            '<div class="gov-kpi">'
            f'<div class="gov-kpi-label">{_html_escape(label)}</div>'
            f'<div class="gov-kpi-value">{_html_escape(value)}</div>'
            f'<div class="gov-kpi-note">{_html_escape(note)}</div>'
            '</div>'
        )
        for label, value, note in gov_kpis
    )
    st.markdown(
        f'<div class="gov-kpi-grid">{kpi_html}</div>',
        unsafe_allow_html=True,
    )

    # Row 1 - completeness & report status
    left, right = st.columns(2)

    with left:
        _section_header(
            "Kualitas Data Operasional",
            kicker="Governance",
            note="Ringkasan kualitas data kejadian pada periode terpilih.",
        )

        quality_df = pd.DataFrame(
            {
                "Kategori": [
                    "Core Complete",
                    "Belum Lengkap",
                    "Tanpa Arus Gangguan",
                    "Recovered tanpa waktu pulih",
                ],
                "Jumlah": [
                    core_complete,
                    gangguan_incomplete,
                    no_fault_current,
                    recovered_missing,
                ],
            }
        )

        fig = px.bar(
            quality_df,
            x="Kategori",
            y="Jumlah",
            text="Jumlah",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(
            height=285,
            margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
            xaxis_title=None,
            yaxis_title=None,
            font=dict(size=10),
        )
        fig.update_yaxes(
            rangemode="tozero",
            gridcolor="rgba(128,128,128,.12)",
            dtick=1,
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False},
        )

    with right:
        _section_header(
            f"Status Laporan {report_period_label}",
            kicker="Governance",
            note=(
                f"Laporan periode {report_period_label} diproses / diverifikasi "
                f"pada {approval_period_label}."
            ),
        )

        report_status_df = pd.DataFrame(
            {
                "Status": [
                    "Verified",
                    "Menunggu Verifikasi",
                    "Draft",
                ],
                "Jumlah": [
                    verified_reports,
                    pending_reports,
                    draft_reports,
                ],
            }
        )

        if total_reports > 0:
            fig = px.pie(
                report_status_df,
                names="Status",
                values="Jumlah",
                hole=0.58,
            )
            fig.update_traces(
                textinfo="percent+value",
                textposition="inside",
            )
            fig.update_layout(
                height=285,
                margin=dict(l=5, r=5, t=10, b=45),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                legend=dict(
                    orientation="h",
                    yanchor="top",
                    y=-0.05,
                    xanchor="center",
                    x=0.5,
                    font=dict(size=9),
                ),
                font=dict(size=10),
            )
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False},
            )
        else:
            st.info(
                f"Belum ada laporan {report_period_label} "
                "pada scope terpilih."
            )

    # Row 2 - compliance progress & issues
    left2, right2 = st.columns([0.8, 1.2])

    with left2:
        _section_header(
            "Compliance Laporan",
            kicker="Governance",
            note="Persentase laporan yang sudah diverifikasi.",
        )

        fig = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=verification_pct,
                number={"suffix": "%"},
                title={"text": report_period_label},
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar": {"thickness": 0.28},
                    "steps": [
                        {
                            "range": [0, 100],
                            "color": "rgba(128,128,128,.06)",
                        }
                    ],
                    "threshold": {
                        "line": {"width": 3},
                        "thickness": 0.75,
                        "value": 100,
                    },
                },
            )
        )
        fig.update_layout(
            height=250,
            margin=dict(l=10, r=10, t=20, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
            font=dict(size=11),
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False},
        )

    with right2:
        _section_header(
            "Management Attention",
            kicker="Governance",
            note="Item yang perlu ditindaklanjuti untuk menjaga kualitas data dan laporan.",
        )

        attention_items: list[tuple[str, str]] = []

        if gangguan_incomplete > 0:
            attention_items.append(
                (
                    "Data Belum Lengkap",
                    f"{gangguan_incomplete} gangguan memiliki data penting yang belum lengkap.",
                )
            )
        if no_fault_current > 0:
            attention_items.append(
                (
                    "Arus Gangguan Belum Ada",
                    f"{no_fault_current} gangguan belum memiliki arus gangguan R/S/T/N.",
                )
            )
        if recovered_missing > 0:
            attention_items.append(
                (
                    "Recovery Belum Lengkap",
                    f"{recovered_missing} record recovered belum memiliki waktu pemulihan.",
                )
            )
        if pending_reports > 0:
            attention_items.append(
                (
                    f"Verifikasi Laporan {report_period_label}",
                    f"{pending_reports} laporan masih menunggu verifikasi.",
                )
            )
        if draft_reports > 0:
            attention_items.append(
                (
                    f"Draft Laporan {report_period_label}",
                    f"{draft_reports} laporan masih berstatus draft.",
                )
            )
        if completeness_pct < 95:
            attention_items.append(
                (
                    "Data Completeness",
                    f"Completeness {completeness_pct:.1f}% masih di bawah target internal 95%.",
                )
            )

        if not attention_items:
            attention_items = [
                (
                    "Kondisi Terkendali",
                    "Tidak ada isu governance utama pada periode dan scope terpilih.",
                )
            ]

        attention_html = "".join(
            (
                '<div class="gov-attention-card">'
                f'<div class="gov-attention-title">{_html_escape(title)}</div>'
                f'<div class="gov-attention-text">{_html_escape(text)}</div>'
                '</div>'
            )
            for title, text in attention_items[:6]
        )

        st.markdown(
            f'<div class="gov-attention-grid">{attention_html}</div>',
            unsafe_allow_html=True,
        )

    # Detail laporan
    with st.expander(
        f"Detail Laporan {report_period_label}",
        expanded=False,
    ):
        if report_rows:
            report_df = pd.DataFrame(report_rows)

            rename = {
                "scope_name": "Scope",
                "status": "Status",
                "submitted_at": "Submitted",
                "verified_at": "Verified",
                "signer_name": "Penandatangan",
                "signer_position": "Jabatan",
                "report_year": "Tahun",
                "report_month": "Bulan",
            }

            preferred = [
                "scope_name",
                "status",
                "submitted_at",
                "verified_at",
                "signer_name",
                "signer_position",
            ]
            available = [
                column
                for column in preferred
                if column in report_df.columns
            ]

            st.dataframe(
                report_df[available].rename(columns=rename),
                use_container_width=True,
                hide_index=True,
                height=360,
            )
        else:
            st.info(
                f"Belum ada detail laporan {report_period_label} "
                "pada scope terpilih."
            )

    with st.expander("Ringkasan Data Governance", expanded=False):
        summary_df = pd.DataFrame(
            [
                ("Total Kejadian", total_events),
                ("Core Complete", core_complete),
                ("Data Belum Lengkap", gangguan_incomplete),
                ("Tanpa Arus Gangguan", no_fault_current),
                ("Ongoing", ongoing_events),
                ("Recovered tanpa Waktu Pulih", recovered_missing),
                ("Total Laporan", total_reports),
                ("Verified", verified_reports),
                ("Menunggu Verifikasi", pending_reports),
                ("Draft", draft_reports),
            ],
            columns=["Parameter", "Nilai"],
        )

        st.dataframe(
            summary_df,
            use_container_width=True,
            hide_index=True,
            height=360,
        )

def render() -> None:
    render_sidebar()
    _inject_dashboard_style()

    if not can_view():
        st.error(
            "Anda tidak memiliki akses untuk melihat Dashboard."
        )
        return

    st.markdown(
        """
        <div class="dashboard-hero">
            <div class="dashboard-title">Dashboard Gangguan Penyulang 20 kV</div>
            <div class="dashboard-subtitle">
                Executive monitoring • Reliability • Engineering • Operations • Governance
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    today = date.today()

    try:
        filter_rows = _load_dashboard_filter_options()
    except Exception as exc:
        st.error(f"Filter dashboard tidak dapat dimuat: {exc}")
        return

    filter_df = pd.DataFrame(filter_rows)

    if filter_df.empty:
        st.warning("Tidak ada hierarchy yang tersedia pada scope akses.")
        return

    st.markdown(
        (
            '<div class="filter-shell">'
            '<div class="filter-shell-head">'
            '<div>'
            '<div class="filter-shell-title">Filter & Scope Dashboard</div>'
            '<div class="filter-shell-subtitle">'
            'Semua indikator mengikuti periode dan scope akses pengguna.'
            '</div>'
            '</div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )

    d1, d2 = st.columns(2)

    with d1:
        start_date = st.date_input(
            "Periode Mulai",
            value=_month_start(today),
            key="dashboard_start_date",
        )

    with d2:
        end_date = st.date_input(
            "Periode Sampai",
            value=today,
            key="dashboard_end_date",
        )

    if start_date > end_date:
        st.error(
            "Periode Mulai tidak boleh lebih besar dari Periode Sampai."
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # ULTG
    ultg_options = (
        filter_df[["ultg_flc", "ultg_name"]]
        .drop_duplicates()
        .sort_values("ultg_name")
        .to_dict("records")
    )
    ultg_lookup = {
        str(item["ultg_flc"]): str(item["ultg_name"])
        for item in ultg_options
    }
    ultg_ids = ["ALL"] + list(ultg_lookup.keys())

    f1, f2, f3, f4 = st.columns(4)

    with f1:
        ultg_selection_raw = st.selectbox(
            "ULTG",
            ultg_ids,
            format_func=lambda value: _format_filter_option(
                str(value),
                ultg_lookup,
                "Semua ULTG",
            ),
            key="dashboard_filter_ultg",
        )
        ultg_selection = str(ultg_selection_raw)

    scoped = filter_df.copy()
    if ultg_selection != "ALL":
        scoped = scoped[scoped["ultg_flc"] == ultg_selection]

    # GI
    gi_options = (
        scoped[["gi_flc", "gi_name"]]
        .drop_duplicates()
        .sort_values("gi_name")
        .to_dict("records")
    )
    gi_lookup = {
        str(item["gi_flc"]): str(item["gi_name"])
        for item in gi_options
    }
    gi_ids = ["ALL"] + list(gi_lookup.keys())

    with f2:
        gi_selection_raw = st.selectbox(
            "Gardu Induk",
            gi_ids,
            format_func=lambda value: _format_filter_option(
                str(value),
                gi_lookup,
                "Semua GI",
            ),
            key="dashboard_filter_gi",
        )
        gi_selection = str(gi_selection_raw)

    if gi_selection != "ALL":
        scoped = scoped[scoped["gi_flc"] == gi_selection]

    # BAY
    bay_options = (
        scoped[["bay_flc", "bay_name"]]
        .drop_duplicates()
        .sort_values("bay_name")
        .to_dict("records")
    )
    bay_lookup = {
        str(item["bay_flc"]): str(item["bay_name"])
        for item in bay_options
    }
    bay_ids = ["ALL"] + list(bay_lookup.keys())

    with f3:
        bay_selection_raw = st.selectbox(
            "Bay Penyulang",
            bay_ids,
            format_func=lambda value: _format_filter_option(
                str(value),
                bay_lookup,
                "Semua Bay",
            ),
            key="dashboard_filter_bay",
        )
        bay_selection = str(bay_selection_raw)

    if bay_selection != "ALL":
        scoped = scoped[scoped["bay_flc"] == bay_selection]

    # PENYULANG
    penyulang_options = (
        scoped[["penyulang_id", "penyulang_name"]]
        .drop_duplicates()
        .sort_values("penyulang_name")
        .to_dict("records")
    )
    penyulang_lookup = {
        str(item["penyulang_id"]): str(item["penyulang_name"])
        for item in penyulang_options
    }
    penyulang_ids = ["ALL"] + list(penyulang_lookup.keys())

    with f4:
        penyulang_selection_raw = st.selectbox(
            "Penyulang",
            penyulang_ids,
            format_func=lambda value: _format_filter_option(
                str(value),
                penyulang_lookup,
                "Semua Penyulang",
            ),
            key="dashboard_filter_penyulang",
        )
        penyulang_selection = str(penyulang_selection_raw)

    ultg_label = (
        "Semua ULTG dalam Scope"
        if ultg_selection == "ALL"
        else ultg_lookup.get(ultg_selection, ultg_selection)
    )
    gi_label = (
        "Semua GI"
        if gi_selection == "ALL"
        else gi_lookup.get(gi_selection, gi_selection)
    )
    bay_label = (
        "Semua Bay"
        if bay_selection == "ALL"
        else bay_lookup.get(bay_selection, bay_selection)
    )
    penyulang_label = (
        "Semua Penyulang"
        if penyulang_selection == "ALL"
        else penyulang_lookup.get(
            penyulang_selection,
            penyulang_selection,
        )
    )

    filter_summary_html = "".join(
        (
            '<span class="filter-summary-chip">'
            f'{_html_escape(label)}'
            '</span>'
        )
        for label in [
            f"{start_date:%d %b %Y} – {end_date:%d %b %Y}",
            ultg_label,
            gi_label,
            bay_label,
            penyulang_label,
        ]
    )

    st.markdown(
        (
            '<div class="filter-summary">'
            f'{filter_summary_html}'
            '</div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )

    refresh_col, _ = st.columns([0.14, 0.86])
    with refresh_col:
        if st.button(
            "Refresh Data",
            key="dashboard_refresh_data",
            use_container_width=True,
        ):
            st.cache_data.clear()
            st.rerun()

    selected_ultg = None if ultg_selection == "ALL" else ultg_selection
    selected_gi = None if gi_selection == "ALL" else gi_selection
    selected_bay = None if bay_selection == "ALL" else bay_selection
    selected_penyulang = (
        None
        if penyulang_selection == "ALL"
        else penyulang_selection
    )

    selected_section = st.segmented_control(
        "Dashboard Section",
        options=[
            "Executive",
            "Reliability",
            "Analisa",
            "Operations",
            "Governance",
        ],
        default="Executive",
        key="dashboard_section",
        label_visibility="collapsed",
    )

    if selected_section == "Reliability":
        with st.spinner("Memuat reliability..."):
            _render_reliability_tab(
                start_date,
                end_date,
                selected_ultg,
                selected_gi,
                selected_bay,
                selected_penyulang,
            )
    elif selected_section == "Analisa":
        with st.spinner("Memuat analisa..."):
            _render_engineering_tab(
                start_date,
                end_date,
                selected_ultg,
                selected_gi,
                selected_bay,
                selected_penyulang,
            )
    elif selected_section == "Operations":
        with st.spinner("Memuat operations..."):
            _render_operations_tab(
                start_date,
                end_date,
                selected_ultg,
                selected_gi,
                selected_bay,
                selected_penyulang,
            )
    elif selected_section == "Governance":
        with st.spinner("Memuat governance..."):
            _render_governance_tab(
                start_date,
                end_date,
                selected_ultg,
                selected_gi,
                selected_bay,
                selected_penyulang,
            )
    else:
        with st.spinner("Memuat executive summary..."):
            _render_executive_tab(
                start_date,
                end_date,
                selected_ultg,
                selected_gi,
                selected_bay,
                selected_penyulang,
            )


    st.markdown(
        '<div style="margin-top:1.2rem;padding-top:.65rem;'
        'border-top:1px solid rgba(128,128,128,.12);'
        'font-size:.66rem;opacity:.52;">'
        'Dashboard Gangguan Penyulang 20 kV • Data mengikuti periode dan scope akses pengguna.'
        '</div>',
        unsafe_allow_html=True,
    )



if __name__ == "__main__":
    render()
