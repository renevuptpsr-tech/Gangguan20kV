"""
Transformer Import Service
==========================

Import master Trafo Daya dari hasil export Excel PLN ke Supabase.

Prinsip:
- TECHIDENTNO = external business key PLN / kunci UPSERT.
- transformer_id UUID tetap menjadi primary key internal Supabase.
- ID_FUNCTLOC harus cocok dengan mst_functloc.
- KODE_PST harus cocok dengan ref_equipment_type.
- KD_STATUS harus cocok dengan ref_equipment_status.
- Seluruh baris asli Excel tetap disimpan dalam source_raw.
- Filter import diterapkan SEBELUM validasi akhir/import.
- Database write dilakukan melalui RPC fn_import_transformers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Mapping
import math
import re

import pandas as pd

from services.supabase_client import get_supabase_client


SOURCE_SYSTEM = "PLN_EXCEL_EXPORT"
DEFAULT_BATCH_SIZE = 100

REQUIRED_SOURCE_COLUMNS = {"ID_FUNCTLOC"}
KEY_COLUMN_CANDIDATES = ("TECHIDENTNO", "TID")

KNOWN_NUMERIC_SENTINELS = {8888.0, 9999.0}
SENTINEL_NULL_FIELDS = {
    "tap_voltage_delta",
    "wheel_distance_cm",
    "axle_distance_cm",
    "main_fitting_weight_kg",
    "core_coil_weight_kg",
}

NUMERIC_FIELDS = {
    "source_asset_id",
    "rated_power_mva",
    "rated_power_2_mva",
    "rated_power_3_mva",
    "rated_power_4_mva",
    "rated_primary_kv",
    "rated_secondary_kv",
    "rated_tertiary_kv",
    "max_primary_kv",
    "max_secondary_kv",
    "max_tertiary_kv",
    "rated_primary_current_a",
    "rated_secondary_current_a",
    "rated_tertiary_current_a",
    "impedance_percent",
    "operating_voltage_kv",
    "bil_primary_kv",
    "bil_secondary_kv",
    "bil_tertiary_kv",
    "power_frequency_withstand_primary_kv",
    "power_frequency_withstand_secondary_kv",
    "power_frequency_withstand_tertiary_kv",
    "short_circuit_time_s",
    "temperature_limit_c",
    "winding_temperature_rise_c",
    "oil_temperature_rise_c",
    "tap_voltage_low_kv",
    "tap_voltage_normal_kv",
    "tap_voltage_high_kv",
    "tap_voltage_delta",
    "length_cm",
    "width_cm",
    "height_cm",
    "oil_weight_kg",
    "core_coil_weight_kg",
    "total_weight_kg",
    "main_fitting_weight_kg",
    "wheel_distance_cm",
    "axle_distance_cm",
}

INTEGER_FIELDS = {
    "source_asset_id",
    "cooling_pump_count",
    "fan_group_count",
    "cooler_count",
    "tap_count",
    "manufacture_year",
}
DATE_FIELDS = {"operational_date", "initial_operational_date", "non_operational_date"}
DATETIME_FIELDS = {"source_created_at", "source_modified_at"}


@dataclass(slots=True)
class TransformerImportFilters:
    statuses: tuple[str, ...] = ()
    gi_names: tuple[str, ...] = ()
    operating_voltages: tuple[str, ...] = ()
    manufacturers: tuple[str, ...] = ()
    transformer_types: tuple[str, ...] = ()
    equipment_types: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not any(
            (
                self.statuses,
                self.gi_names,
                self.operating_voltages,
                self.manufacturers,
                self.transformer_types,
                self.equipment_types,
            )
        )


@dataclass(slots=True)
class TransformerImportIssue:
    row_number: int
    techidentno: str | None
    level: str
    message: str


@dataclass(slots=True)
class TransformerSourcePreview:
    file_name: str
    sheet_name: str
    header_row: int
    source_rows: int
    dataframe: pd.DataFrame
    filter_options: dict[str, list[str]]


@dataclass(slots=True)
class TransformerImportPreview:
    file_name: str
    sheet_name: str
    header_row: int
    source_rows: int
    selected_rows: int
    filtered_out_rows: int
    valid_rows: int
    skipped_rows: int
    duplicate_keys: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    issues: list[TransformerImportIssue] = field(default_factory=list)
    applied_filters: TransformerImportFilters = field(default_factory=TransformerImportFilters)

    @property
    def has_blocking_issues(self) -> bool:
        return any(issue.level == "ERROR" for issue in self.issues)


@dataclass(slots=True)
class TransformerImportResult:
    processed: int
    inserted: int
    updated: int
    skipped: int
    errors: list[dict[str, Any]]
    source_batch_id: str


DIRECT_COLUMN_MAP: dict[str, str] = {
    "SERIAL_ID": "serial_id",
    "ID_BAY": "source_bay_id",
    "KODE_PST": "equipment_type_code",
    "KD_STATUS": "status_code",
    "TEG_OPRS": "operating_voltage_kv",
    "TEG_OPERASI": "operating_voltage_text",
    "IMPDNS": "impedance_percent",
    "PHASA": "phase_code",
    "TGL_OPRS": "operational_date",
    "THN_BUAT": "manufacture_year",
    "BUATAN": "country",
    "JENIS": "transformer_kind",
    "PENEMPATAN": "placement",
    "KETERANGAN": "notes",
    "CONS_TYPE": "source_cons_type",
    "DESCRIPTION": "source_description",
    "ASSET": "source_asset_id",
    "EQ_NUMBER": "eq_number",
    "EQUIPMENT_NUMBER": "equipment_number",
    "ID_FUNCTLOC": "functloc_id",
    "TIPE": "transformer_type",
    "MERK": "manufacturer",
    "TEG_PRIM_RATED": "rated_primary_kv",
    "TEG_SEC_RATED": "rated_secondary_kv",
    "TEG_TER_RATED": "rated_tertiary_kv",
    "TEG_PRIM_MAX": "max_primary_kv",
    "TEG_SEC_MAX": "max_secondary_kv",
    "TEG_TER_MAX": "max_tertiary_kv",
    "ARUS_PRIM": "rated_primary_current_a",
    "ARUS_SEC": "rated_secondary_current_a",
    "ARUS_TER": "rated_tertiary_current_a",
    "VECTOR": "vector_group",
    "BIL": "bil_primary_kv",
    "SIL": "sil_value",
    "PFWV": "power_frequency_withstand_primary_kv",
    "SUHU": "temperature_limit_c",
    "SUHU_NAIK_W": "winding_temperature_rise_c",
    "SUHU_NAIK_O": "oil_temperature_rise_c",
    "COOLING": "cooling_type",
    "JNS_ISO_KERTAS": "insulation_paper_type",
    "KLS_ISO": "insulation_class",
    "PANJANG": "length_cm",
    "LEBAR": "width_cm",
    "TINGGI": "height_cm",
    "BRT_MINYAK": "oil_weight_kg",
    "BRT_INTI_BLTN": "core_coil_weight_kg",
    "BRT_TOT": "total_weight_kg",
    "JNS_MINYAK": "oil_type",
    "JRK_RODA": "wheel_distance_cm",
    "JRK_AS": "axle_distance_cm",
    "STANDARD": "standard_code",
    "BIL_SEC": "bil_secondary_kv",
    "BIL_TER": "bil_tertiary_kv",
    "PFW_SEC": "power_frequency_withstand_secondary_kv",
    "PFW_TER": "power_frequency_withstand_tertiary_kv",
    "BRT_MAIN_FITTING": "main_fitting_weight_kg",
    "DELTA_TEG_TAP": "tap_voltage_delta",
    "JML_COOLING_PUMP": "cooling_pump_count",
    "JML_GROUP_KIPAS": "fan_group_count",
    "JML_TAP": "tap_count",
    "TEG_TAP_BAWAH": "tap_voltage_low_kv",
    "TEG_TAP_ATAS": "tap_voltage_high_kv",
    "TEG_TAP_NORMAL": "tap_voltage_normal_kv",
    "TIPE_MINYAK": "oil_type_detail",
    "WAKTU_SC": "short_circuit_time_s",
    "TGL_TDK_OPRS": "non_operational_date",
    "TGL_AWAL_OPRS": "initial_operational_date",
    "MNFSERIALNUM": "manufacturer_serial_number",
    "CREATED": "source_created_at",
    "MODIFIED": "source_modified_at",
    "NOKONTRAK": "contract_number",
    "DAYA": "rated_power_mva",
    "DAYA2": "rated_power_2_mva",
    "DAYA3": "rated_power_3_mva",
    "DAYA4": "rated_power_4_mva",
}


def _clean_header(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    return re.sub(r"\s+", "_", text)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(value, str) and not value.strip()


def _text(value: Any) -> str | None:
    if _is_blank(value):
        return None
    text = str(value).strip()
    if text.startswith("'"):
        text = text[1:].strip()
    if not text or text.upper() in {"NAN", "NONE", "NULL"}:
        return None
    return text


def _json_safe(value: Any) -> Any:
    if _is_blank(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().isoformat(sep=" ")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _numeric(value: Any) -> float | int | None:
    if _is_blank(value) or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value

    text = str(value).strip()
    if not text or text.upper() in {"NO DATA", "N/A", "NA", "NULL", "NONE", "-"}:
        return None

    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")

    text = re.sub(r"[^0-9eE+\-.]", "", text)
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _integer(value: Any) -> int | None:
    number = _numeric(value)
    if number is None:
        return None
    try:
        return int(float(number))
    except (TypeError, ValueError):
        return None


def _date_iso(value: Any) -> str | None:
    if _is_blank(value):
        return None
    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _datetime_iso(value: Any) -> str | None:
    if _is_blank(value):
        return None
    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime().isoformat(sep=" ")


def _coerce_field(field_name: str, value: Any) -> Any:
    if field_name in DATE_FIELDS:
        return _date_iso(value)
    if field_name in DATETIME_FIELDS:
        return _datetime_iso(value)
    if field_name in INTEGER_FIELDS:
        number = _integer(value)
        if number is not None and field_name in SENTINEL_NULL_FIELDS and float(number) in KNOWN_NUMERIC_SENTINELS:
            return None
        return number
    if field_name in NUMERIC_FIELDS:
        number = _numeric(value)
        if number is not None and field_name in SENTINEL_NULL_FIELDS and float(number) in KNOWN_NUMERIC_SENTINELS:
            return None
        return number
    return _text(value)


def _read_file_bytes(source: bytes | bytearray | BinaryIO | Any) -> bytes:
    if isinstance(source, bytes):
        return source
    if isinstance(source, bytearray):
        return bytes(source)

    getvalue = getattr(source, "getvalue", None)
    if callable(getvalue):
        value = getvalue()
        if isinstance(value, bytes):
            return value

    read = getattr(source, "read", None)
    if callable(read):
        current_position = None
        tell = getattr(source, "tell", None)
        seek = getattr(source, "seek", None)
        if callable(tell):
            try:
                current_position = tell()
            except Exception:
                current_position = None

        value = read()

        if callable(seek) and current_position is not None:
            try:
                seek(current_position)
            except Exception:
                pass

        if isinstance(value, bytes):
            return value

    raise TypeError("File Excel tidak dapat dibaca sebagai bytes.")


def _detect_header_row(file_bytes: bytes, sheet_name: str | int = 0, scan_rows: int = 15) -> int:
    preview = pd.read_excel(
        BytesIO(file_bytes),
        sheet_name=sheet_name,
        header=None,
        nrows=scan_rows,
        dtype=object,
    )
    for row_index in range(len(preview.index)):
        headers = {
            _clean_header(value)
            for value in preview.iloc[row_index].tolist()
            if not _is_blank(value)
        }
        if "ID_FUNCTLOC" in headers and ("TECHIDENTNO" in headers or "TID" in headers):
            return row_index
    raise ValueError(
        "Header Excel tidak ditemukan. File harus memiliki kolom "
        "ID_FUNCTLOC dan TECHIDENTNO/TID."
    )


def _unique_values(df: pd.DataFrame, column: str) -> list[str]:
    if column not in df.columns:
        return []
    values: set[str] = set()
    for value in df[column].tolist():
        text = _text(value)
        if text:
            if column == "KD_STATUS" and text.isdigit():
                text = text.zfill(2)
            values.add(text)
    return sorted(values)


def load_transformer_source(
    source: bytes | bytearray | BinaryIO | Any,
    *,
    file_name: str | None = None,
    sheet_name: str | int = 0,
) -> TransformerSourcePreview:
    """
    Membaca Excel mentah dan mengembalikan pilihan filter.
    Belum melakukan validasi baris untuk import.
    """
    file_bytes = _read_file_bytes(source)
    if file_name is None:
        file_name = str(getattr(source, "name", "transformer_import.xlsx"))

    header_index = _detect_header_row(file_bytes, sheet_name=sheet_name)
    xls = pd.ExcelFile(BytesIO(file_bytes))
    resolved_sheet: str
    if isinstance(sheet_name, int):
        resolved_sheet = str(xls.sheet_names[sheet_name])
    else:
        resolved_sheet = str(sheet_name)

    df = pd.read_excel(
        BytesIO(file_bytes),
        sheet_name=resolved_sheet,
        header=header_index,
        dtype=object,
    )
    df.columns = [_clean_header(column) for column in df.columns]
    df = df.dropna(how="all").reset_index(drop=True)

    source_columns = set(df.columns)
    missing_required = REQUIRED_SOURCE_COLUMNS - source_columns
    if missing_required:
        raise ValueError(
            "Kolom wajib tidak tersedia: " + ", ".join(sorted(missing_required))
        )
    if not any(key in source_columns for key in KEY_COLUMN_CANDIDATES):
        raise ValueError("File tidak memiliki TECHIDENTNO maupun TID.")

    filter_options = {
        "statuses": _unique_values(df, "KD_STATUS"),
        "gi_names": _unique_values(df, "NAMAGI"),
        "operating_voltages": _unique_values(df, "TEG_OPRS"),
        "manufacturers": _unique_values(df, "MERK"),
        "transformer_types": _unique_values(df, "TIPE"),
        "equipment_types": _unique_values(df, "KODE_PST"),
    }

    return TransformerSourcePreview(
        file_name=file_name,
        sheet_name=resolved_sheet,
        header_row=header_index + 1,
        source_rows=len(df.index),
        dataframe=df,
        filter_options=filter_options,
    )


def _matches_filter(value: Any, selected: tuple[str, ...], *, status: bool = False) -> bool:
    if not selected:
        return True
    text = _text(value)
    if text is None:
        return False
    if status and text.isdigit():
        text = text.zfill(2)
    return text in selected


def apply_transformer_filters(
    source_preview: TransformerSourcePreview,
    filters: TransformerImportFilters,
) -> pd.DataFrame:
    df = source_preview.dataframe.copy()

    mask = pd.Series(True, index=df.index)

    if filters.statuses and "KD_STATUS" in df.columns:
        mask &= df["KD_STATUS"].apply(
            lambda value: _matches_filter(value, filters.statuses, status=True)
        )
    if filters.gi_names and "NAMAGI" in df.columns:
        mask &= df["NAMAGI"].apply(
            lambda value: _matches_filter(value, filters.gi_names)
        )
    if filters.operating_voltages and "TEG_OPRS" in df.columns:
        mask &= df["TEG_OPRS"].apply(
            lambda value: _matches_filter(value, filters.operating_voltages)
        )
    if filters.manufacturers and "MERK" in df.columns:
        mask &= df["MERK"].apply(
            lambda value: _matches_filter(value, filters.manufacturers)
        )
    if filters.transformer_types and "TIPE" in df.columns:
        mask &= df["TIPE"].apply(
            lambda value: _matches_filter(value, filters.transformer_types)
        )
    if filters.equipment_types and "KODE_PST" in df.columns:
        mask &= df["KODE_PST"].apply(
            lambda value: _matches_filter(value, filters.equipment_types)
        )

    return df.loc[mask].copy().reset_index(drop=True)


def _resolve_key(row: Mapping[str, Any]) -> str | None:
    for column in KEY_COLUMN_CANDIDATES:
        value = _text(row.get(column))
        if value:
            return value
    return None


def _normalize_row(source_row: Mapping[str, Any], *, source_batch_id: str) -> dict[str, Any]:
    normalized_source = {_clean_header(key): value for key, value in source_row.items()}

    result: dict[str, Any] = {"techidentno": _resolve_key(normalized_source)}

    for source_column, target_column in DIRECT_COLUMN_MAP.items():
        result[target_column] = _coerce_field(
            target_column,
            normalized_source.get(source_column),
        )

    if result.get("rated_power_3_mva") is None:
        result["rated_power_3_mva"] = _numeric(normalized_source.get("DAYA_TER"))

    if not result.get("vector_group"):
        result["vector_group"] = _text(normalized_source.get("VECTORX"))

    if not result.get("notes"):
        result["notes"] = _text(normalized_source.get("DESKRIPSI"))

    result["source_system"] = SOURCE_SYSTEM
    result["source_batch_id"] = source_batch_id

    status_code = str(result.get("status_code") or "")
    if status_code.isdigit():
        status_code = status_code.zfill(2)
        result["status_code"] = status_code

    # Status historis/nonaktif tidak dihapus; hanya ditandai is_active=false.
    result["is_active"] = status_code not in {"03", "04", "05", "08"}

    result["source_raw"] = {
        str(key): _json_safe(value)
        for key, value in source_row.items()
    }
    return result


def prepare_transformer_import(
    source: bytes | bytearray | BinaryIO | Any | None = None,
    *,
    file_name: str | None = None,
    sheet_name: str | int = 0,
    filters: TransformerImportFilters | None = None,
    source_preview: TransformerSourcePreview | None = None,
) -> TransformerImportPreview:
    """
    Filter -> validasi -> normalisasi.

    Bisa menerima source_preview agar file tidak perlu dibaca ulang.
    """
    filters = filters or TransformerImportFilters()

    if source_preview is None:
        if source is None:
            raise ValueError("source atau source_preview wajib diberikan.")
        source_preview = load_transformer_source(
            source,
            file_name=file_name,
            sheet_name=sheet_name,
        )

    selected_df = apply_transformer_filters(source_preview, filters)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_stem = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        Path(source_preview.file_name).stem,
    ).strip("_")
    source_batch_id = f"{clean_stem}_{timestamp}"

    issues: list[TransformerImportIssue] = []
    normalized_rows: list[dict[str, Any]] = []
    key_counts: dict[str, int] = {}

    for row_offset, (_, row_series) in enumerate(selected_df.iterrows(), start=1):
        source_row = {
            str(key): value
            for key, value in row_series.to_dict().items()
        }
        row_number = source_preview.header_row + row_offset

        normalized = _normalize_row(source_row, source_batch_id=source_batch_id)
        techidentno = normalized.get("techidentno")

        if not techidentno:
            issues.append(
                TransformerImportIssue(
                    row_number=row_number,
                    techidentno=None,
                    level="ERROR",
                    message="TECHIDENTNO/TID kosong.",
                )
            )
            continue

        key_counts[techidentno] = key_counts.get(techidentno, 0) + 1

        if not normalized.get("functloc_id"):
            issues.append(
                TransformerImportIssue(
                    row_number=row_number,
                    techidentno=techidentno,
                    level="ERROR",
                    message="ID_FUNCTLOC kosong.",
                )
            )
            continue

        if not normalized.get("equipment_type_code"):
            issues.append(
                TransformerImportIssue(
                    row_number=row_number,
                    techidentno=techidentno,
                    level="WARNING",
                    message="KODE_PST kosong.",
                )
            )

        if not normalized.get("status_code"):
            issues.append(
                TransformerImportIssue(
                    row_number=row_number,
                    techidentno=techidentno,
                    level="WARNING",
                    message="KD_STATUS kosong.",
                )
            )

        if normalized.get("equipment_type_code") is not None:
            normalized["equipment_type_code"] = str(
                normalized["equipment_type_code"]
            ).strip()

        normalized_rows.append(normalized)

    duplicate_keys = sorted(
        key for key, count in key_counts.items() if count > 1
    )
    for key in duplicate_keys:
        issues.append(
            TransformerImportIssue(
                row_number=0,
                techidentno=key,
                level="ERROR",
                message=(
                    "TECHIDENTNO duplikat di dalam data terpilih. "
                    "Import diblokir sampai duplikasi diperbaiki."
                ),
            )
        )

    return TransformerImportPreview(
        file_name=source_preview.file_name,
        sheet_name=source_preview.sheet_name,
        header_row=source_preview.header_row,
        source_rows=source_preview.source_rows,
        selected_rows=len(selected_df.index),
        filtered_out_rows=source_preview.source_rows - len(selected_df.index),
        valid_rows=len(normalized_rows),
        skipped_rows=len(selected_df.index) - len(normalized_rows),
        duplicate_keys=duplicate_keys,
        rows=normalized_rows,
        issues=issues,
        applied_filters=filters,
    )


def preview_rows_for_display(
    preview: TransformerImportPreview,
    *,
    limit: int = 100,
) -> pd.DataFrame:
    display_columns = [
        "techidentno",
        "functloc_id",
        "equipment_type_code",
        "status_code",
        "manufacturer",
        "transformer_type",
        "rated_power_mva",
        "rated_primary_kv",
        "rated_secondary_kv",
        "rated_tertiary_kv",
        "rated_secondary_current_a",
        "impedance_percent",
        "operational_date",
    ]
    return pd.DataFrame(
        [
            {column: row.get(column) for column in display_columns}
            for row in preview.rows[:limit]
        ]
    )


def issues_for_display(preview: TransformerImportPreview) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Baris Excel": issue.row_number or "",
                "TECHIDENTNO": issue.techidentno or "",
                "Level": issue.level,
                "Keterangan": issue.message,
            }
            for issue in preview.issues
        ]
    )


def import_transformers(
    preview: TransformerImportPreview,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> TransformerImportResult:
    if preview.has_blocking_issues:
        raise ValueError("Import diblokir karena preview masih memiliki ERROR.")
    if not preview.rows:
        raise ValueError("Tidak ada data Trafo yang dapat diimport.")
    if batch_size < 1:
        raise ValueError("batch_size minimal 1.")

    supabase = get_supabase_client()

    total_processed = 0
    total_inserted = 0
    total_updated = 0
    total_skipped = 0
    all_errors: list[dict[str, Any]] = []

    source_batch_id = str(
        preview.rows[0].get("source_batch_id")
        or datetime.now().strftime("PLN_TRAFO_%Y%m%d_%H%M%S")
    )

    for start in range(0, len(preview.rows), batch_size):
        batch = preview.rows[start : start + batch_size]

        response = (
            supabase
            .rpc(
                "fn_import_transformers",
                {
                    "p_rows": batch,
                    "p_source_batch_id": source_batch_id,
                },
            )
            .execute()
        )

        raw_result: object = response.data

        if isinstance(raw_result, list):
            raw_result = raw_result[0] if raw_result else None

        if not isinstance(raw_result, dict):
            raise RuntimeError(
                "Respons RPC import Trafo tidak valid."
            )

        result: dict[str, object] = {
            str(key): value
            for key, value in raw_result.items()
        }

        def _result_int(key: str) -> int:
            value: object = result.get(key, 0)

            if isinstance(value, bool):
                return int(value)

            if isinstance(value, int):
                return value

            if isinstance(value, float):
                return int(value)

            if isinstance(value, str):
                try:
                    return int(float(value))
                except ValueError:
                    return 0

            return 0

        total_processed += _result_int("processed")
        total_inserted += _result_int("inserted")
        total_updated += _result_int("updated")
        total_skipped += _result_int("skipped")

        errors_value: object = result.get("errors", [])

        if isinstance(errors_value, list):
            for error in errors_value:
                if isinstance(error, dict):
                    all_errors.append(
                        {
                            str(key): value
                            for key, value in error.items()
                        }
                    )

    return TransformerImportResult(
        processed=total_processed,
        inserted=total_inserted,
        updated=total_updated,
        skipped=total_skipped,
        errors=all_errors,
        source_batch_id=source_batch_id,
    )