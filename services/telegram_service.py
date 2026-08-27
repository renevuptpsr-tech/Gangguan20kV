from __future__ import annotations

from typing import Any, cast

import httpx
import streamlit as st

from services.supabase_client import (
    get_supabase_client,
)


TELEGRAM_TEMPLATE_VERSION = "2026.08.24-v4-gangguan-frequency"


# ==========================================================
# CONFIG
# ==========================================================


def _get_telegram_config() -> tuple[str, str]:
    try:
        config = st.secrets["telegram"]

    except Exception as exc:
        raise RuntimeError(
            "Konfigurasi [telegram] belum tersedia "
            "di .streamlit/secrets.toml."
        ) from exc

    bot_token = str(
        config.get(
            "bot_token",
            "",
        )
    ).strip()

    chat_id = str(
        config.get(
            "chat_id",
            "",
        )
    ).strip()

    if not bot_token:
        raise RuntimeError(
            "telegram.bot_token belum diisi."
        )

    if not chat_id:
        raise RuntimeError(
            "telegram.chat_id belum diisi."
        )

    return (
        bot_token,
        chat_id,
    )


# ==========================================================
# GENERIC HELPERS
# ==========================================================


def _escape_html(
    value: Any,
) -> str:
    text = str(
        value
        if value is not None
        else "-"
    )

    return (
        text
        .replace(
            "&",
            "&amp;",
        )
        .replace(
            "<",
            "&lt;",
        )
        .replace(
            ">",
            "&gt;",
        )
    )


def _safe_text(
    value: Any,
    default: str = "-",
) -> str:
    if value is None:
        return default

    text = str(
        value
    ).strip()

    return (
        text
        if text
        else default
    )


def _format_number(
    value: Any,
    unit: str = "",
) -> str:
    if value is None:
        return "-"

    try:
        number = float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return _escape_html(
            value
        )

    formatted = (
        f"{number:,.2f}"
        .replace(
            ",",
            "_",
        )
        .replace(
            ".",
            ",",
        )
        .replace(
            "_",
            ".",
        )
    )

    return (
        f"{formatted} {unit}"
        .strip()
    )


# ==========================================================
# PENYULANG AREA / WILAYAH
# ==========================================================


def _optional_float(
    value: Any,
) -> float | None:
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


def _three_phase_current_values(
    payload: dict[str, Any],
    *,
    prefix: str,
    legacy_field: str,
) -> tuple[
    float | None,
    float | None,
    float | None,
]:
    """
    Membaca arus R/S/T.

    Jika payload lama belum membawa field phasa, fallback ke
    nilai legacy single-current agar notifikasi lama tetap aman.
    """

    current_r = _optional_float(
        payload.get(
            f"{prefix}_r_a"
        )
    )

    current_s = _optional_float(
        payload.get(
            f"{prefix}_s_a"
        )
    )

    current_t = _optional_float(
        payload.get(
            f"{prefix}_t_a"
        )
    )

    legacy = _optional_float(
        payload.get(
            legacy_field
        )
    )

    if (
        current_r is None
        and current_s is None
        and current_t is None
        and legacy is not None
    ):
        return (
            legacy,
            legacy,
            legacy,
        )

    return (
        current_r,
        current_s,
        current_t,
    )


def _format_three_phase_current(
    payload: dict[str, Any],
    *,
    prefix: str,
    legacy_field: str,
) -> str:
    """
    Format singkat arus R/S/T untuk Telegram.

    Contoh:
        R 102,00 A | S 98,00 A | T 100,00 A
    """

    current_r, current_s, current_t = (
        _three_phase_current_values(
            payload,
            prefix=prefix,
            legacy_field=legacy_field,
        )
    )

    return (
        f"R {_format_number(current_r, 'A')} "
        f"| S {_format_number(current_s, 'A')} "
        f"| T {_format_number(current_t, 'A')}"
    )




def _has_three_phase_or_legacy_current(
    payload: dict[str, Any],
    *,
    prefix: str,
    legacy_field: str,
) -> bool:
    """
    True bila minimal ada satu nilai arus R/S/T atau legacy.
    """

    return any(
        payload.get(
            field
        )
        is not None
        for field in (
            f"{prefix}_r_a",
            f"{prefix}_s_a",
            f"{prefix}_t_a",
            legacy_field,
        )
    )


