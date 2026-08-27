from __future__ import annotations

from datetime import date
from typing import Any

from services.supabase_client import get_supabase_client


def _as_dict_list(data: object) -> list[dict[str, object]]:
    if not isinstance(data, list):
        return []

    rows: list[dict[str, object]] = []
    for item in data:
        if isinstance(item, dict):
            rows.append(
                {
                    str(key): value
                    for key, value in item.items()
                }
            )
    return rows


def get_transformer_mapping_options() -> list[dict[str, object]]:
    supabase = get_supabase_client()
    response = (
        supabase
        .rpc(
            "fn_list_transformer_mapping_options",
            {},
        )
        .execute()
    )
    return _as_dict_list(response.data)


def get_transformer_feeder_bay_mappings() -> list[dict[str, object]]:
    supabase = get_supabase_client()
    response = (
        supabase
        .rpc(
            "fn_list_transformer_feeder_bay_mappings",
            {},
        )
        .execute()
    )
    return _as_dict_list(response.data)


def save_transformer_feeder_bay_mapping(
    *,
    transformer_id: str,
    feeder_bay_functloc_id: str,
    valid_from: date,
    notes: str | None = None,
) -> dict[str, object]:
    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_save_transformer_feeder_bay_mapping",
            {
                "p_transformer_id": transformer_id,
                "p_feeder_bay_functloc_id": feeder_bay_functloc_id,
                "p_valid_from": valid_from.isoformat(),
                "p_notes": notes or None,
            },
        )
        .execute()
    )

    raw: object = response.data

    if isinstance(raw, list):
        raw = raw[0] if raw else None

    if not isinstance(raw, dict):
        raise RuntimeError(
            "Respons penyimpanan mapping Trafo-Bay tidak valid."
        )

    return {
        str(key): value
        for key, value in raw.items()
    }


def build_mapping_catalog(
    rows: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    """
    Struktur:
    {
      gi_functloc_id: {
        "gi_name": ...,
        "transformers": {transformer_id: {...}},
        "feeder_bays": {feeder_bay_functloc_id: {...}},
      }
    }
    """
    catalog: dict[str, dict[str, object]] = {}

    for row in rows:
        gi_id = str(row.get("gi_functloc_id") or "").strip()
        if not gi_id:
            continue

        gi_entry = catalog.setdefault(
            gi_id,
            {
                "gi_name": str(row.get("gi_name") or gi_id),
                "transformers": {},
                "feeder_bays": {},
            },
        )

        transformers = gi_entry["transformers"]
        feeder_bays = gi_entry["feeder_bays"]

        if isinstance(transformers, dict):
            transformer_id = str(row.get("transformer_id") or "").strip()
            if transformer_id:
                transformers[transformer_id] = {
                    "transformer_id": transformer_id,
                    "techidentno": row.get("techidentno"),
                    "transformer_bay_functloc_id": row.get(
                        "transformer_bay_functloc_id"
                    ),
                    "transformer_bay_name": row.get(
                        "transformer_bay_name"
                    ),
                    "rated_power_mva": row.get("rated_power_mva"),
                }

        if isinstance(feeder_bays, dict):
            feeder_bay_id = str(
                row.get("feeder_bay_functloc_id") or ""
            ).strip()
            if feeder_bay_id:
                feeder_bays[feeder_bay_id] = {
                    "feeder_bay_functloc_id": feeder_bay_id,
                    "feeder_bay_name": row.get("feeder_bay_name"),
                    "feeder_count": row.get("feeder_count"),
                    "feeder_names": row.get("feeder_names"),
                    "current_transformer_id": row.get(
                        "current_transformer_id"
                    ),
                    "current_transformer_techidentno": row.get(
                        "current_transformer_techidentno"
                    ),
                    "current_transformer_bay_name": row.get(
                        "current_transformer_bay_name"
                    ),
                }

    return catalog