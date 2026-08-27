from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

import streamlit as st

from services.supabase_client import get_supabase_client


EventPayload = dict[str, Any]
EventRow = dict[str, Any]


# ==========================================================
# THREE-PHASE FIELD DEFINITIONS
# ==========================================================

_BEFORE_PHASE_FIELDS = (
    "load_current_before_r_a",
    "load_current_before_s_a",
    "load_current_before_t_a",
)

_AFTER_PHASE_FIELDS = (
    "load_current_after_r_a",
    "load_current_after_s_a",
    "load_current_after_t_a",
)

_MANEUVERED_PHASE_FIELDS = (
    "maneuvered_current_r_a",
    "maneuvered_current_s_a",
    "maneuvered_current_t_a",
)

_REMAINING_PHASE_FIELDS = (
    "remaining_current_r_a",
    "remaining_current_s_a",
    "remaining_current_t_a",
)

_LEGACY_BEFORE_FIELD = (
    "load_current_before_a"
)

_LEGACY_AFTER_FIELD = (
    "load_current_after_a"
)

_LEGACY_MANEUVERED_FIELD = (
    "maneuvered_current_a"
)

_LEGACY_REMAINING_FIELD = (
    "remaining_current_a"
)


# ==========================================================
# GENERIC HELPERS
# ==========================================================


def _as_event_rows(
    data: Any,
) -> list[EventRow]:
    """
    Normalisasi response Supabase menjadi list[dict]
    agar aman untuk Pylance.
    """

    if not isinstance(
        data,
        list,
    ):
        return []

    rows: list[EventRow] = []

    for item in data:
        if isinstance(
            item,
            dict,
        ):
            rows.append(
                cast(
                    EventRow,
                    item,
                )
            )

    return rows


