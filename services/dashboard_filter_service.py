from __future__ import annotations

from services.supabase_client import get_supabase_client


def _as_dict_list(data: object) -> list[dict[str, object]]:
    if not isinstance(data, list):
        return []

    rows: list[dict[str, object]] = []
    for item in data:
        if isinstance(item, dict):
            rows.append({str(k): v for k, v in item.items()})
    return rows


def get_dashboard_filter_options() -> list[dict[str, object]]:
    supabase = get_supabase_client()
    response = (
        supabase
        .rpc(
            "fn_dashboard_filter_options",
            {},
        )
        .execute()
    )
    return _as_dict_list(response.data)