def _build_maneuver_current_lines(
    payload: dict[str, Any],
    *,
    bullet: str = "• ",
) -> list[str]:
    """
    Menyusun informasi beban termanuver dan sisa beban.

    - MANUVER_PENUH: tampilkan beban termanuver R/S/T.
    - MANUVER_SEBAGIAN: tampilkan termanuver + sisa R/S/T.
    - Data lama fallback ke field legacy single-current.
    """

    supply_status = str(
        payload.get(
            "supply_status_code"
        )
        or ""
    ).strip().upper()

    if supply_status not in {
        "MANUVER_PENUH",
        "MANUVER_SEBAGIAN",
    }:
        return []

    lines: list[str] = []

    if _has_three_phase_or_legacy_current(
        payload,
        prefix="maneuvered_current",
        legacy_field="maneuvered_current_a",
    ):
        lines.append(
            (
                f"{bullet}Beban Termanuver: "
                + _format_three_phase_current(
                    payload,
                    prefix="maneuvered_current",
                    legacy_field="maneuvered_current_a",
                )
            )
        )

    if (
        supply_status
        == "MANUVER_SEBAGIAN"
        and _has_three_phase_or_legacy_current(
            payload,
            prefix="remaining_current",
            legacy_field="remaining_current_a",
        )
    ):
        lines.append(
            (
                f"{bullet}Sisa Beban: "
                + _format_three_phase_current(
                    payload,
                    prefix="remaining_current",
                    legacy_field="remaining_current_a",
                )
            )
        )

    return lines


def _enrich_hierarchy_with_area(
    hierarchy: dict[str, Any],
) -> dict[str, Any]:
    """
    Menambahkan data wilayah penyulang dari
    vw_penyulang_hierarchy_accessible.

    Field:
    - wilayah_penyaluran
    - up3_code
    - ulp_code

    Query hanya dilakukan apabila field belum tersedia
    pada hierarchy yang dikirim dari selector.
    """

    result = dict(
        hierarchy
    )

    required_fields = (
        "wilayah_penyaluran",
        "up3_code",
        "ulp_code",
    )

    if all(
        str(
            result.get(
                field_name
            )
            or ""
        ).strip()
        for field_name in required_fields
    ):
        return result

    penyulang_id = str(
        result.get(
            "penyulang_id"
        )
        or ""
    ).strip()

    if not penyulang_id:
        return result

    try:
        supabase = (
            get_supabase_client()
        )

        response = (
            supabase
            .table(
                "vw_penyulang_hierarchy_accessible"
            )
            .select(
                "wilayah_penyaluran,"
                "up3_code,"
                "ulp_code"
            )
            .eq(
                "penyulang_id",
                penyulang_id,
            )
            .limit(
                1
            )
            .execute()
        )

        rows = cast(
            list[dict[str, Any]],
            response.data
            or [],
        )

        if not rows:
            return result

        area_row = rows[
            0
        ]

        for field_name in required_fields:
            current_value = str(
                result.get(
                    field_name
                )
                or ""
            ).strip()

            if current_value:
                continue

            result[
                field_name
            ] = (
                area_row.get(
                    field_name
                )
            )

    except Exception:
        # Informasi wilayah bersifat tambahan.
        # Kegagalan query wilayah tidak boleh membatalkan
        # notifikasi utama Telegram.
        return result

    return result


def _build_affected_area_lines(
    hierarchy: dict[str, Any],
) -> list[str]:
    wilayah_penyaluran = (
        _safe_text(
            hierarchy.get(
                "wilayah_penyaluran"
            )
        )
    )

    ulp_code = (
        _safe_text(
            hierarchy.get(
                "ulp_code"
            )
        )
    )

    up3_code = (
        _safe_text(
            hierarchy.get(
                "up3_code"
            )
        )
    )

    return [
        "",
        "🌐 <b>Wilayah Terdampak</b>",
        (
            "• Wilayah Penyaluran: "
            f"{_escape_html(wilayah_penyaluran)}"
        ),
        (
            "• ULP / UP3: "
            f"{_escape_html(ulp_code)} / "
            f"{_escape_html(up3_code)}"
        ),
    ]