def _optional_float(
    value: Any,
) -> float | None:
    """
    Konversi nilai menjadi float opsional.
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

    text = str(
        value
    ).strip()

    if not text:
        return None

    try:
        return float(
            text.replace(
                ",",
                ".",
            )
        )

    except ValueError:
        return None


def _three_phase_average(
    current_r: float | None,
    current_s: float | None,
    current_t: float | None,
) -> float | None:
    """
    Iavg = (IR + IS + IT) / 3

    Nilai rata-rata hanya dihitung jika ketiga phasa tersedia.
    """

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


def _normalize_three_phase_group(
    payload: EventPayload,
    *,
    phase_fields: tuple[str, str, str],
    legacy_field: str,
) -> None:
    """
    Normalisasi satu kelompok arus R/S/T.

    Aturan:
    1. Jika R/S/T lengkap:
       - legacy field otomatis diisi rata-rata R/S/T.

    2. Jika R/S/T tidak dikirim tetapi legacy field dikirim:
       - legacy diteruskan;
       - R/S/T diisi dengan nilai legacy untuk kompatibilitas data lama.

    3. Jika hanya sebagian R/S/T diisi:
       - payload tidak dipaksakan menjadi lengkap.
       - validasi form / constraint database yang menentukan apakah valid.

    Catatan:
    Trigger database tetap menjadi sinkronisasi terakhir.
    """

    phase_values = [
        _optional_float(
            payload.get(
                field
            )
        )
        for field in phase_fields
    ]

    phase_keys_present = any(
        field in payload
        for field in phase_fields
    )

    legacy_present = (
        legacy_field in payload
    )

    legacy_value = _optional_float(
        payload.get(
            legacy_field
        )
    )

    complete_three_phase = all(
        value is not None
        for value in phase_values
    )

    if complete_three_phase:
        current_r = cast(
            float,
            phase_values[0],
        )

        current_s = cast(
            float,
            phase_values[1],
        )

        current_t = cast(
            float,
            phase_values[2],
        )

        average = _three_phase_average(
            current_r,
            current_s,
            current_t,
        )

        payload[
            phase_fields[0]
        ] = current_r

        payload[
            phase_fields[1]
        ] = current_s

        payload[
            phase_fields[2]
        ] = current_t

        payload[
            legacy_field
        ] = average

        return

    if (
        not phase_keys_present
        and legacy_present
    ):
        payload[
            legacy_field
        ] = legacy_value

        if legacy_value is not None:
            payload[
                phase_fields[0]
            ] = legacy_value

            payload[
                phase_fields[1]
            ] = legacy_value

            payload[
                phase_fields[2]
            ] = legacy_value

        return

    # Jika payload memang membawa phase fields tetapi tidak lengkap,
    # pertahankan apa adanya. Jangan menebak nilai phasa yang hilang.
    for field, value in zip(
        phase_fields,
        phase_values,
        strict=True,
    ):
        if field in payload:
            payload[
                field
            ] = value

    if legacy_present:
        payload[
            legacy_field
        ] = legacy_value


def _normalize_event_payload(
    payload: EventPayload,
) -> EventPayload:
    """
    Menyalin dan menormalisasi payload event.

    Fungsi ini menjadi satu titik kompatibilitas antara:
    - arus beban sebelum operasi R/S/T;
    - arus beban setelah operasi R/S/T;
    - arus berhasil dimanuver R/S/T;
    - arus sisa belum tersuplai R/S/T;
    - field legacy single-current/rata-rata;
    - service lama yang belum seluruhnya dimigrasikan.
    """

    normalized: EventPayload = dict(
        payload
    )

    _normalize_three_phase_group(
        normalized,
        phase_fields=(
            _BEFORE_PHASE_FIELDS
        ),
        legacy_field=(
            _LEGACY_BEFORE_FIELD
        ),
    )

    _normalize_three_phase_group(
        normalized,
        phase_fields=(
            _AFTER_PHASE_FIELDS
        ),
        legacy_field=(
            _LEGACY_AFTER_FIELD
        ),
    )

    _normalize_three_phase_group(
        normalized,
        phase_fields=(
            _MANEUVERED_PHASE_FIELDS
        ),
        legacy_field=(
            _LEGACY_MANEUVERED_FIELD
        ),
    )

    _normalize_three_phase_group(
        normalized,
        phase_fields=(
            _REMAINING_PHASE_FIELDS
        ),
        legacy_field=(
            _LEGACY_REMAINING_FIELD
        ),
    )

    return normalized


def clear_event_cache() -> None:
    """
    Membersihkan cache pembacaan event.
    """

    _load_events.clear()


# ==========================================================
# CREATE
# ==========================================================


def create_event(
    payload: EventPayload,
) -> EventRow:
    """
    Membuat record utama Gangguan / Manuver
    pada trx_kejadian_penyulang.

    Mendukung arus tiga phasa:
    - load_current_before_r_a / s / t
    - load_current_after_r_a / s / t
    - maneuvered_current_r_a / s / t
    - remaining_current_r_a / s / t

    Field legacy tetap dipertahankan sebagai rata-rata untuk
    kompatibilitas database dan komponen lama.
    - load_current_after_s_a
    - load_current_after_t_a

    Field legacy load_current_before_a / after_a tetap
    disinkronkan sebagai nilai rata-rata tiga phasa.
    """

    if not payload:
        raise ValueError(
            "Payload event tidak boleh kosong."
        )

    normalized_payload = (
        _normalize_event_payload(
            payload
        )
    )

    supabase = get_supabase_client()

    response = (
        supabase
        .table(
            "trx_kejadian_penyulang"
        )
        .insert(
            normalized_payload
        )
        .execute()
    )

    rows = _as_event_rows(
        response.data
    )

    if not rows:
        raise RuntimeError(
            "Data operasi tidak berhasil disimpan "
            "atau response database kosong."
        )

    clear_event_cache()

    return rows[0]


def create_event_indications(
    event_id: str,
    indication_codes: list[str],
) -> None:
    """
    Menyimpan indikasi relay / proteksi
    ke trx_kejadian_indikasi.
    """

    if not event_id:
        raise ValueError(
            "Event ID tidak boleh kosong."
        )

    clean_codes: list[str] = []

    for code in indication_codes:
        value = str(
            code
            or ""
        ).strip()

        if (
            value
            and value not in clean_codes
        ):
            clean_codes.append(
                value
            )

    if not clean_codes:
        return

    supabase = get_supabase_client()

    rows: list[dict[str, str]] = [
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

    clear_event_cache()


def replace_event_indications(
    event_id: str,
    indication_codes: list[str],
) -> None:
    """
    Mengganti seluruh indikasi suatu event.

    Digunakan saat edit riwayat.
    """

    if not event_id:
        raise ValueError(
            "Event ID tidak boleh kosong."
        )

    supabase = get_supabase_client()

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

    create_event_indications(
        event_id=event_id,
        indication_codes=(
            indication_codes
        ),
    )

    clear_event_cache()


# ==========================================================
# UPDATE
# ==========================================================


def update_event_recovery(
    event_id: str,
    payload: EventPayload,
) -> EventRow:
    """
    Memperbarui data pemulihan beban,
    normalisasi jaringan, status PMT,
    serta arus setelah operasi R/S/T.
    """

    if not event_id:
        raise ValueError(
            "Event ID tidak boleh kosong."
        )

    if not payload:
        raise ValueError(
            "Payload pemulihan tidak boleh kosong."
        )

    normalized_payload = (
        _normalize_event_payload(
            payload
        )
    )

    supabase = get_supabase_client()

    response = (
        supabase
        .table(
            "trx_kejadian_penyulang"
        )
        .update(
            normalized_payload
        )
        .eq(
            "event_id",
            event_id,
        )
        .eq(
            "is_deleted",
            False,
        )
        .execute()
    )

    rows = _as_event_rows(
        response.data
    )

    if not rows:
        raise RuntimeError(
            "Data pemulihan tidak berhasil diperbarui "
            "atau record sudah dihapus."
        )

    clear_event_cache()

    return rows[0]


def update_event(
    event_id: str,
    payload: EventPayload,
) -> EventRow:
    """
    Update umum data Gangguan / Manuver.

    Mendukung field arus R/S/T baru dan tetap menjaga
    field legacy rata-rata untuk kompatibilitas downstream.
    """

    if not event_id:
        raise ValueError(
            "Event ID tidak boleh kosong."
        )

    if not payload:
        raise ValueError(
            "Payload update tidak boleh kosong."
        )

    normalized_payload = (
        _normalize_event_payload(
            payload
        )
    )

    supabase = get_supabase_client()

    response = (
        supabase
        .table(
            "trx_kejadian_penyulang"
        )
        .update(
            normalized_payload
        )
        .eq(
            "event_id",
            event_id,
        )
        .eq(
            "is_deleted",
            False,
        )
        .execute()
    )

    rows = _as_event_rows(
        response.data
    )

    if not rows:
        raise RuntimeError(
            "Data operasi tidak berhasil diperbarui "
            "atau record sudah dihapus."
        )

    clear_event_cache()

    return rows[0]


# ==========================================================
# SOFT DELETE / RESTORE
# ==========================================================


def soft_delete_event(
    event_id: str,
    delete_reason: str,
) -> None:
    """
    Soft delete record Gangguan / Manuver.
    """

    if not event_id:
        raise ValueError(
            "Event ID tidak boleh kosong."
        )

    reason = (
        delete_reason
        or ""
    ).strip()

    if not reason:
        raise ValueError(
            "Alasan penghapusan wajib diisi."
        )

    user_id = get_current_user_id()

    if not user_id:
        raise RuntimeError(
            "User login tidak ditemukan."
        )

    supabase = get_supabase_client()

    payload: EventPayload = {
        "is_deleted":
            True,

        "deleted_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "deleted_by":
            user_id,

        "delete_reason":
            reason,
    }

    response = (
        supabase
        .table(
            "trx_kejadian_penyulang"
        )
        .update(
            payload
        )
        .eq(
            "event_id",
            event_id,
        )
        .eq(
            "is_deleted",
            False,
        )
        .execute()
    )

    rows = _as_event_rows(
        response.data
    )

    if not rows:
        raise RuntimeError(
            "Record tidak ditemukan, sudah dihapus, "
            "atau tidak dapat dihapus."
        )

    clear_event_cache()


def restore_event(
    event_id: str,
) -> None:
    """
    Mengembalikan record yang sebelumnya
    sudah di-soft-delete.
    """

    if not event_id:
        raise ValueError(
            "Event ID tidak boleh kosong."
        )

    supabase = get_supabase_client()

    payload: EventPayload = {
        "is_deleted":
            False,

        "deleted_at":
            None,

        "deleted_by":
            None,

        "delete_reason":
            None,
    }

    response = (
        supabase
        .table(
            "trx_kejadian_penyulang"
        )
        .update(
            payload
        )
        .eq(
            "event_id",
            event_id,
        )
        .eq(
            "is_deleted",
            True,
        )
        .execute()
    )

    rows = _as_event_rows(
        response.data
    )

    if not rows:
        raise RuntimeError(
            "Record tidak ditemukan atau "
            "tidak dapat dipulihkan."
        )

    clear_event_cache()


# ==========================================================
# READ
# ==========================================================


def get_event_by_id(
    event_id: str,
) -> EventRow | None:
    """
    Membaca satu record dari vw_kejadian_penyulang_detail.

    View sudah mencakup:
    - load_current_before_r_a / s / t
    - load_current_after_r_a / s / t
    - field legacy average
    """

    if not event_id:
        return None

    supabase = get_supabase_client()

    response = (
        supabase
        .table(
            "vw_kejadian_penyulang_detail"
        )
        .select("*")
        .eq(
            "event_id",
            event_id,
        )
        .limit(1)
        .execute()
    )

    rows = _as_event_rows(
        response.data
    )

    if not rows:
        return None

    return rows[0]


@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def _load_events(
    record_status: str | None = None,
    event_type_code: str | None = None,
) -> list[EventRow]:
    """
    Pembacaan daftar event melalui view detail.
    """

    supabase = get_supabase_client()

    query = (
        supabase
        .table(
            "vw_kejadian_penyulang_detail"
        )
        .select("*")
    )

    if record_status:
        query = query.eq(
            "record_status",
            record_status,
        )

    if event_type_code:
        query = query.eq(
            "event_type_code",
            event_type_code,
        )

    response = (
        query
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

    return _as_event_rows(
        response.data
    )


def get_events(
    record_status: str | None = None,
    event_type_code: str | None = None,
) -> list[EventRow]:
    return _load_events(
        record_status=(
            record_status
        ),
        event_type_code=(
            event_type_code
        ),
    )


def get_active_events() -> list[EventRow]:
    """
    Gangguan yang masih ONGOING.
    """

    return get_events(
        record_status="ONGOING",
        event_type_code="GANGGUAN",
    )


# ==========================================================
# AUTH
# ==========================================================


def get_current_user_id() -> str | None:
    """
    Mengambil UUID user Supabase yang sedang login.
    """

    user = st.session_state.get(
        "auth_user"
    )

    if user is None:
        return None

    user_id = getattr(
        user,
        "id",
        None,
    )

    if user_id is None:
        return None

    result = str(
        user_id
    ).strip()

    return (
        result
        if result
        else None
    )