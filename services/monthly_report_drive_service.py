from __future__ import annotations

import base64
from typing import Any

import httpx
import streamlit as st

from services.report_service import (
    register_monthly_report_file,
)


def _get_drive_config() -> tuple[str, str]:
    try:
        config = st.secrets[
            "google_drive"
        ]

    except Exception as exc:
        raise RuntimeError(
            "Konfigurasi [google_drive] belum tersedia "
            "di .streamlit/secrets.toml."
        ) from exc

    web_app_url = str(
        config.get(
            "web_app_url",
            "",
        )
        or ""
    ).strip()

    api_key = str(
        config.get(
            "api_key",
            "",
        )
        or ""
    ).strip()

    if not web_app_url:
        raise RuntimeError(
            "google_drive.web_app_url belum diisi."
        )

    if not api_key:
        raise RuntimeError(
            "google_drive.api_key belum diisi."
        )

    return (
        web_app_url,
        api_key,
    )


def upload_monthly_report_bytes(
    *,
    monthly_report_id: str,
    report_year: int,
    report_month: int,
    gi_flc: str,
    gi_name: str,
    file_name: str,
    mime_type: str,
    file_bytes: bytes,
    file_format: str,
) -> dict[str, Any]:
    """
    Upload file laporan bulanan resmi ke Google Drive.

    Endpoint Apps Script perlu menangani:
        request_type = MONTHLY_REPORT

    Struktur folder yang direkomendasikan:
        ROOT/
        └─ LAPORAN BULANAN/
           └─ GI/
              └─ YYYY/
                 └─ YYYY-MM/
                    ├─ PDF
                    └─ EXCEL
    """

    if not file_bytes:
        raise ValueError(
            "File laporan kosong."
        )

    web_app_url, api_key = (
        _get_drive_config()
    )

    normalized_format = str(
        file_format
        or ""
    ).strip().upper()

    if normalized_format not in {
        "PDF",
        "XLSX",
    }:
        raise ValueError(
            "file_format harus PDF atau XLSX."
        )

    payload = {
        "api_key":
            api_key,

        "request_type":
            "MONTHLY_REPORT",

        "monthly_report_id":
            monthly_report_id,

        "report_year":
            int(
                report_year
            ),

        "report_month":
            int(
                report_month
            ),

        "gi_flc":
            str(
                gi_flc
                or ""
            ).strip(),

        "gi_name":
            str(
                gi_name
                or ""
            ).strip(),

        "file_format":
            normalized_format,

        "file_name":
            str(
                file_name
                or ""
            ).strip(),

        "mime_type":
            str(
                mime_type
                or "application/octet-stream"
            ).strip(),

        "base64_data":
            base64.b64encode(
                file_bytes
            ).decode(
                "ascii"
            ),
    }

    try:
        with httpx.Client(
            timeout=60.0,
            follow_redirects=True,
        ) as client:
            response = client.post(
                web_app_url,
                json=payload,
            )

            response.raise_for_status()

            result = response.json()

    except Exception as exc:
        raise RuntimeError(
            f"Upload laporan ke Google Drive gagal: {exc}"
        ) from exc

    if not isinstance(
        result,
        dict,
    ):
        raise RuntimeError(
            "Response Google Drive tidak valid."
        )

    if not bool(
        result.get(
            "success"
        )
    ):
        raise RuntimeError(
            str(
                result.get(
                    "error"
                )
                or "Upload laporan ke Google Drive gagal."
            )
        )

    file_url = str(
        result.get(
            "file_url"
        )
        or ""
    ).strip()

    if not file_url:
        raise RuntimeError(
            "Google Drive tidak mengembalikan file_url."
        )

    file_size_raw = result.get(
        "file_size"
    )

    file_size: int | None = None

    if isinstance(
        file_size_raw,
        (int, float),
    ):
        file_size = int(
            file_size_raw
        )

    register_monthly_report_file(
        monthly_report_id=(
            monthly_report_id
        ),
        file_format=(
            normalized_format
        ),
        file_name=str(
            result.get(
                "file_name"
            )
            or file_name
        ).strip(),
        drive_file_url=(
            file_url
        ),
        drive_file_id=str(
            result.get(
                "file_id"
            )
            or ""
        ).strip()
        or None,
        mime_type=str(
            result.get(
                "mime_type"
            )
            or mime_type
        ).strip()
        or None,
        file_size=(
            file_size
        ),
    )

    return result