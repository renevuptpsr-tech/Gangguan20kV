from __future__ import annotations

from typing import Any, cast

import pandas as pd
import streamlit as st

from services.report_service import get_accessible_feeders
from services.supabase_client import get_supabase_client


ReportRow = dict[str, Any]


STATUS_ORDER: dict[str, int] = {
    "NOT_CREATED": 0,
    "DRAFT": 1,
    "REJECTED": 2,
    "SUBMITTED": 3,
    "APPROVED": 4,
}


def _safe_string(
    value: Any,
    default: str = "",
) -> str:
    if value is None:
        return default

    text = str(value).strip()
    return text or default


def _build_accessible_gi_master() -> list[ReportRow]:
    feeders = get_accessible_feeders()

    gi_map: dict[str, ReportRow] = {}

    for row in feeders:
        gi_flc = _safe_string(
            row.get("gi_flc")
        )

        if not gi_flc:
            continue

        if gi_flc not in gi_map:
            gi_map[
                gi_flc
            ] = {
                "gi_flc":
                    gi_flc,

                "gi_name":
                    _safe_string(
                        row.get(
                            "gi_name"
                        ),
                        gi_flc,
                    ),

                "ultg_flc":
                    _safe_string(
                        row.get(
                            "ultg_flc"
                        )
                    ),

                "ultg_name":
                    _safe_string(
                        row.get(
                            "ultg_name"
                        ),
                        "-",
                    ),
            }

    return sorted(
        gi_map.values(),
        key=lambda row: (
            _safe_string(
                row.get(
                    "ultg_name"
                )
            ).upper(),
            _safe_string(
                row.get(
                    "gi_name"
                )
            ).upper(),
        ),
    )


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def load_monthly_monitoring_snapshot(
    report_year: int,
    report_month: int,
) -> list[ReportRow]:
    """
    Membuat snapshot monitoring untuk seluruh GI yang dapat
    diakses user saat ini.

    GI tanpa trx_monthly_report tetap muncul sebagai
    NOT_CREATED.
    """

    gi_master = (
        _build_accessible_gi_master()
    )

    if not gi_master:
        return []

    supabase = get_supabase_client()

    report_response = (
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
        .eq(
            "report_year",
            report_year,
        )
        .eq(
            "report_month",
            report_month,
        )
        .execute()
    )

    report_rows = cast(
        list[ReportRow],
        report_response.data
        or [],
    )

    report_by_gi: dict[
        str,
        ReportRow,
    ] = {}

    report_ids: list[str] = []

    for report in report_rows:
        scope_id = _safe_string(
            report.get(
                "scope_functloc_id"
            )
        )

        report_id = _safe_string(
            report.get(
                "monthly_report_id"
            )
        )

        if scope_id:
            report_by_gi[
                scope_id
            ] = report

        if report_id:
            report_ids.append(
                report_id
            )

    files_by_report: dict[
        str,
        dict[str, ReportRow],
    ] = {}

    if report_ids:
        file_response = (
            supabase
            .table(
                "trx_monthly_report_file"
            )
            .select(
                "report_file_id,monthly_report_id,file_format,"
                "file_name,drive_file_url,version_no,"
                "is_current,generated_at"
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

        file_rows = cast(
            list[ReportRow],
            file_response.data
            or [],
        )

        for file_row in file_rows:
            report_id = _safe_string(
                file_row.get(
                    "monthly_report_id"
                )
            )

            file_format = _safe_string(
                file_row.get(
                    "file_format"
                )
            ).upper()

            if (
                not report_id
                or file_format
                not in {
                    "PDF",
                    "XLSX",
                }
            ):
                continue

            files_by_report.setdefault(
                report_id,
                {},
            )[
                file_format
            ] = file_row

    snapshot: list[ReportRow] = []

    for gi in gi_master:
        gi_flc = _safe_string(
            gi.get(
                "gi_flc"
            )
        )

        report = report_by_gi.get(
            gi_flc
        )

        if report is None:
            snapshot.append(
                {
                    **gi,
                    "report_year":
                        report_year,

                    "report_month":
                        report_month,

                    "monthly_report_id":
                        None,

                    "status":
                        "NOT_CREATED",

                    "submitted_at":
                        None,

                    "verified_at":
                        None,

                    "verified_role":
                        None,

                    "signer_name":
                        None,

                    "signer_position":
                        None,

                    "pdf_url":
                        None,

                    "xlsx_url":
                        None,

                    "file_status":
                        "NONE",
                }
            )

            continue

        report_id = _safe_string(
            report.get(
                "monthly_report_id"
            )
        )

        files = files_by_report.get(
            report_id,
            {},
        )

        pdf_file = files.get(
            "PDF"
        )

        xlsx_file = files.get(
            "XLSX"
        )

        if (
            pdf_file
            and xlsx_file
        ):
            file_status = (
                "COMPLETE"
            )

        elif (
            pdf_file
            or xlsx_file
        ):
            file_status = (
                "PARTIAL"
            )

        else:
            file_status = (
                "NONE"
            )

        snapshot.append(
            {
                **gi,
                **report,

                "pdf_url":
                    (
                        pdf_file.get(
                            "drive_file_url"
                        )
                        if pdf_file
                        else None
                    ),

                "xlsx_url":
                    (
                        xlsx_file.get(
                            "drive_file_url"
                        )
                        if xlsx_file
                        else None
                    ),

                "file_status":
                    file_status,
            }
        )

    snapshot.sort(
        key=lambda row: (
            STATUS_ORDER.get(
                _safe_string(
                    row.get(
                        "status"
                    )
                ).upper(),
                99,
            ),
            _safe_string(
                row.get(
                    "ultg_name"
                )
            ).upper(),
            _safe_string(
                row.get(
                    "gi_name"
                )
            ).upper(),
        )
    )

    return snapshot


def build_monitoring_summary(
    rows: list[ReportRow],
) -> dict[str, int | float]:
    total_gi = len(
        rows
    )

    counts = {
        "NOT_CREATED": 0,
        "DRAFT": 0,
        "SUBMITTED": 0,
        "REJECTED": 0,
        "APPROVED": 0,
    }

    complete_files = 0

    for row in rows:
        status = _safe_string(
            row.get(
                "status"
            ),
            "NOT_CREATED",
        ).upper()

        if status in counts:
            counts[
                status
            ] += 1

        if (
            status
            == "APPROVED"
            and _safe_string(
                row.get(
                    "file_status"
                )
            ).upper()
            == "COMPLETE"
        ):
            complete_files += 1

    completion_pct = (
        (
            counts[
                "APPROVED"
            ]
            / total_gi
        )
        * 100
        if total_gi
        else 0.0
    )

    archive_pct = (
        (
            complete_files
            / total_gi
        )
        * 100
        if total_gi
        else 0.0
    )

    return {
        "total_gi":
            total_gi,

        "not_created":
            counts[
                "NOT_CREATED"
            ],

        "draft":
            counts[
                "DRAFT"
            ],

        "submitted":
            counts[
                "SUBMITTED"
            ],

        "rejected":
            counts[
                "REJECTED"
            ],

        "approved":
            counts[
                "APPROVED"
            ],

        "complete_files":
            complete_files,

        "completion_pct":
            round(
                completion_pct,
                1,
            ),

        "archive_pct":
            round(
                archive_pct,
                1,
            ),
    }


def monitoring_rows_to_dataframe(
    rows: list[ReportRow],
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()

    data: list[
        dict[str, Any]
    ] = []

    for row in rows:
        status = _safe_string(
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

        data.append(
            {
                "ULTG":
                    _safe_string(
                        row.get(
                            "ultg_name"
                        ),
                        "-",
                    ),

                "Gardu Induk":
                    _safe_string(
                        row.get(
                            "gi_name"
                        ),
                        "-",
                    ),

                "Status":
                    status,

                "Diverifikasi Oleh":
                    _safe_string(
                        row.get(
                            "signer_name"
                        ),
                        "-",
                    ),

                "Role":
                    _safe_string(
                        row.get(
                            "verified_role"
                        ),
                        "-",
                    ),

                "File":
                    (
                        "Lengkap"
                        if file_status
                        == "COMPLETE"
                        else (
                            "Sebagian"
                            if file_status
                            == "PARTIAL"
                            else "-"
                        )
                    ),

                "PDF":
                    _safe_string(
                        row.get(
                            "pdf_url"
                        ),
                        "",
                    ),

                "Excel":
                    _safe_string(
                        row.get(
                            "xlsx_url"
                        ),
                        "",
                    ),
            }
        )

    return pd.DataFrame(
        data
    )


def clear_monthly_monitoring_cache() -> None:
    load_monthly_monitoring_snapshot.clear()