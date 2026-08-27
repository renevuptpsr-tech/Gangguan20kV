from __future__ import annotations

from collections import defaultdict
from typing import Any

import streamlit as st

from components.login_form import render_login_form
from components.sidebar import hide_sidebar, render_sidebar
from services.auth_service import is_authenticated
from services.profile_service import (
    change_my_password,
    clear_profile_cache,
    get_my_assignments,
    get_my_profile,
    get_my_unit_users,
)


st.set_page_config(
    page_title="Profil Saya | Gangguan Penyulang 20 kV",
    page_icon="👤",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ==========================================================
# HELPERS
# ==========================================================


def _text(
    value: Any,
    fallback: str = "-",
) -> str:
    if value is None:
        return fallback

    result = str(value).strip()
    return result if result else fallback


def _bool_label(
    value: Any,
) -> str:
    return "Ya" if bool(value) else "Tidak"


def _assignment_rows(
    assignments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for row in assignments:
        role_code = str(
            row.get("role_code")
            or ""
        ).strip().upper()

        unit_name = (
            "Global"
            if role_code == "SUPER_ADMIN"
            else _text(
                row.get("unit_name")
            )
        )

        rows.append(
            {
                "Role":
                    _text(
                        row.get("role_name")
                    ),

                "Unit Access":
                    unit_name,

                "Include Child":
                    _bool_label(
                        row.get(
                            "include_children"
                        )
                    ),

                "Primary":
                    _bool_label(
                        row.get(
                            "is_primary"
                        )
                    ),
            }
        )

    return rows


def _unit_user_row(
    row: dict[str, Any],
) -> dict[str, Any]:
    return {
        "Nama":
            _text(
                row.get("full_name")
            ),

        "NIP":
            _text(
                row.get("employee_id")
            ),

        "Jabatan":
            _text(
                row.get("position_name")
            ),

        "Role":
            _text(
                row.get("roles")
            ),

        "Email":
            _text(
                row.get("email")
            ),
    }


def _filter_unit_users(
    users: list[dict[str, Any]],
    keyword: str,
) -> list[dict[str, Any]]:
    keyword_clean = (
        keyword
        .strip()
        .lower()
    )

    if not keyword_clean:
        return users

    result: list[dict[str, Any]] = []

    for row in users:
        haystack = " ".join(
            [
                _text(
                    row.get("full_name"),
                    "",
                ),
                _text(
                    row.get("employee_id"),
                    "",
                ),
                _text(
                    row.get("position_name"),
                    "",
                ),
                _text(
                    row.get("default_unit_name"),
                    "",
                ),
                _text(
                    row.get("roles"),
                    "",
                ),
                _text(
                    row.get("email"),
                    "",
                ),
            ]
        ).lower()

        if keyword_clean in haystack:
            result.append(
                row
            )

    return result


def _group_users_by_unit(
    users: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for row in users:
        unit_name = _text(
            row.get(
                "default_unit_name"
            ),
            "Tanpa Unit Default",
        )

        grouped[
            unit_name
        ].append(
            row
        )

    return dict(
        sorted(
            grouped.items(),
            key=lambda item:
                item[0].lower(),
        )
    )


def _render_profile_header(
    profile: dict[str, Any],
    assignments: list[dict[str, Any]],
    unit_users: list[dict[str, Any]],
) -> None:
    title_col, refresh_col = st.columns(
        [5.6, 1.0]
    )

    with title_col:
        st.title(
            "Profil Saya"
        )

        st.caption(
            "Informasi account, role, unit access, "
            "dan user yang berada dalam scope unit Anda."
        )

    with refresh_col:
        st.write("")
        st.write("")

        if st.button(
            "Refresh",
            icon=":material/refresh:",
            use_container_width=True,
            key="profile_refresh_top",
        ):
            clear_profile_cache()
            st.rerun()

    st.divider()

    m1, m2, m3 = st.columns(3)

    with m1:
        st.metric(
            "Role / Access Aktif",
            len(
                assignments
            ),
        )

    with m2:
        unit_count = len(
            {
                _text(
                    row.get(
                        "default_unit_name"
                    ),
                    "Tanpa Unit Default",
                )
                for row
                in unit_users
            }
        )

        st.metric(
            "Unit Terlihat",
            unit_count,
        )

    with m3:
        st.metric(
            "User Dalam Scope",
            len(
                unit_users
            ),
        )

    st.markdown(
        "### Informasi Account"
    )

    with st.container(
        border=True
    ):
        c1, c2, c3, c4 = st.columns(4)

        with c1:
            st.caption(
                "Nama Lengkap"
            )
            st.write(
                _text(
                    profile.get(
                        "full_name"
                    )
                )
            )

        with c2:
            st.caption(
                "NIP / Employee ID"
            )
            st.write(
                _text(
                    profile.get(
                        "employee_id"
                    )
                )
            )

        with c3:
            st.caption(
                "Jabatan"
            )
            st.write(
                _text(
                    profile.get(
                        "position_name"
                    )
                )
            )

        with c4:
            st.caption(
                "Unit Default"
            )
            st.write(
                _text(
                    profile.get(
                        "default_unit_name"
                    )
                )
            )

        st.caption(
            "Email Login"
        )
        st.write(
            _text(
                profile.get(
                    "email"
                )
            )
        )


def _render_my_access(
    assignments: list[dict[str, Any]],
) -> None:
    st.markdown(
        "### Role & Unit Access Saya"
    )

    if not assignments:
        st.info(
            "Belum ada role / unit access aktif."
        )
        return

    st.dataframe(
        _assignment_rows(
            assignments
        ),
        use_container_width=True,
        hide_index=True,
    )


def _render_change_password() -> None:
    st.markdown(
        "### Keamanan Account"
    )

    with st.expander(
        "Ubah Password",
        expanded=False,
        icon=":material/password:",
    ):
        st.caption(
            "Password baru minimal 8 karakter. "
            "Perubahan berlaku langsung untuk login berikutnya."
        )

        p1, p2 = st.columns(2)

        with p1:
            new_password = st.text_input(
                "Password Baru",
                type="password",
                key="profile_new_password",
            )

        with p2:
            confirm_password = st.text_input(
                "Konfirmasi Password",
                type="password",
                key="profile_confirm_password",
            )

        if st.button(
            "Simpan Password Baru",
            type="primary",
            icon=":material/save:",
            key="profile_save_password",
        ):
            if len(
                new_password
            ) < 8:
                st.error(
                    "Password minimal 8 karakter."
                )
                return

            if (
                new_password
                != confirm_password
            ):
                st.error(
                    "Konfirmasi password tidak sesuai."
                )
                return

            try:
                with st.spinner(
                    "Memperbarui password..."
                ):
                    change_my_password(
                        password=
                            new_password
                    )

                st.success(
                    "Password berhasil diperbarui."
                )

            except Exception as exc:
                st.error(
                    "Password tidak berhasil diperbarui."
                )
                st.exception(
                    exc
                )


def _render_unit_users(
    users: list[dict[str, Any]],
) -> None:
    st.markdown(
        "### Daftar User Unit"
    )

    st.caption(
        "User aktif yang berada pada scope unit yang "
        "dapat Anda akses. Daftar dikelompokkan berdasarkan Unit Default."
    )

    if not users:
        st.info(
            "Belum ada user aktif pada scope unit Anda."
        )
        return

    search = st.text_input(
        "Cari User Unit",
        placeholder=(
            "Cari nama, NIP, jabatan, unit, role, atau email..."
        ),
        key="profile_unit_user_search",
    )

    filtered_users = _filter_unit_users(
        users,
        search,
    )

    grouped = _group_users_by_unit(
        filtered_users
    )

    unit_count = len(
        grouped
    )

    total_users = len(
        filtered_users
    )

    c1, c2 = st.columns(2)

    with c1:
        st.caption(
            f"{total_users} user ditampilkan"
        )

    with c2:
        st.caption(
            f"{unit_count} unit"
        )

    if not filtered_users:
        st.info(
            "Tidak ada user yang sesuai dengan pencarian."
        )
        return

    for index, (
        unit_name,
        unit_rows,
    ) in enumerate(
        grouped.items()
    ):
        expanded = (
            len(
                grouped
            ) <= 3
            or index == 0
        )

        with st.expander(
            f"{unit_name} · {len(unit_rows)} User",
            expanded=expanded,
            icon=":material/domain:",
        ):
            st.dataframe(
                [
                    _unit_user_row(
                        row
                    )
                    for row
                    in unit_rows
                ],
                use_container_width=True,
                hide_index=True,
                height=min(
                    350,
                    55
                    + (
                        36
                        * len(
                            unit_rows
                        )
                    ),
                ),
            )


def render_page() -> None:
    render_sidebar()

    try:
        profile = get_my_profile()
        assignments = get_my_assignments()
        unit_users = get_my_unit_users()

    except Exception as exc:
        st.error(
            "Data Profil Saya tidak dapat dibaca."
        )
        st.exception(
            exc
        )
        return

    if not profile:
        st.warning(
            "Profile account belum tersedia."
        )
        return

    _render_profile_header(
        profile,
        assignments,
        unit_users,
    )

    st.divider()

    _render_my_access(
        assignments
    )

    st.divider()

    _render_change_password()

    st.divider()

    _render_unit_users(
        unit_users
    )


def main() -> None:
    if not is_authenticated():
        hide_sidebar()
        render_login_form()
        st.stop()

    render_page()


if __name__ == "__main__":
    main()