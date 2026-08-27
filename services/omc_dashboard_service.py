from __future__ import annotations

from datetime import date
from typing import Any, cast

from services.supabase_client import get_supabase_client


def get_omc_recent_gangguan(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    client = get_supabase_client()

    response = (
        client
        .rpc(
            "fn_omc_recent_gangguan",
            {
                "p_start_date": (
                    start_date.isoformat()
                    if start_date is not None
                    else None
                ),
                "p_end_date": (
                    end_date.isoformat()
                    if end_date is not None
                    else None
                ),
                "p_limit": max(
                    int(limit),
                    1,
                ),
            },
        )
        .execute()
    )

    raw_data: Any = response.data

    if not isinstance(
        raw_data,
        list,
    ):
        return []

    rows = cast(
        list[Any],
        raw_data,
    )

    result: list[dict[str, Any]] = []

    for row in rows:
        if not isinstance(
            row,
            dict,
        ):
            continue

        result.append(
            cast(
                dict[str, Any],
                row,
            )
        )

    return result