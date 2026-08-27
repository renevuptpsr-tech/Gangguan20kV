from __future__ import annotations

import pandas as pd
import streamlit as st

from components.sidebar import render_sidebar
from services.transformer_import_service import (
    TransformerImportFilters,
    import_transformers,
    issues_for_display,
    load_transformer_source,
    prepare_transformer_import,
    preview_rows_for_display,
)
from services.supabase_client import get_supabase_client
from services.access_service import can_manage_access




STATUS_LABELS = {
    "00": "00 - Spare",
    "01": "01 - Operasi",
    "02": "02 - Belum Operasi",
    "03": "03 - Tidak Operasi",
    "04": "04 - Rusak",
    "05": "05 - Digudangkan",
    "06": "06 - Mutasi (Intra)",
    "07": "07 - Mutasi (Inter)",
    "08": "08 - Hapus",
    "11": "11 - Berfungsi",
    "12": "12 - Berfungsi Sebagian",
    "13": "13 - Hilang",
    "14": "14 - NA",
}


def _can_import_transformer() -> bool:
    return can_manage_access()


def _safe_float(value: object) -> float:
    if isinstance(value, bool):
        return float(int(value))

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return 0.0

    return 0.0


@st.cache_data(ttl=60, show_spinner=False)
def _load_transformers(search: str = "") -> list[dict[str, object]]:
    supabase = get_supabase_client()
    response = (
        supabase
        .rpc(
            "fn_list_transformers",
            {
                "p_search": search or None,
                "p_limit": 1000,
            },
        )
        .execute()
    )
    data = response.data
    if not isinstance(data, list):
        return []

    rows: list[dict[str, object]] = []
    for item in data:
        if isinstance(item, dict):
            rows.append(dict(item))

    return rows


