from __future__ import annotations

from datetime import date

from services.supabase_client import get_supabase_client


def _as_dict_list(data: object) -> list[dict[str, object]]:
    if not isinstance(data, list):
        return []

    rows: list[dict[str, object]] = []
    for item in data:
        if isinstance(item, dict):
            rows.append({str(k): v for k, v in item.items()})
    return rows


def get_transformer_fault_exposure(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    ultg_flc: str | None = None,
    gi_flc: str | None = None,
    bay_flc: str | None = None,
    penyulang_id: str | None = None,
) -> list[dict[str, object]]:
    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_transformer_fault_exposure_v2",
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

    return _as_dict_list(response.data)


def get_transformer_fault_exposure_coverage(
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
            "fn_transformer_fault_exposure_coverage_v2",
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
        return {
            "total_gangguan": 0,
            "mapped_gangguan": 0,
            "unmapped_gangguan": 0,
            "coverage_percent": 100,
        }

    return {str(k): v for k, v in data.items()}