# ==========================================================
# FREKUENSI GANGGUAN HARIAN / BULANAN
# ==========================================================


OGF_INDICATION_CODES: set[str] = {
    "OCR_INST",
    "OCR_TD",
    "GFR_INST",
    "GFR_TD",
}


def _date_ranges(
    event_date_value: Any,
) -> tuple[str, str, str] | None:
    """
    Menghasilkan:
    - tanggal kejadian
    - awal bulan
    - awal bulan berikutnya

    Format ISO YYYY-MM-DD.
    """

    from datetime import date as date_type

    text = str(
        event_date_value
        or ""
    ).strip()

    if not text:
        return None

    try:
        event_date = date_type.fromisoformat(
            text[:10]
        )

    except ValueError:
        return None

    month_start = date_type(
        event_date.year,
        event_date.month,
        1,
    )

    if event_date.month == 12:
        next_month_start = date_type(
            event_date.year + 1,
            1,
            1,
        )

    else:
        next_month_start = date_type(
            event_date.year,
            event_date.month + 1,
            1,
        )

    return (
        event_date.isoformat(),
        month_start.isoformat(),
        next_month_start.isoformat(),
    )


def _classify_disturbance(
    indication_codes: set[str],
) -> str:
    """
    Klasifikasi eksklusif untuk monitoring frekuensi:

    OGF
        Jika event mempunyai minimal satu indikasi:
        OCR INST / OCR TD / GFR INST / GFR TD.

    SYSTEM
        Gangguan lainnya, termasuk UFR/UVLS, OLS, RTN,
        atau gangguan tanpa indikasi OCR/GFR.

    Jika satu event memiliki OCR/GFR sekaligus UFR/OLS,
    event dihitung sebagai OGF agar satu event tidak dihitung ganda.
    """

    normalized = {
        str(
            code
        ).strip().upper()
        for code in indication_codes
        if str(
            code
        ).strip()
    }

    if normalized.intersection(
        OGF_INDICATION_CODES
    ):
        return "OGF"

    return "SYSTEM"


def _load_disturbance_frequency(
    *,
    penyulang_id: str,
    event_date_value: Any,
) -> dict[str, int]:
    """
    Menghitung frekuensi Gangguan pada PENYULANG YANG SAMA.

    Harian:
        seluruh event GANGGUAN pada tanggal kejadian.

    Bulanan:
        seluruh event GANGGUAN sejak tanggal 1 sampai
        sebelum tanggal 1 bulan berikutnya.

    Deleted event tidak dihitung.
    """

    result = {
        "daily_total": 0,
        "daily_ogf": 0,
        "daily_system": 0,
        "monthly_total": 0,
        "monthly_ogf": 0,
        "monthly_system": 0,
    }

    penyulang_id_text = str(
        penyulang_id
        or ""
    ).strip()

    ranges = _date_ranges(
        event_date_value
    )

    if (
        not penyulang_id_text
        or ranges is None
    ):
        return result

    event_date, month_start, next_month_start = ranges

    try:
        supabase = get_supabase_client()

        response = (
            supabase
            .table(
                "trx_kejadian_penyulang"
            )
            .select(
                "event_id,event_date"
            )
            .eq(
                "penyulang_id",
                penyulang_id_text,
            )
            .eq(
                "event_type_code",
                "GANGGUAN",
            )
            .eq(
                "is_deleted",
                False,
            )
            .gte(
                "event_date",
                month_start,
            )
            .lt(
                "event_date",
                next_month_start,
            )
            .execute()
        )

        event_rows = cast(
            list[dict[str, Any]],
            response.data
            or [],
        )

        if not event_rows:
            return result

        event_ids = [
            str(
                row.get(
                    "event_id"
                )
                or ""
            ).strip()
            for row in event_rows
            if str(
                row.get(
                    "event_id"
                )
                or ""
            ).strip()
        ]

        indications_by_event: dict[
            str,
            set[str],
        ] = {
            event_id: set()
            for event_id in event_ids
        }

        if event_ids:
            indication_response = (
                supabase
                .table(
                    "trx_kejadian_indikasi"
                )
                .select(
                    "event_id,indikasi_code"
                )
                .in_(
                    "event_id",
                    event_ids,
                )
                .execute()
            )

            indication_rows = cast(
                list[dict[str, Any]],
                indication_response.data
                or [],
            )

            for indication in indication_rows:
                indication_event_id = str(
                    indication.get(
                        "event_id"
                    )
                    or ""
                ).strip()

                indication_code = str(
                    indication.get(
                        "indikasi_code"
                    )
                    or ""
                ).strip().upper()

                if (
                    indication_event_id
                    in indications_by_event
                    and indication_code
                ):
                    indications_by_event[
                        indication_event_id
                    ].add(
                        indication_code
                    )

        for event_row in event_rows:
            event_id = str(
                event_row.get(
                    "event_id"
                )
                or ""
            ).strip()

            event_date_row = str(
                event_row.get(
                    "event_date"
                )
                or ""
            ).strip()[:10]

            disturbance_class = (
                _classify_disturbance(
                    indications_by_event.get(
                        event_id,
                        set(),
                    )
                )
            )

            result[
                "monthly_total"
            ] += 1

            if disturbance_class == "OGF":
                result[
                    "monthly_ogf"
                ] += 1

            else:
                result[
                    "monthly_system"
                ] += 1

            if event_date_row == event_date:
                result[
                    "daily_total"
                ] += 1

                if disturbance_class == "OGF":
                    result[
                        "daily_ogf"
                    ] += 1

                else:
                    result[
                        "daily_system"
                    ] += 1

    except Exception:
        # Statistik bersifat tambahan.
        # Kegagalan query tidak boleh menggagalkan notifikasi Telegram.
        return result

    return result


