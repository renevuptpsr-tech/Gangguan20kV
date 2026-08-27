from __future__ import annotations

import base64
from typing import Any, cast

import httpx
import streamlit as st

from services.supabase_client import get_supabase_client


def _get_drive_config() -> tuple[str, str]:
    try:
        config = st.secrets["google_drive"]
    except Exception as exc:
        raise RuntimeError(
            "Konfigurasi [google_drive] belum tersedia "
            "di .streamlit/secrets.toml."
        ) from exc

    web_app_url = str(config.get("web_app_url", "")).strip()
    api_key = str(config.get("api_key", "")).strip()

    if not web_app_url:
        raise RuntimeError("google_drive.web_app_url belum diisi.")

    if not api_key:
        raise RuntimeError("google_drive.api_key belum diisi.")

    return web_app_url, api_key


def upload_file_to_drive(
    *,
    uploaded_file: Any,
    event_id: str,
    event_type: str,
    hierarchy: dict[str, Any],
    event_date: str,
    event_time: str,
    cause_name: str,
) -> dict[str, Any]:
    web_app_url, api_key = _get_drive_config()

    file_name = str(
        getattr(uploaded_file, "name", "evidence") or "evidence"
    ).strip()

    mime_type = str(
        getattr(
            uploaded_file,
            "type",
            "application/octet-stream",
        )
        or "application/octet-stream"
    ).strip()

    try:
        file_bytes = uploaded_file.getvalue()
    except Exception as exc:
        raise RuntimeError(
            f"File {file_name} tidak dapat dibaca."
        ) from exc

    if not file_bytes:
        raise RuntimeError(f"File {file_name} kosong.")

    payload: dict[str, Any] = {
        "api_key": api_key,
        "event_id": event_id,
        "event_type": event_type,
        "ultg_name": str(
            hierarchy.get("ultg_name") or "ULTG_UNKNOWN"
        ),
        "gi_name": str(
            hierarchy.get("gi_name") or "GI_UNKNOWN"
        ),
        "event_date": event_date,
        "event_time": event_time,
        "cause_name": cause_name or "TANPA PENYEBAB",
        "file_name": file_name,
        "mime_type": mime_type,
        "base64_data": base64.b64encode(
            file_bytes
        ).decode("ascii"),
    }

    try:
        with httpx.Client(
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            response = client.post(
                web_app_url,
                json=payload,
            )
            response.raise_for_status()
            raw_data: Any = response.json()

    except Exception as exc:
        raise RuntimeError(
            f"Upload ke Google Drive gagal: {exc}"
        ) from exc

    if not isinstance(raw_data, dict):
        raise RuntimeError(
            "Response Apps Script tidak valid."
        )

    data = cast(
        dict[str, Any],
        raw_data,
    )

    if not bool(data.get("success")):
        raise RuntimeError(
            str(
                data.get("error")
                or "Upload Google Drive gagal."
            )
        )

    return data


def save_attachment_metadata(
    *,
    event_id: str,
    drive_result: dict[str, Any],
    attachment_type: str = "EVIDENCE",
    description: str | None = None,
) -> str:
    file_name = str(
        drive_result.get("file_name") or ""
    ).strip()

    file_url = str(
        drive_result.get("file_url") or ""
    ).strip()

    mime_type = str(
        drive_result.get("mime_type") or ""
    ).strip()

    file_size_raw = drive_result.get(
        "file_size"
    )

    file_size: int | None = None

    if isinstance(
        file_size_raw,
        (int, float),
    ):
        file_size = int(file_size_raw)

    if not file_name:
        raise RuntimeError(
            "Nama file Drive kosong."
        )

    if not file_url:
        raise RuntimeError(
            "URL file Drive kosong."
        )

    payload: dict[str, Any] = {
        "event_id": event_id,
        "file_name": file_name,
        "file_path": file_url,
        "file_type": mime_type or None,
        "file_size": file_size,
        "attachment_type": attachment_type,
        "description": description,
    }

    supabase = get_supabase_client()

    response = (
        supabase
        .table("trx_kejadian_attachment")
        .insert(payload)
        .execute()
    )

    data: Any = response.data

    if (
        not isinstance(data, list)
        or not data
    ):
        raise RuntimeError(
            "Metadata attachment tidak berhasil disimpan."
        )

    first_row: Any = data[0]

    if not isinstance(first_row, dict):
        raise RuntimeError(
            "Response metadata attachment tidak valid."
        )

    row = cast(
        dict[str, Any],
        first_row,
    )

    return str(
        row.get("attachment_id")
        or ""
    )


def upload_evidence_files(
    *,
    uploaded_files: list[Any] | None,
    event_id: str,
    event_type: str,
    hierarchy: dict[str, Any],
    event_date: str,
    event_time: str,
    cause_name: str,
) -> tuple[int, list[str]]:
    if not uploaded_files:
        return 0, []

    success_count = 0
    errors: list[str] = []

    for uploaded_file in uploaded_files:
        file_name = str(
            getattr(
                uploaded_file,
                "name",
                "evidence",
            )
            or "evidence"
        )

        try:
            result = upload_file_to_drive(
                uploaded_file=uploaded_file,
                event_id=event_id,
                event_type=event_type,
                hierarchy=hierarchy,
                event_date=event_date,
                event_time=event_time,
                cause_name=cause_name,
            )

            save_attachment_metadata(
                event_id=event_id,
                drive_result=result,
                attachment_type="EVIDENCE",
            )

            success_count += 1

        except Exception as exc:
            errors.append(
                f"{file_name}: {exc}"
            )

    return success_count, errors