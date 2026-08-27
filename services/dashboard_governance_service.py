from __future__ import annotations

from datetime import date

from services.supabase_client import get_supabase_client


def get_dashboard_governance(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    ultg_flc: str | None = None,
    gi_flc: str | None = None,
    bay_flc: str | None = None,
    penyulang_id: str | None = None,
) -> dict[str, object]:
    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_dashboard_governance",
            {
                "p_start_date": start_date.isoformat() if start_date else None,
                "p_end_date": end_date.isoformat() if end_date else None,
                "p_ultg_flc": ultg_flc,
                "p_gi_flc": gi_flc,
                "p_bay_flc": bay_flc,
                "p_penyulang_id": penyulang_id,
            },
        )
        .execute()
    )

    data: object = response.data

    if isinstance(data, list):
        data = data[0] if data else None

    if not isinstance(data, dict):
        return {}

    return {str(k): v for k, v in data.items()}