def _build_disturbance_frequency_lines(
    frequency: dict[str, int],
) -> list[str]:
    return [
        "",
        "📊 <b>Frekuensi Gangguan Penyulang</b>",
        "• Hari ini:",
        (
            "  ├ OGF (OCR/GFR): "
            f"<b>{int(frequency.get('daily_ogf', 0))} kali</b>"
        ),
        (
            "  └ Sistem/Lainnya: "
            f"<b>{int(frequency.get('daily_system', 0))} kali</b>"
        ),
        "• Bulan ini:",
        (
            "  ├ OGF (OCR/GFR): "
            f"<b>{int(frequency.get('monthly_ogf', 0))} kali</b>"
        ),
        (
            "  └ Sistem/Lainnya: "
            f"<b>{int(frequency.get('monthly_system', 0))} kali</b>"
        ),
    ]


# ==========================================================
# TELEGRAM MESSAGE
# ==========================================================


def send_telegram_message(
    message: str,
) -> None:
    bot_token, chat_id = (
        _get_telegram_config()
    )

    url = (
        "https://api.telegram.org/"
        f"bot{bot_token}/sendMessage"
    )

    try:
        with httpx.Client(
            timeout=10.0
        ) as client:
            response = (
                client.post(
                    url,
                    json={
                        "chat_id":
                            chat_id,

                        "text":
                            message,

                        "parse_mode":
                            "HTML",

                        "disable_web_page_preview":
                            True,
                    },
                )
            )

            response.raise_for_status()

            data: Any = (
                response.json()
            )

    except Exception as exc:
        raise RuntimeError(
            f"Gagal mengirim Telegram: {exc}"
        ) from exc

    if (
        not isinstance(
            data,
            dict,
        )
        or not data.get(
            "ok"
        )
    ):
        raise RuntimeError(
            "Telegram API tidak mengembalikan status OK."
        )


# ==========================================================
# TELEGRAM ATTACHMENT
# ==========================================================


