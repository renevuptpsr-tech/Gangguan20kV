from __future__ import annotations

from datetime import date

import streamlit as st

from services.monthly_period_guard_service import (
    is_event_period_approved,
    monthly_period_label,
)


def render_monthly_period_guard(
    *,
    penyulang_id: str | None,
    event_date: date | None,
    event_type: str,
) -> bool:
    """
    Mengecek periode segera setelah user memilih tanggal operasi.

    Return:
        True  -> periode terbuka, form dapat dilanjutkan.
        False -> periode sudah terverifikasi, input/edit diblokir.

    Catatan:
    Backend Supabase tetap menjadi pengaman final melalui trigger
    EVENT_PERIOD_ALREADY_APPROVED / EVENT_LOCKED_BY_APPROVED_MONTHLY_REPORT.
    """

    if event_date is None:
        return True

    feeder_id = str(
        penyulang_id
        or ""
    ).strip()

    if not feeder_id:
        return True

    operation_name = (
        "Gangguan"
        if str(
            event_type
            or ""
        ).strip().upper()
        == "GANGGUAN"
        else "Manuver"
    )

    try:
        approved = (
            is_event_period_approved(
                penyulang_id=feeder_id,
                event_date=event_date,
            )
        )

    except Exception:
        # Jangan membuat form crash karena gangguan koneksi.
        # Database tetap akan menolak penyimpanan apabila periode
        # memang sudah APPROVED.
        return True

    if not approved:
        return True

    period = monthly_period_label(
        event_date
    )

    st.error(
        (
            f"🔒 **{operation_name} pada periode {period} "
            "tidak dapat diinput atau diubah.**"
        )
    )

    st.warning(
        (
            f"Laporan Bulanan **{period}** sudah dilakukan "
            "**Verifikasi & e-Sign**. "
            "Silakan hubungi **Evaluator / Admin / Super Admin** "
            "untuk mengembalikan laporan ke **Draft** terlebih dahulu."
        )
    )

    st.caption(
        "Setelah laporan dikembalikan ke Draft, periode akan terbuka "
        "kembali untuk input atau koreksi data. Laporan kemudian harus "
        "diajukan dan diverifikasi ulang."
    )

    return False