def _summary_cards(rows: list[dict[str, object]]) -> None:
    total = len(rows)
    active = sum(1 for row in rows if row.get("is_active"))
    gi_count = len({row.get("gi_name") for row in rows if row.get("gi_name")})
    total_mva = sum(
        _safe_float(row.get("rated_power_mva"))
        for row in rows
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Trafo", total)
    c2.metric("Aktif", active)
    c3.metric("Gardu Induk", gi_count)
    c4.metric("Total Daya", f"{total_mva:,.1f} MVA")


def _master_table(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info("Belum ada data master Trafo pada scope akses Anda.")
        return

    df = pd.DataFrame(rows)

    rename_map = {
        "gi_name": "Gardu Induk",
        "techidentno": "TECHIDENTNO",
        "transformer_name": "Nama / Deskripsi",
        "manufacturer": "Merk",
        "transformer_type": "Tipe",
        "rated_power_mva": "Daya (MVA)",
        "rated_primary_kv": "Primer (kV)",
        "rated_secondary_kv": "Sekunder (kV)",
        "rated_tertiary_kv": "Tersier (kV)",
        "rated_secondary_current_a": "I Nom Sekunder (A)",
        "impedance_percent": "Impedansi (%)",
        "status_name": "Status",
        "operational_date": "Tgl Operasi",
        "manufacture_year": "Tahun Buat",
        "source_system": "Sumber",
        "last_synced_at": "Sinkron Terakhir",
    }

    wanted = [
        "gi_name",
        "techidentno",
        "transformer_name",
        "manufacturer",
        "transformer_type",
        "rated_power_mva",
        "rated_primary_kv",
        "rated_secondary_kv",
        "rated_tertiary_kv",
        "rated_secondary_current_a",
        "impedance_percent",
        "status_name",
        "operational_date",
        "manufacture_year",
        "source_system",
        "last_synced_at",
    ]
    wanted = [column for column in wanted if column in df.columns]
    df = df[wanted].rename(columns=rename_map)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=460,
    )


def _status_display(code: str) -> str:
    return STATUS_LABELS.get(code, code)


def _status_code(display: str) -> str:
    return display.split(" - ", 1)[0].strip()


def _default_status_selection(options: list[str]) -> list[str]:
    preferred = [code for code in ("01", "00") if code in options]
    return preferred or options


def _render_import_filters(source_preview) -> TransformerImportFilters:
    options = source_preview.filter_options

    st.markdown("### Filter Import")
    st.caption(
        "Opsional. Filter diterapkan sebelum validasi dan sebelum data ditulis ke database."
    )

    col1, col2 = st.columns(2)

    status_options = options.get("statuses", [])
    default_statuses = _default_status_selection(status_options)

    with col1:
        selected_status_display = st.multiselect(
            "KD_STATUS",
            options=[_status_display(code) for code in status_options],
            default=[_status_display(code) for code in default_statuses],
            help="Default: Operasi + Spare jika tersedia.",
            key="trafo_filter_status",
        )

        selected_gi = st.multiselect(
            "Gardu Induk",
            options=options.get("gi_names", []),
            default=[],
            placeholder="Semua GI",
            key="trafo_filter_gi",
        )

        selected_voltage = st.multiselect(
            "Tegangan Operasi",
            options=options.get("operating_voltages", []),
            default=[],
            placeholder="Semua tegangan",
            key="trafo_filter_voltage",
        )

    with col2:
        selected_manufacturer = st.multiselect(
            "Merk",
            options=options.get("manufacturers", []),
            default=[],
            placeholder="Semua merk",
            key="trafo_filter_manufacturer",
        )

        selected_type = st.multiselect(
            "Tipe Trafo",
            options=options.get("transformer_types", []),
            default=[],
            placeholder="Semua tipe",
            key="trafo_filter_type",
        )

        selected_equipment_type = st.multiselect(
            "KODE_PST",
            options=options.get("equipment_types", []),
            default=[],
            placeholder="Semua equipment type",
            help="Untuk export query saat ini biasanya 11 = Power Transformer.",
            key="trafo_filter_equipment_type",
        )

    return TransformerImportFilters(
        statuses=tuple(_status_code(item) for item in selected_status_display),
        gi_names=tuple(selected_gi),
        operating_voltages=tuple(selected_voltage),
        manufacturers=tuple(selected_manufacturer),
        transformer_types=tuple(selected_type),
        equipment_types=tuple(selected_equipment_type),
    )


# ==========================================================
# TRANSFORMER ↔ FEEDER BAY MAPPING
# ==========================================================

from datetime import date

from services.transformer_mapping_service import (
    build_mapping_catalog,
    get_transformer_feeder_bay_mappings,
    get_transformer_mapping_options,
    save_transformer_feeder_bay_mapping,
)


@st.cache_data(ttl=60, show_spinner=False)
def _load_transformer_mapping_options() -> list[dict[str, object]]:
    return get_transformer_mapping_options()


@st.cache_data(ttl=60, show_spinner=False)
def _load_transformer_feeder_bay_mappings() -> list[dict[str, object]]:
    return get_transformer_feeder_bay_mappings()


def _safe_int(value: object) -> int:
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


def _format_transformer_option(item: dict[str, object]) -> str:
    bay_name = str(item.get("transformer_bay_name") or "-")
    techidentno = str(item.get("techidentno") or "-")
    power = _safe_float(item.get("rated_power_mva"))

    if power > 0:
        return f"{bay_name} | {power:,.1f} MVA | {techidentno}"

    return f"{bay_name} | {techidentno}"


def _format_feeder_bay_option(item: dict[str, object]) -> str:
    bay_name = str(item.get("feeder_bay_name") or "-")
    bay_id = str(item.get("feeder_bay_functloc_id") or "-")
    feeder_count = _safe_int(item.get("feeder_count"))

    return f"{bay_name} | {feeder_count} Penyulang | {bay_id}"


def _render_mapping_tab() -> None:
    st.subheader("Mapping Trafo Daya ke Bay Penyulang")
    st.caption(
        "Satu mapping Bay otomatis berlaku untuk seluruh penyulang "
        "yang memiliki bay_functloc_id yang sama."
    )

    if not can_manage_access():
        st.info(
            "Anda dapat melihat mapping sesuai scope akses. "
            "Perubahan mapping hanya tersedia untuk ADMIN / SUPER_ADMIN."
        )

    try:
        option_rows = _load_transformer_mapping_options()
    except Exception as exc:
        st.error(f"Pilihan mapping tidak dapat dimuat: {exc}")
        return

    catalog = build_mapping_catalog(option_rows)

    if not catalog:
        st.info(
            "Belum ada kombinasi Trafo dan Bay Penyulang yang tersedia."
        )
        return

    gi_ids = sorted(
        catalog.keys(),
        key=lambda gi_id: str(
            catalog[gi_id].get("gi_name") or gi_id
        ),
    )

    selected_gi_id = st.selectbox(
        "Gardu Induk",
        options=gi_ids,
        format_func=lambda gi_id: str(
            catalog[gi_id].get("gi_name") or gi_id
        ),
        key="trafo_map_gi",
    )

    gi_entry = catalog[selected_gi_id]

    transformers_raw = gi_entry.get("transformers", {})
    feeder_bays_raw = gi_entry.get("feeder_bays", {})

    transformers = (
        transformers_raw
        if isinstance(transformers_raw, dict)
        else {}
    )
    feeder_bays = (
        feeder_bays_raw
        if isinstance(feeder_bays_raw, dict)
        else {}
    )

    transformer_ids = sorted(
        transformers.keys(),
        key=lambda item_id: _format_transformer_option(
            transformers[item_id]
        ),
    )
    feeder_bay_ids = sorted(
        feeder_bays.keys(),
        key=lambda item_id: _format_feeder_bay_option(
            feeder_bays[item_id]
        ),
    )

    col1, col2 = st.columns(2)

    with col1:
        selected_transformer_id = st.selectbox(
            "Trafo Daya",
            options=transformer_ids,
            format_func=lambda item_id: _format_transformer_option(
                transformers[item_id]
            ),
            key="trafo_map_transformer",
        )

    with col2:
        selected_feeder_bay_id = st.selectbox(
            "Bay Penyulang 20 kV",
            options=feeder_bay_ids,
            format_func=lambda item_id: _format_feeder_bay_option(
                feeder_bays[item_id]
            ),
            key="trafo_map_feeder_bay",
        )

    if selected_transformer_id is None:
        st.warning("Pilih Trafo Daya terlebih dahulu.")
        return

    if selected_feeder_bay_id is None:
        st.warning("Pilih Bay Penyulang 20 kV terlebih dahulu.")
        return

    selected_transformer_id_str = str(selected_transformer_id)
    selected_feeder_bay_id_str = str(selected_feeder_bay_id)

    selected_transformer = transformers[
        selected_transformer_id_str
    ]
    selected_bay = feeder_bays[
        selected_feeder_bay_id_str
    ]

    st.markdown("#### Preview Relasi")

    p1, p2 = st.columns(2)

    with p1:
        st.write(
            {
                "Trafo": selected_transformer.get(
                    "transformer_bay_name"
                ),
                "TECHIDENTNO": selected_transformer.get(
                    "techidentno"
                ),
                "Bay Trafo": selected_transformer.get(
                    "transformer_bay_functloc_id"
                ),
                "Daya MVA": selected_transformer.get(
                    "rated_power_mva"
                ),
            }
        )

    with p2:
        st.write(
            {
                "Bay Penyulang": selected_bay.get(
                    "feeder_bay_name"
                ),
                "Functloc Bay": selected_bay.get(
                    "feeder_bay_functloc_id"
                ),
                "Jumlah Penyulang": selected_bay.get(
                    "feeder_count"
                ),
                "Penyulang": selected_bay.get(
                    "feeder_names"
                ),
            }
        )

    current_transformer_id = str(
        selected_bay.get("current_transformer_id") or ""
    ).strip()

    if current_transformer_id:
        current_name = str(
            selected_bay.get(
                "current_transformer_bay_name"
            )
            or selected_bay.get(
                "current_transformer_techidentno"
            )
            or current_transformer_id
        )

        if current_transformer_id == selected_transformer_id_str:
            st.success(
                f"Bay ini sudah aktif bersumber dari {current_name}."
            )
        else:
            st.warning(
                "Bay ini saat ini sudah memiliki sumber aktif: "
                f"{current_name}. Menyimpan mapping baru akan "
                "menutup histori mapping lama dan membuat mapping baru."
            )
    else:
        st.info(
            "Bay ini belum memiliki mapping sumber Trafo aktif."
        )

    valid_from = st.date_input(
        "Berlaku Mulai",
        value=date.today(),
        key="trafo_map_valid_from",
    )

    notes = st.text_area(
        "Catatan (opsional)",
        placeholder=(
            "Contoh: Mapping berdasarkan konfigurasi aktual "
            "single line diagram / data operasi."
        ),
        key="trafo_map_notes",
    )

    if can_manage_access():
        confirm = st.checkbox(
            "Saya sudah memeriksa Trafo, Bay, dan daftar Penyulang.",
            key="trafo_map_confirm",
        )

        if st.button(
            "Simpan Mapping",
            type="primary",
            disabled=not confirm,
            use_container_width=True,
            key="trafo_map_save",
        ):
            try:
                with st.spinner("Menyimpan mapping Trafo-Bay..."):
                    result = save_transformer_feeder_bay_mapping(
                        transformer_id=selected_transformer_id_str,
                        feeder_bay_functloc_id=selected_feeder_bay_id_str,
                        valid_from=valid_from,
                        notes=notes.strip() or None,
                    )

                _load_transformer_mapping_options.clear()
                _load_transformer_feeder_bay_mappings.clear()

                action = str(result.get("action") or "SAVED")

                if action == "UNCHANGED":
                    st.success(
                        "Mapping sudah sesuai. Tidak ada perubahan sumber."
                    )
                elif action == "REASSIGNED":
                    st.success(
                        "Mapping berhasil dipindahkan ke Trafo baru "
                        "dan histori mapping sebelumnya tetap disimpan."
                    )
                else:
                    st.success("Mapping berhasil disimpan.")

                st.rerun()

            except Exception as exc:
                st.error(f"Mapping gagal disimpan: {exc}")

    st.divider()
    st.markdown("#### Mapping yang Tersimpan")

    try:
        mappings = _load_transformer_feeder_bay_mappings()
    except Exception as exc:
        st.error(f"Daftar mapping tidak dapat dimuat: {exc}")
        return

    if not mappings:
        st.info("Belum ada mapping Trafo-Bay yang tersimpan.")
        return

    mapping_df = pd.DataFrame(mappings)

    rename = {
        "gi_name": "Gardu Induk",
        "transformer_bay_name": "Bay Trafo",
        "techidentno": "TECHIDENTNO",
        "rated_power_mva": "Daya (MVA)",
        "feeder_bay_name": "Bay Penyulang",
        "feeder_bay_functloc_id": "Functloc Bay Penyulang",
        "feeder_count": "Jumlah Penyulang",
        "feeder_names": "Daftar Penyulang",
        "valid_from": "Berlaku Mulai",
        "valid_to": "Berlaku Sampai",
        "is_active": "Aktif",
        "notes": "Catatan",
    }

    wanted = [
        column
        for column in rename
        if column in mapping_df.columns
    ]

    st.dataframe(
        mapping_df[wanted].rename(columns=rename),
        use_container_width=True,
        hide_index=True,
        height=430,
    )


def render() -> None:
    render_sidebar()

    st.title("Import Data Trafo PST")
    st.caption(
        "Master aset Trafo Daya berbasis data PLN. "
        "TECHIDENTNO digunakan sebagai external business key untuk sinkronisasi."
    )

    tab_master, tab_import, tab_mapping = st.tabs(
        ["Master Data", "Import Excel PLN", "Mapping Trafo ↔ Bay Penyulang"]
    )

    with tab_master:
        search = st.text_input(
            "Cari Trafo",
            placeholder="TECHIDENTNO, GI, merk, atau tipe...",
            key="transformer_master_search",
        )

        try:
            rows = _load_transformers(search.strip())
        except Exception as exc:
            st.error(f"Gagal memuat master Trafo: {exc}")
            rows = []

        _summary_cards(rows)
        st.divider()
        _master_table(rows)

    with tab_import:
        if not _can_import_transformer():
            st.info(
                "Import master Trafo hanya tersedia untuk ADMIN / SUPER_ADMIN. "
                "Anda tetap dapat melihat master data sesuai scope akses."
            )
            return

        st.subheader("Import Excel Master Trafo PLN")
        st.caption(
            "Upload → Filter → Preview → Validasi → Import. "
            "Aset yang tidak dipilih oleh filter tidak akan diproses."
        )

        last_result = st.session_state.pop(
            "transformer_import_last_result",
            None,
        )

        if isinstance(last_result, dict):
            st.success("Import master Trafo selesai.")

            r1, r2, r3, r4 = st.columns(4)
            r1.metric(
                "Diproses",
                last_result.get("processed", 0),
            )
            r2.metric(
                "Insert Baru",
                last_result.get("inserted", 0),
            )
            r3.metric(
                "Update",
                last_result.get("updated", 0),
            )
            r4.metric(
                "Gagal / Skip",
                last_result.get("skipped", 0),
            )

            st.caption(
                f"Batch ID: {last_result.get('source_batch_id', '-')}"
            )

            errors = last_result.get("errors")
            if isinstance(errors, list) and errors:
                st.error("Sebagian data gagal diproses oleh database.")
                st.dataframe(
                    pd.DataFrame(errors),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info(
                    "Master Data sudah diperbarui. "
                    "Buka tab Master Data untuk melihat hasil terbaru."
                )

        uploaded_file = st.file_uploader(
            "Pilih file export Excel PLN",
            type=["xlsx"],
            key="transformer_import_file",
        )

        if uploaded_file is None:
            st.info("Upload file .xlsx untuk memulai.")
            return

        try:
            with st.spinner("Membaca file Excel..."):
                source_preview = load_transformer_source(
                    uploaded_file,
                    file_name=uploaded_file.name,
                )
        except Exception as exc:
            st.error(f"File tidak dapat dibaca: {exc}")
            return

        f1, f2, f3 = st.columns(3)
        f1.metric("Baris Sumber", source_preview.source_rows)
        f2.metric("Header Excel", f"Baris {source_preview.header_row}")
        f3.metric("Sheet", source_preview.sheet_name)

        st.divider()

        filters = _render_import_filters(source_preview)

        try:
            preview = prepare_transformer_import(
                source_preview=source_preview,
                filters=filters,
            )
        except Exception as exc:
            st.error(f"Preview filter gagal dibuat: {exc}")
            return

        st.markdown("### Ringkasan Seleksi")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Data Sumber", preview.source_rows)
        m2.metric("Terpilih", preview.selected_rows)
        m3.metric("Tidak Diimport", preview.filtered_out_rows)
        m4.metric("Valid", preview.valid_rows)

        if preview.selected_rows == 0:
            st.warning(
                "Tidak ada data yang sesuai filter. Ubah pilihan filter untuk melanjutkan."
            )
            return

        if preview.duplicate_keys:
            st.error(
                f"Ditemukan {len(preview.duplicate_keys)} TECHIDENTNO duplikat "
                "di dalam data terpilih."
            )

        if preview.issues:
            st.markdown("### Hasil Validasi")
            issue_df = issues_for_display(preview)
            st.dataframe(
                issue_df,
                use_container_width=True,
                hide_index=True,
                height=min(360, 42 + len(issue_df) * 35),
            )
        else:
            st.success("Data terpilih lolos validasi awal tanpa error/warning.")

        st.markdown("### Preview Data yang Akan Diimport")
        preview_df = preview_rows_for_display(preview, limit=200)
        st.dataframe(
            preview_df,
            use_container_width=True,
            hide_index=True,
            height=430,
        )

        if preview.has_blocking_issues:
            st.warning(
                "Import belum dapat dijalankan karena masih terdapat ERROR."
            )
            return

        st.info(
            "Import hanya melakukan INSERT/UPDATE untuk data yang dipilih. "
            "Aset lain yang tidak ada atau tidak dipilih tidak akan dihapus "
            "dan tidak akan diubah otomatis."
        )

        confirm = st.checkbox(
            f"Saya sudah memeriksa {preview.selected_rows} data terpilih dan ingin mengimpornya.",
            key="confirm_transformer_import",
        )

        if st.button(
            "Import Data Terpilih ke Database",
            type="primary",
            disabled=not confirm,
            use_container_width=True,
        ):
            try:
                with st.spinner("Mengimpor master Trafo ke Supabase..."):
                    result = import_transformers(preview)

                _load_transformers.clear()

                # Simpan ringkasan hasil import agar tetap dapat ditampilkan
                # setelah Streamlit melakukan rerun.
                st.session_state["transformer_import_last_result"] = {
                    "processed": result.processed,
                    "inserted": result.inserted,
                    "updated": result.updated,
                    "skipped": result.skipped,
                    "errors": result.errors,
                    "source_batch_id": result.source_batch_id,
                }

                # Paksa rerun agar tab Master Data membaca database terbaru
                # setelah cache dibersihkan.
                st.rerun()

            except Exception as exc:
                st.error(f"Import gagal: {exc}")

    with tab_mapping:
        _render_mapping_tab()


render()