def send_telegram_attachment(
    *,
    uploaded_file: Any,
    caption: str | None = None,
) -> None:
    bot_token, chat_id = (
        _get_telegram_config()
    )

    file_name = str(
        getattr(
            uploaded_file,
            "name",
            "evidence",
        )
        or "evidence"
    ).strip()

    content_type = str(
        getattr(
            uploaded_file,
            "type",
            "",
        )
        or ""
    ).lower()

    file_bytes = (
        uploaded_file.getvalue()
    )

    if not file_bytes:
        raise RuntimeError(
            f"File {file_name} kosong."
        )

    is_photo = (
        content_type
        in {
            "image/jpeg",
            "image/jpg",
            "image/png",
        }
        or file_name.lower().endswith(
            (
                ".jpg",
                ".jpeg",
                ".png",
            )
        )
    )

    endpoint = (
        "sendPhoto"
        if is_photo
        else "sendDocument"
    )

    file_field = (
        "photo"
        if is_photo
        else "document"
    )

    url = (
        "https://api.telegram.org/"
        f"bot{bot_token}/{endpoint}"
    )

    data: dict[str, str] = {
        "chat_id":
            chat_id,
    }

    if caption:
        data[
            "caption"
        ] = caption

        data[
            "parse_mode"
        ] = "HTML"

    try:
        with httpx.Client(
            timeout=25.0
        ) as client:
            response = (
                client.post(
                    url,
                    data=data,
                    files={
                        file_field: (
                            file_name,
                            file_bytes,
                            content_type
                            or "application/octet-stream",
                        )
                    },
                )
            )

            response.raise_for_status()

            result: Any = (
                response.json()
            )

    except Exception as exc:
        raise RuntimeError(
            f"Gagal mengirim file {file_name}: {exc}"
        ) from exc

    if (
        not isinstance(
            result,
            dict,
        )
        or not result.get(
            "ok"
        )
    ):
        raise RuntimeError(
            f"Telegram tidak menerima file {file_name}."
        )


def send_telegram_attachments(
    *,
    uploaded_files: list[Any] | None,
    event_id: str,
) -> tuple[int, list[str]]:
    if not uploaded_files:
        return (
            0,
            [],
        )

    success_count = 0
    errors: list[str] = []

    total = len(
        uploaded_files
    )

    for index, uploaded_file in enumerate(
        uploaded_files,
        start=1,
    ):
        file_name = str(
            getattr(
                uploaded_file,
                "name",
                "evidence",
            )
            or "evidence"
        )

        caption = (
            f"📎 <b>Evidence {index}/{total}</b>\n"
            f"🆔 <code>{_escape_html(event_id)}</code>\n"
            f"📄 {_escape_html(file_name)}"
        )

        try:
            send_telegram_attachment(
                uploaded_file=(
                    uploaded_file
                ),
                caption=(
                    caption
                ),
            )

            success_count += 1

        except Exception as exc:
            errors.append(
                str(
                    exc
                )
            )

    return (
        success_count,
        errors,
    )


# ==========================================================
# EVENT MESSAGE
# ==========================================================


def build_event_message(
    *,
    event_id: str,
    event_type: str,
    hierarchy: dict[str, Any],
    payload: dict[str, Any],
    cause_name: str | None = None,
    pic_name: str | None = None,
    annunciator_name: str | None = None,
    indication_names: list[str] | None = None,
    disturbance_frequency: dict[str, int] | None = None,
) -> str:
    is_gangguan = (
        str(
            event_type
        ).upper()
        == "GANGGUAN"
    )

    title = (
        "⚡ <b>GANGGUAN PENYULANG 20 kV</b>"
        if is_gangguan
        else "🔄 <b>MANUVER PENYULANG 20 kV</b>"
    )

    lines: list[str] = [
        title,
        "",
        (
            "🏢 <b>ULTG:</b> "
            f"{_escape_html(hierarchy.get('ultg_name') or '-')}"
        ),
        (
            "🏭 <b>GI:</b> "
            f"{_escape_html(hierarchy.get('gi_name') or '-')}"
        ),
        (
            "🔌 <b>Bay:</b> "
            f"{_escape_html(hierarchy.get('bay_name') or '-')}"
        ),
        (
            "📍 <b>Penyulang:</b> "
            f"{_escape_html(hierarchy.get('penyulang_code') or '-')} — "
            f"{_escape_html(hierarchy.get('penyulang_name') or '-')}"
        ),
        "",
        "👥 <b>Petugas Operasi</b>",
        (
            "• Operator: "
            f"{_escape_html(payload.get('operator_name') or '-')}"
        ),
        (
            "• Dispatcher UP2D: "
            f"{_escape_html(payload.get('dispatcher_up2d_name') or '-')}"
        ),
        (
            "• Diinput Oleh: "
            f"{_escape_html(payload.get('created_by_name') or payload.get('input_user_name') or '-')}"
        ),
        "",
        (
            "🗓️ <b>Waktu:</b> "
            f"{_escape_html(payload.get('event_date') or '-')} "
            f"{_escape_html(payload.get('event_time') or '-')}"
        ),
        (
            "⚙️ <b>Status PMT:</b> "
            f"{_escape_html(payload.get('pmt_status_code') or '-')}"
        ),
        (
            "👤 <b>PIC:</b> "
            f"{_escape_html(pic_name or payload.get('pic_code') or '-')}"
        ),
        (
            "📝 <b>Klasifikasi:</b> "
            f"{_escape_html(cause_name or payload.get('cause_code') or '-')}"
        ),
        (
            "📈 <b>Arus Beban Sebelum:</b> "
            + _format_three_phase_current(
                payload,
                prefix="load_current_before",
                legacy_field="load_current_before_a",
            )
        ),
        (
            "⚡ <b>Tegangan:</b> "
            f"{_format_number(payload.get('voltage_before_kv'), 'kV')}"
        ),
    ]

    lines.extend(
        _build_affected_area_lines(
            hierarchy
        )
    )

    if (
        is_gangguan
        and disturbance_frequency is not None
    ):
        lines.extend(
            _build_disturbance_frequency_lines(
                disturbance_frequency
            )
        )

    if is_gangguan:
        phases: list[str] = []

        for phase in (
            "r",
            "s",
            "t",
            "n",
        ):
            if payload.get(
                f"phase_{phase}"
            ):
                phases.append(
                    phase.upper()
                )

        lines.extend(
            [
                "",
                "🛡️ <b>Proteksi</b>",
                (
                    "• Annunciator: "
                    f"{_escape_html(annunciator_name or payload.get('annunciator_code') or '-')}"
                ),
                (
                    "• Indikasi: "
                    f"{_escape_html(', '.join(indication_names or []) or '-')}"
                ),
                (
                    "• Phasa: "
                    f"{_escape_html('/'.join(phases) or '-')}"
                ),
                (
                    "• I-R: "
                    f"{_format_number(payload.get('fault_current_r_a'), 'A')}"
                ),
                (
                    "• I-S: "
                    f"{_format_number(payload.get('fault_current_s_a'), 'A')}"
                ),
                (
                    "• I-T: "
                    f"{_format_number(payload.get('fault_current_t_a'), 'A')}"
                ),
                (
                    "• I-N: "
                    f"{_format_number(payload.get('fault_current_n_a'), 'A')}"
                ),
            ]
        )

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
            supply_datetime = (
                f"{payload.get('supply_restored_date') or '-'} "
                f"{payload.get('supply_restored_time') or '-'}"
            ).strip()

            recovery_datetime = (
                f"{payload.get('recovery_date') or '-'} "
                f"{payload.get('recovery_time') or '-'}"
            ).strip()

            lines.extend(
                [
                    "",
                    "✅ <b>Pemulihan / Normalisasi</b>",
                    (
                        "• Status Suplai: "
                        f"{_escape_html(payload.get('supply_status_code') or '-')}"
                    ),
                    (
                        "• Mulai Tersuplai: "
                        f"{_escape_html(supply_datetime)}"
                    ),
                ]
            )

            lines.extend(
                _build_maneuver_current_lines(
                    payload,
                    bullet="• ",
                )
            )

            lines.extend(
                [
                    (
                        "• Status PMT Akhir: "
                        f"{_escape_html(payload.get('recovery_status_code') or '-')}"
                    ),
                    (
                        "• Waktu Operasi PMT: "
                        f"{_escape_html(recovery_datetime)}"
                    ),
                    (
                        "• Counter PMT: "
                        f"{_escape_html(payload.get('pmt_counter_after') if payload.get('pmt_counter_after') is not None else '-')}"
                    ),
                    (
                        "• Arus Setelah: "
                        + _format_three_phase_current(
                            payload,
                            prefix="load_current_after",
                            legacy_field="load_current_after_a",
                        )
                    ),
                    (
                        "• Tegangan Setelah: "
                        f"{_format_number(payload.get('voltage_after_kv'), 'kV')}"
                    ),
                ]
            )

            recovery_description = str(
                payload.get(
                    "recovery_description"
                )
                or ""
            ).strip()

            if recovery_description:
                lines.extend(
                    [
                        "",
                        "📝 <b>Keterangan Pemulihan:</b>",
                        _escape_html(
                            recovery_description
                        ),
                    ]
                )

    if not is_gangguan:
        maneuver_lines = (
            _build_maneuver_current_lines(
                payload,
                bullet="• ",
            )
        )

        if maneuver_lines:
            lines.extend(
                [
                    "",
                    "🔄 <b>Data Manuver Beban</b>",
                ]
            )

            lines.extend(
                maneuver_lines
            )

            supply_datetime = (
                f"{payload.get('supply_restored_date') or '-'} "
                f"{payload.get('supply_restored_time') or '-'}"
            ).strip()

            if str(
                payload.get(
                    "supply_status_code"
                )
                or ""
            ).strip().upper() != "BELUM":
                lines.append(
                    (
                        "• Mulai Tersuplai: "
                        f"{_escape_html(supply_datetime)}"
                    )
                )

    description = payload.get(
        "event_description"
    )

    if description:
        lines.extend(
            [
                "",
                "📄 <b>Keterangan:</b>",
                _escape_html(
                    description
                ),
            ]
        )

    lines.extend(
        [
            "",
            (
                "🆔 <b>Event ID:</b> "
                f"<code>{_escape_html(event_id)}</code>"
            ),
        ]
    )

    return "\n".join(
        lines
    )


def send_event_notification(
    *,
    event_id: str,
    event_type: str,
    hierarchy: dict[str, Any],
    payload: dict[str, Any],
    cause_name: str | None = None,
    pic_name: str | None = None,
    annunciator_name: str | None = None,
    indication_names: list[str] | None = None,
    uploaded_files: list[Any] | None = None,
) -> tuple[bool, str]:
    try:
        enriched_hierarchy = (
            _enrich_hierarchy_with_area(
                hierarchy
            )
        )

        disturbance_frequency: dict[str, int] | None = None

        if str(
            event_type
        ).upper() == "GANGGUAN":
            disturbance_frequency = (
                _load_disturbance_frequency(
                    penyulang_id=str(
                        enriched_hierarchy.get(
                            "penyulang_id"
                        )
                        or payload.get(
                            "penyulang_id"
                        )
                        or ""
                    ),
                    event_date_value=(
                        payload.get(
                            "event_date"
                        )
                    ),
                )
            )

        message = (
            build_event_message(
                event_id=(
                    event_id
                ),
                event_type=(
                    event_type
                ),
                hierarchy=(
                    enriched_hierarchy
                ),
                payload=(
                    payload
                ),
                cause_name=(
                    cause_name
                ),
                pic_name=(
                    pic_name
                ),
                annunciator_name=(
                    annunciator_name
                ),
                indication_names=(
                    indication_names
                ),
                disturbance_frequency=(
                    disturbance_frequency
                ),
            )
        )

        send_telegram_message(
            message
        )

        count, errors = (
            send_telegram_attachments(
                uploaded_files=(
                    uploaded_files
                ),
                event_id=(
                    event_id
                ),
            )
        )

        if errors:
            return (
                False,
                (
                    "Teks Telegram berhasil, tetapi "
                    f"{len(errors)} evidence gagal. "
                    + " | ".join(
                        errors
                    )
                ),
            )

        if count > 0:
            return (
                True,
                (
                    f"Notifikasi Telegram dan {count} "
                    "evidence berhasil dikirim."
                ),
            )

        return (
            True,
            "Notifikasi Telegram berhasil dikirim.",
        )

    except Exception as exc:
        return (
            False,
            str(
                exc
            ),
        )


# ==========================================================
# RECOVERY MESSAGE
# ==========================================================


def build_recovery_message(
    *,
    event_id: str,
    event_row: dict[str, Any],
    recovery_payload: dict[str, Any],
) -> str:
    lines: list[str] = [
        "✅ <b>PEMULIHAN / NORMALISASI PENYULANG 20 kV</b>",
        "",
        (
            "🏢 <b>ULTG:</b> "
            f"{_escape_html(event_row.get('ultg_name') or '-')}"
        ),
        (
            "🏭 <b>GI:</b> "
            f"{_escape_html(event_row.get('gi_name') or '-')}"
        ),
        (
            "🔌 <b>Bay:</b> "
            f"{_escape_html(event_row.get('bay_name') or '-')}"
        ),
        (
            "📍 <b>Penyulang:</b> "
            f"{_escape_html(event_row.get('penyulang_code') or '-')} — "
            f"{_escape_html(event_row.get('penyulang_name') or '-')}"
        ),
    ]

    lines.extend(
        _build_affected_area_lines(
            event_row
        )
    )

    lines.extend(
        [
            "",
            "👥 <b>Petugas Operasi</b>",
            (
                "• Operator: "
                f"{_escape_html(event_row.get('operator_name') or '-')}"
            ),
            (
                "• Dispatcher UP2D: "
                f"{_escape_html(event_row.get('dispatcher_up2d_name') or '-')}"
            ),
            (
                "• Diinput Oleh: "
                f"{_escape_html(event_row.get('created_by_name') or '-')}"
            ),
            "",
            (
                "🔋 <b>Status Suplai:</b> "
                f"{_escape_html(recovery_payload.get('supply_status_code') or '-')}"
            ),
        ]
    )

    lines.extend(
        _build_maneuver_current_lines(
            recovery_payload,
            bullet="• ",
        )
    )

    lines.extend(
        [
            (
                "⚙️ <b>Status PMT:</b> "
                f"{_escape_html(recovery_payload.get('recovery_status_code') or '-')}"
            ),
            (
                "📈 <b>Arus Setelah:</b> "
                + _format_three_phase_current(
                    recovery_payload,
                    prefix="load_current_after",
                    legacy_field="load_current_after_a",
                )
            ),
            (
                "⚡ <b>Tegangan Setelah:</b> "
                f"{_format_number(recovery_payload.get('voltage_after_kv'), 'kV')}"
            ),
            (
                "🔢 <b>Counter PMT:</b> "
                f"{_escape_html(recovery_payload.get('pmt_counter_after') if recovery_payload.get('pmt_counter_after') is not None else '-')}"
            ),
            "",
            "📝 <b>Keterangan Pemulihan:</b>",
            _escape_html(
                recovery_payload.get(
                    "recovery_description"
                )
                or "-"
            ),
            "",
            (
                "🆔 <b>Event ID:</b> "
                f"<code>{_escape_html(event_id)}</code>"
            ),
        ]
    )

    return "\n".join(
        lines
    )


def send_recovery_notification(
    *,
    event_id: str,
    event_row: dict[str, Any],
    recovery_payload: dict[str, Any],
    uploaded_files: list[Any] | None = None,
) -> tuple[bool, str]:
    try:
        enriched_event_row = (
            _enrich_hierarchy_with_area(
                event_row
            )
        )

        message = (
            build_recovery_message(
                event_id=(
                    event_id
                ),
                event_row=(
                    enriched_event_row
                ),
                recovery_payload=(
                    recovery_payload
                ),
            )
        )

        send_telegram_message(
            message
        )

        count, errors = (
            send_telegram_attachments(
                uploaded_files=(
                    uploaded_files
                ),
                event_id=(
                    event_id
                ),
            )
        )

        if errors:
            return (
                False,
                (
                    "Notifikasi pemulihan berhasil, tetapi "
                    f"{len(errors)} evidence gagal. "
                    + " | ".join(
                        errors
                    )
                ),
            )

        if count > 0:
            return (
                True,
                (
                    f"Notifikasi pemulihan dan {count} "
                    "evidence berhasil dikirim."
                ),
            )

        return (
            True,
            "Notifikasi pemulihan Telegram berhasil dikirim.",
        )

    except Exception as exc:
        return (
            False,
            str(
                exc
            ),
        )