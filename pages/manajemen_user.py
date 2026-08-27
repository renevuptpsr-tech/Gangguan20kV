from __future__ import annotations

from typing import Any

import streamlit as st

from components.login_form import render_login_form
from components.sidebar import hide_sidebar, render_sidebar
from services.access_service import (
    can_manage_access,
    is_super_admin,
)
from services.auth_service import is_authenticated
from services.user_management_service import (
    add_multiple_user_assignments,
    clear_user_management_cache,
    create_user,
    get_assignable_roles,
    get_manageable_functlocs,
    get_user_assignments,
    get_users,
    reset_user_password,
    set_assignment_active,
    set_multiple_assignments_active,
    sync_user_access,
    set_user_active,
    update_user_profile,
)


st.set_page_config(
    page_title="Manajemen User | Gangguan Penyulang 20 kV",
    page_icon="👥",
    layout="wide",
    initial_sidebar_state="expanded",
)


KEY_SELECTED_USER = "mu_selected_user_id"
KEY_SEARCH = "mu_search"
KEY_STATUS_FILTER = "mu_status_filter"
KEY_FORM_MODE = "mu_form_mode"
KEY_FORM_NOTICE = "mu_form_notice"


def _text(
    value: Any,
    fallback: str = "-",
) -> str:
    if value is None:
        return fallback

    result = str(value).strip()
    return result if result else fallback


def _status_label(
    value: Any,
) -> str:
    return "Aktif" if bool(value) else "Nonaktif"


def _yes_no(
    value: Any,
) -> str:
    return "Ya" if bool(value) else "Tidak"


def _role_display(
    row: dict[str, Any],
) -> str:
    name = _text(
        row.get("role_name"),
        "",
    )

    code = _text(
        row.get("role_code"),
        "",
    )

    if name and code:
        return f"{name} ({code})"

    return name or code or "-"


def _scope_display(
    row: dict[str, Any],
) -> str:
    role_code = str(
        row.get("role_code")
        or ""
    ).strip().upper()

    if role_code == "SUPER_ADMIN":
        return "Global"

    name = _text(
        row.get("unit_name"),
        "",
    )

    functloc_id = _text(
        row.get("functloc_id"),
        "",
    )

    if name and functloc_id:
        return f"{name} | {functloc_id}"

    return name or functloc_id or "-"


def _functloc_display(
    row: dict[str, Any],
) -> str:
    name = _text(
        row.get("location_name"),
        "",
    )

    short_name = _text(
        row.get("short_name"),
        "",
    )

    functloc_id = _text(
        row.get("functloc_id"),
        "",
    )

    nlevel = row.get("nlevel")

    pieces: list[str] = []

    if short_name:
        pieces.append(short_name)
    elif name:
        pieces.append(name)

    if name and name != short_name:
        pieces.append(name)

    if functloc_id:
        pieces.append(functloc_id)

    if nlevel is not None:
        pieces.append(f"L{nlevel}")

    return " | ".join(pieces)


def _find_user(
    users: list[dict[str, Any]],
    user_id: str | None,
) -> dict[str, Any] | None:
    if not user_id:
        return None

    for row in users:
        if str(
            row.get("user_id")
            or ""
        ) == str(user_id):
            return row

    return None


def _filter_users(
    users: list[dict[str, Any]],
    search_text: str,
    status_filter: str,
) -> list[dict[str, Any]]:
    keyword = (
        search_text
        .strip()
        .lower()
    )

    result: list[dict[str, Any]] = []

    for row in users:
        if keyword:
            haystack = " ".join(
                [
                    _text(
                        row.get("full_name"),
                        "",
                    ),
                    _text(
                        row.get("email"),
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
                ]
            ).lower()

            if keyword not in haystack:
                continue

        active = bool(
            row.get("is_active")
        )

        if (
            status_filter == "Aktif"
            and not active
        ):
            continue

        if (
            status_filter == "Nonaktif"
            and active
        ):
            continue

        result.append(row)

    return result


def _set_notice(
    message: str,
) -> None:
    st.session_state[
        KEY_FORM_NOTICE
    ] = message


def _render_notice() -> None:
    notice = st.session_state.pop(
        KEY_FORM_NOTICE,
        None,
    )

    if notice:
        st.success(notice)


def _load_form_masters() -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    roles = get_assignable_roles()
    functlocs = get_manageable_functlocs()

    role_map = {
        str(
            row.get("role_code")
            or ""
        ).strip().upper():
            row
        for row in roles
        if str(
            row.get("role_code")
            or ""
        ).strip()
    }

    functloc_map = {
        str(
            row.get("functloc_id")
            or ""
        ).strip():
            row
        for row in functlocs
        if str(
            row.get("functloc_id")
            or ""
        ).strip()
    }

    return (
        role_map,
        functloc_map,
    )


def _render_summary(
    users: list[dict[str, Any]],
) -> None:
    total = len(users)

    active = sum(
        1
        for row in users
        if bool(row.get("is_active"))
    )

    inactive = total - active

    total_role = sum(
        int(
            row.get("role_count")
            or 0
        )
        for row in users
    )

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric(
            "Total User",
            total,
        )

    with c2:
        st.metric(
            "User Aktif",
            active,
        )

    with c3:
        st.metric(
            "User Nonaktif",
            inactive,
        )

    with c4:
        st.metric(
            "Role Aktif",
            total_role,
        )


def _user_table_rows(
    users: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "Nama":
                _text(
                    row.get("full_name")
                ),

            "Email":
                _text(
                    row.get("email")
                ),

            "NIP":
                _text(
                    row.get("employee_id")
                ),

            "Jabatan":
                _text(
                    row.get("position_name")
                ),

            "Unit Default":
                _text(
                    row.get("default_unit_name")
                ),

            "Role":
                int(
                    row.get("role_count")
                    or 0
                ),

            "Status":
                _status_label(
                    row.get("is_active")
                ),
        }
        for row in users
    ]


def _render_user_table(
    users: list[dict[str, Any]],
) -> str | None:
    event = st.dataframe(
        _user_table_rows(
            users
        ),
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        height=360,
        key="mu_user_table",
    )

    try:
        selected_rows = list(
            event.selection.rows
        )
    except Exception:
        selected_rows = []

    if selected_rows:
        index = selected_rows[0]

        if 0 <= index < len(users):
            selected_user_id = str(
                users[index].get(
                    "user_id"
                )
                or ""
            ).strip()

            if selected_user_id:
                previous = (
                    st.session_state.get(
                        KEY_SELECTED_USER
                    )
                )

                if previous != selected_user_id:
                    st.session_state[
                        KEY_SELECTED_USER
                    ] = selected_user_id

                    st.session_state[
                        KEY_FORM_MODE
                    ] = "NONE"

    selected = (
        st.session_state.get(
            KEY_SELECTED_USER
        )
    )

    return (
        str(selected)
        if selected
        else None
    )


def _render_access_list(
    assignments: list[dict[str, Any]],
) -> None:
    if not assignments:
        st.info(
            "User belum memiliki role / unit access."
        )
        return

    st.caption(
        "Pilih satu atau beberapa assignment untuk "
        "mengaktifkan / menonaktifkan access sekaligus."
    )

    selectable: list[dict[str, Any]] = []
    id_map: dict[str, dict[str, Any]] = {}

    for assignment in assignments:
        assignment_id = str(
            assignment.get("assignment_id")
            or ""
        ).strip()

        if not assignment_id:
            continue

        role_code = str(
            assignment.get("role_code")
            or ""
        ).strip().upper()

        protected = (
            role_code
            in {
                "ADMIN",
                "SUPER_ADMIN",
            }
            and not is_super_admin()
        )

        label = (
            f"{_role_display(assignment)}"
            f"  •  {_scope_display(assignment)}"
            f"  •  {'Aktif' if bool(assignment.get('is_active')) else 'Nonaktif'}"
        )

        selectable.append(
            {
                "id":
                    assignment_id,

                "label":
                    label,

                "protected":
                    protected,
            }
        )

        id_map[
            assignment_id
        ] = assignment

    available_ids = [
        row["id"]
        for row in selectable
        if not row["protected"]
    ]

    selected_ids = st.multiselect(
        "Pilih Access",
        options=
            available_ids,
        format_func=lambda assignment_id:
            next(
                (
                    row["label"]
                    for row in selectable
                    if row["id"]
                    == assignment_id
                ),
                assignment_id,
            ),
        placeholder=(
            "Pilih satu atau beberapa assignment"
        ),
        key="mu_bulk_access_selection",
    )

    c1, c2, c3 = st.columns(
        [1.5, 1.5, 4.0]
    )

    with c1:
        if st.button(
            "Aktifkan Dipilih",
            icon=":material/check_circle:",
            use_container_width=True,
            disabled=
                not selected_ids,
            key="mu_bulk_activate",
        ):
            try:
                with st.spinner(
                    "Mengaktifkan access..."
                ):
                    total = (
                        set_multiple_assignments_active(
                            assignment_ids=
                                selected_ids,
                            is_active=True,
                        )
                    )

                _set_notice(
                    f"{total} assignment berhasil diaktifkan."
                )

                st.session_state.pop(
                    "mu_bulk_access_selection",
                    None,
                )

                st.rerun()

            except Exception as exc:
                st.error(
                    "Access tidak berhasil diaktifkan."
                )
                st.exception(
                    exc
                )

    with c2:
        if st.button(
            "Nonaktifkan Dipilih",
            icon=":material/block:",
            use_container_width=True,
            disabled=
                not selected_ids,
            key="mu_bulk_deactivate",
        ):
            try:
                with st.spinner(
                    "Menonaktifkan access..."
                ):
                    total = (
                        set_multiple_assignments_active(
                            assignment_ids=
                                selected_ids,
                            is_active=False,
                        )
                    )

                _set_notice(
                    f"{total} assignment berhasil dinonaktifkan."
                )

                st.session_state.pop(
                    "mu_bulk_access_selection",
                    None,
                )

                st.rerun()

            except Exception as exc:
                st.error(
                    "Access tidak berhasil dinonaktifkan."
                )
                st.exception(
                    exc
                )

    st.divider()

    for assignment in assignments:
        assignment_id = str(
            assignment.get("assignment_id")
            or ""
        ).strip()

        role_code = str(
            assignment.get("role_code")
            or ""
        ).strip().upper()

        active = bool(
            assignment.get("is_active")
        )

        protected = (
            role_code
            in {
                "ADMIN",
                "SUPER_ADMIN",
            }
            and not is_super_admin()
        )

        with st.container(
            border=True
        ):
            c1, c2, c3, c4 = st.columns(
                [
                    1.7,
                    3.0,
                    1.3,
                    1.15,
                ]
            )

            with c1:
                st.caption("Role")
                st.write(
                    _role_display(
                        assignment
                    )
                )

            with c2:
                st.caption("Unit Access")
                st.write(
                    _scope_display(
                        assignment
                    )
                )

            with c3:
                st.caption("Include Child")
                st.write(
                    _yes_no(
                        assignment.get(
                            "include_children"
                        )
                    )
                )

                if bool(
                    assignment.get(
                        "is_primary"
                    )
                ):
                    st.caption("Primary")

            with c4:
                if active:
                    st.success("Aktif")
                else:
                    st.warning("Nonaktif")

                if st.button(
                    (
                        "Nonaktifkan"
                        if active
                        else "Aktifkan"
                    ),
                    use_container_width=True,
                    disabled=protected,
                    key=(
                        f"mu_access_"
                        f"{assignment_id}"
                    ),
                ):
                    try:
                        with st.spinner(
                            "Memperbarui akses..."
                        ):
                            set_assignment_active(
                                assignment_id=
                                    assignment_id,
                                is_active=(
                                    not active
                                ),
                            )

                        _set_notice(
                            "Status access berhasil diperbarui."
                        )

                        st.rerun()

                    except Exception as exc:
                        st.error(
                            "Access tidak berhasil diperbarui."
                        )
                        st.exception(exc)

                if protected:
                    st.caption(
                        "Hanya Super Admin"
                    )

def _render_create_user_form() -> None:
    st.subheader("Tambah User")

    st.caption(
        "Buat account Supabase Auth, password, multiple Role, "
        "dan multiple Unit Access dalam satu form."
    )

    try:
        (
            role_map,
            functloc_map,
        ) = _load_form_masters()

    except Exception as exc:
        st.error(
            "Master Role / Unit Access tidak dapat dibaca."
        )
        st.exception(exc)
        return

    with st.container(
        border=True
    ):
        c1, c2 = st.columns(2)

        with c1:
            full_name = st.text_input(
                "Nama Lengkap *",
                key="mu_create_full_name",
            )

            employee_id = st.text_input(
                "NIP / Employee ID",
                key="mu_create_employee_id",
            )

        with c2:
            email = st.text_input(
                "Email *",
                placeholder="nama@pln.co.id",
                key="mu_create_email",
            )

            position_name = st.text_input(
                "Jabatan",
                key="mu_create_position",
            )

        p1, p2 = st.columns(2)

        with p1:
            password = st.text_input(
                "Password *",
                type="password",
                help="Minimal 8 karakter.",
                key="mu_create_password",
            )

        with p2:
            confirm_password = st.text_input(
                "Konfirmasi Password *",
                type="password",
                key="mu_create_confirm_password",
            )

        st.divider()

        selected_roles = st.multiselect(
            "Role *",
            options=list(
                role_map.keys()
            ),
            format_func=lambda code:
                _role_display(
                    role_map[
                        code
                    ]
                ),
            placeholder=(
                "Pilih satu atau beberapa role"
            ),
            key="mu_create_roles",
        )

        has_super_admin = (
            "SUPER_ADMIN"
            in selected_roles
        )

        if has_super_admin:
            st.info(
                "SUPER_ADMIN menggunakan scope Global "
                "dan tidak dapat digabung dengan role lain."
            )

            selected_scopes: list[str] = []

        else:
            selected_scopes = st.multiselect(
                "Unit Access *",
                options=list(
                    functloc_map.keys()
                ),
                format_func=lambda code:
                    _functloc_display(
                        functloc_map[
                            code
                        ]
                    ),
                placeholder=(
                    "Pilih satu atau beberapa unit"
                ),
                key="mu_create_scopes",
            )

        include_children = st.checkbox(
            "Termasuk unit di bawah scope",
            value=True,
            disabled=has_super_admin,
            key="mu_create_children",
        )

        is_active = st.toggle(
            "User Aktif",
            value=True,
            key="mu_create_active",
        )

        if (
            selected_roles
            and selected_scopes
            and not has_super_admin
        ):
            total_assignment = (
                len(selected_roles)
                * len(selected_scopes)
            )

            st.caption(
                f"{len(selected_roles)} Role × "
                f"{len(selected_scopes)} Unit Access = "
                f"{total_assignment} assignment akan dibuat."
            )

        st.caption(
            "User langsung dibuat pada Supabase Auth. "
            "Tidak ada email invitation yang dikirim."
        )

        b1, b2 = st.columns(
            [1.5, 4.5]
        )

        with b1:
            save = st.button(
                "Simpan User",
                type="primary",
                use_container_width=True,
                key="mu_create_save",
            )

        with b2:
            if st.button(
                "Batal",
                key="mu_create_cancel",
            ):
                st.session_state[
                    KEY_FORM_MODE
                ] = "NONE"
                st.rerun()

        if save:
            if not full_name.strip():
                st.error(
                    "Nama Lengkap wajib diisi."
                )
                return

            if not email.strip():
                st.error(
                    "Email wajib diisi."
                )
                return

            if len(password) < 8:
                st.error(
                    "Password minimal 8 karakter."
                )
                return

            if password != confirm_password:
                st.error(
                    "Konfirmasi Password tidak sesuai."
                )
                return

            if not selected_roles:
                st.error(
                    "Minimal satu Role wajib dipilih."
                )
                return

            if (
                has_super_admin
                and len(
                    selected_roles
                ) > 1
            ):
                st.error(
                    "SUPER_ADMIN harus dipilih sendiri "
                    "tanpa role lain."
                )
                return

            if (
                not has_super_admin
                and not selected_scopes
            ):
                st.error(
                    "Minimal satu Unit Access wajib dipilih."
                )
                return

            try:
                with st.spinner(
                    "Membuat user dan access..."
                ):
                    result = create_user(
                        email=email,
                        password=password,
                        full_name=full_name,
                        employee_id=employee_id,
                        position_name=position_name,
                        role_codes=
                            selected_roles,
                        functloc_ids=
                            selected_scopes,
                        include_children=(
                            True
                            if has_super_admin
                            else include_children
                        ),
                        is_active=is_active,
                    )

                created_user_id = str(
                    result.get(
                        "user_id"
                    )
                    or ""
                ).strip()

                if created_user_id:
                    st.session_state[
                        KEY_SELECTED_USER
                    ] = created_user_id

                st.session_state[
                    KEY_FORM_MODE
                ] = "NONE"

                _set_notice(
                    "User berhasil dibuat langsung pada Supabase Auth. "
                    f"{int(result.get('assignment_count') or 0)} "
                    "assignment access dibuat."
                )

                st.rerun()

            except Exception as exc:
                st.error(
                    "User tidak berhasil dibuat."
                )
                st.exception(exc)


def _render_edit_user_form(
    user: dict[str, Any],
) -> None:
    user_id = str(
        user.get("user_id")
        or ""
    ).strip()

    user_active = bool(
        user.get("is_active")
    )

    try:
        (
            role_map,
            functloc_map,
        ) = _load_form_masters()

        assignments = (
            get_user_assignments(
                user_id
            )
        )

    except Exception as exc:
        st.error(
            "Data user / master access tidak dapat dibaca."
        )
        st.exception(exc)
        return

    st.subheader("Edit User")

    st.caption(
        "Profile dan access tambahan dikelola "
        "dalam satu form."
    )

    with st.container(
        border=True
    ):
        p1, p2 = st.columns(2)

        with p1:
            full_name = st.text_input(
                "Nama Lengkap *",
                value=_text(
                    user.get("full_name"),
                    "",
                ),
                key=f"mu_edit_name_{user_id}",
            )

            employee_id = st.text_input(
                "NIP / Employee ID",
                value=_text(
                    user.get("employee_id"),
                    "",
                ),
                key=f"mu_edit_employee_{user_id}",
            )

        with p2:
            st.text_input(
                "Email",
                value=_text(
                    user.get("email"),
                    "",
                ),
                disabled=True,
                help=(
                    "Email merupakan identitas login "
                    "Supabase Auth."
                ),
                key=f"mu_edit_email_{user_id}",
            )

            position_name = st.text_input(
                "Jabatan",
                value=_text(
                    user.get("position_name"),
                    "",
                ),
                key=f"mu_edit_position_{user_id}",
            )

        st.divider()

        active_assignments = [
            row
            for row
            in assignments
            if bool(
                row.get(
                    "is_active"
                )
            )
        ]

        existing_role_codes: list[str] = []

        for row in active_assignments:
            role_code = str(
                row.get(
                    "role_code"
                )
                or ""
            ).strip().upper()

            if (
                role_code
                and role_code in role_map
                and role_code
                not in existing_role_codes
            ):
                existing_role_codes.append(
                    role_code
                )

        selected_roles = st.multiselect(
            "Role Aktif *",
            options=list(
                role_map.keys()
            ),
            default=
                existing_role_codes,
            format_func=lambda code:
                _role_display(
                    role_map[
                        code
                    ]
                ),
            placeholder=(
                "Pilih satu atau beberapa role"
            ),
            key=f"mu_edit_roles_{user_id}",
        )

        has_super_admin = (
            "SUPER_ADMIN"
            in selected_roles
        )

        existing_scope_ids: list[str] = []

        if not has_super_admin:
            for row in active_assignments:
                functloc_id = str(
                    row.get(
                        "functloc_id"
                    )
                    or ""
                ).strip()

                if (
                    functloc_id
                    and functloc_id
                    in functloc_map
                    and functloc_id
                    not in existing_scope_ids
                ):
                    existing_scope_ids.append(
                        functloc_id
                    )

        if has_super_admin:
            st.info(
                "SUPER_ADMIN menggunakan scope Global "
                "dan tidak dapat digabung dengan role lain."
            )

            selected_scopes: list[str] = []

        else:
            selected_scopes = st.multiselect(
                "Unit Access Aktif *",
                options=list(
                    functloc_map.keys()
                ),
                default=
                    existing_scope_ids,
                format_func=lambda code:
                    _functloc_display(
                        functloc_map[
                            code
                        ]
                    ),
                placeholder=(
                    "Pilih satu atau beberapa unit"
                ),
                key=f"mu_edit_scopes_{user_id}",
            )

        include_children = st.checkbox(
            "Termasuk unit di bawah scope",
            value=True,
            disabled=has_super_admin,
            key=f"mu_edit_children_{user_id}",
        )

        if (
            selected_roles
            and selected_scopes
            and not has_super_admin
        ):
            st.caption(
                f"Kondisi akhir: {len(selected_roles)} Role × "
                f"{len(selected_scopes)} Unit Access = "
                f"{len(selected_roles) * len(selected_scopes)} "
                "assignment aktif."
            )

        st.caption(
            "Saat disimpan, assignment yang tidak lagi dipilih "
            "akan dinonaktifkan, bukan dihapus."
        )

        default_scope_options = [
            ""
        ] + list(
            functloc_map.keys()
        )

        current_default = str(
            user.get(
                "default_functloc_id"
            )
            or ""
        ).strip()

        default_index = (
            default_scope_options.index(
                current_default
            )
            if current_default
            in default_scope_options
            else 0
        )

        default_functloc_id = st.selectbox(
            "Unit Default",
            options=
                default_scope_options,
            index=
                default_index,
            format_func=lambda code:
                (
                    "Tidak ditetapkan"
                    if not code
                    else _functloc_display(
                        functloc_map[
                            code
                        ]
                    )
                ),
            key=f"mu_edit_default_{user_id}",
        )

        if is_super_admin():
            desired_user_active = st.toggle(
                "User Aktif",
                value=user_active,
                key=f"mu_edit_active_{user_id}",
            )
        else:
            desired_user_active = (
                user_active
            )

            st.toggle(
                "User Aktif",
                value=user_active,
                disabled=True,
                key=f"mu_edit_active_disabled_{user_id}",
            )

        if (
            selected_roles
            and selected_scopes
            and not has_super_admin
        ):
            st.caption(
                f"{len(selected_roles)} Role × "
                f"{len(selected_scopes)} Unit Access = "
                f"{len(selected_roles) * len(selected_scopes)} "
                "assignment akan ditambahkan / diaktifkan."
            )

        st.divider()

        st.markdown(
            "**Reset Password**"
        )

        st.caption(
            "Isi hanya jika password user perlu diganti. "
            "Kosongkan jika tidak ada perubahan password."
        )

        pw1, pw2 = st.columns(2)

        with pw1:
            new_password = st.text_input(
                "Password Baru",
                type="password",
                help="Minimal 8 karakter.",
                key=f"mu_reset_password_{user_id}",
            )

        with pw2:
            confirm_new_password = st.text_input(
                "Konfirmasi Password Baru",
                type="password",
                key=f"mu_reset_password_confirm_{user_id}",
            )

        b1, b2 = st.columns(
            [1.6, 4.4]
        )

        with b1:
            save = st.button(
                "Simpan Perubahan",
                type="primary",
                use_container_width=True,
                key=f"mu_edit_save_{user_id}",
            )

        with b2:
            if st.button(
                "Batal",
                key=f"mu_edit_cancel_{user_id}",
            ):
                st.session_state[
                    KEY_FORM_MODE
                ] = "NONE"
                st.rerun()

        if save:
            if not full_name.strip():
                st.error(
                    "Nama Lengkap wajib diisi."
                )
                return

            if (
                has_super_admin
                and len(
                    selected_roles
                ) > 1
            ):
                st.error(
                    "SUPER_ADMIN harus dipilih sendiri."
                )
                return

            if not selected_roles:
                st.error(
                    "Minimal satu Role wajib dipilih."
                )
                return

            if (
                has_super_admin
                and len(
                    selected_roles
                ) > 1
            ):
                st.error(
                    "SUPER_ADMIN harus dipilih sendiri."
                )
                return

            if (
                not has_super_admin
                and not selected_scopes
            ):
                st.error(
                    "Minimal satu Unit Access wajib dipilih."
                )
                return

            if new_password:
                if len(new_password) < 8:
                    st.error(
                        "Password baru minimal 8 karakter."
                    )
                    return

                if new_password != confirm_new_password:
                    st.error(
                        "Konfirmasi Password Baru tidak sesuai."
                    )
                    return

            try:
                with st.spinner(
                    "Menyimpan perubahan user..."
                ):
                    update_user_profile(
                        user_id=user_id,
                        full_name=full_name,
                        employee_id=employee_id,
                        position_name=position_name,
                        default_functloc_id=(
                            default_functloc_id
                            or None
                        ),
                    )

                    sync_result = sync_user_access(
                        user_id=user_id,
                        role_codes=
                            selected_roles,
                        functloc_ids=
                            selected_scopes,
                        include_children=(
                            True
                            if has_super_admin
                            else include_children
                        ),
                    )

                    if (
                        is_super_admin()
                        and desired_user_active
                        != user_active
                    ):
                        set_user_active(
                            user_id=user_id,
                            is_active=
                                desired_user_active,
                        )

                    if new_password:
                        reset_user_password(
                            user_id=user_id,
                            password=new_password,
                        )

                clear_user_management_cache()

                st.session_state[
                    KEY_FORM_MODE
                ] = "NONE"

                _set_notice(
                    "Perubahan user berhasil disimpan. "
                    f"{int(sync_result.get('active_assignment_count') or 0)} "
                    "assignment aktif setelah sinkronisasi."
                )

                st.rerun()

            except Exception as exc:
                st.error(
                    "Perubahan user tidak berhasil disimpan."
                )
                st.exception(exc)

    st.markdown(
        "#### Access Saat Ini"
    )

    _render_access_list(
        assignments
    )


def _render_selected_user(
    user: dict[str, Any],
) -> None:
    user_id = str(
        user.get("user_id")
        or ""
    ).strip()

    try:
        assignments = get_user_assignments(
            user_id
        )

    except Exception as exc:
        st.error(
            "Role dan Unit Access user tidak dapat dibaca."
        )
        st.exception(exc)
        return

    left, right = st.columns(
        [5.2, 1.4]
    )

    with left:
        st.subheader(
            _text(
                user.get("full_name"),
                "User",
            )
        )

        subtitle = " • ".join(
            item
            for item in [
                _text(
                    user.get("email"),
                    "",
                ),
                _text(
                    user.get("employee_id"),
                    "",
                ),
                _text(
                    user.get("position_name"),
                    "",
                ),
            ]
            if item
        )

        if subtitle:
            st.caption(subtitle)

    with right:
        if bool(
            user.get("is_active")
        ):
            st.success("User Aktif")
        else:
            st.warning("User Nonaktif")

        if st.button(
            "Edit User",
            icon=":material/edit:",
            type="primary",
            use_container_width=True,
            key="mu_open_edit",
        ):
            st.session_state[
                KEY_FORM_MODE
            ] = "EDIT"
            st.rerun()

    if (
        st.session_state.get(
            KEY_FORM_MODE
        )
        == "EDIT"
    ):
        st.divider()

        _render_edit_user_form(
            user
        )

    else:
        st.markdown(
            "#### Access Saat Ini"
        )

        _render_access_list(
            assignments
        )


def render_page() -> None:
    render_sidebar()

    if not can_manage_access():
        st.error(
            "Anda tidak memiliki akses ke Manajemen User."
        )
        st.stop()

    _render_notice()

    h1, h2 = st.columns(
        [5.5, 1.35]
    )

    with h1:
        st.title(
            "Manajemen User"
        )

        st.caption(
            "Kelola user, multiple Role, dan multiple "
            "Unit Access secara terpusat."
        )

    with h2:
        st.write("")
        st.write("")

        if st.button(
            "Tambah User",
            icon=":material/person_add:",
            type="primary",
            use_container_width=True,
            key="mu_add_user",
        ):
            st.session_state[
                KEY_FORM_MODE
            ] = "CREATE"

            st.session_state.pop(
                KEY_SELECTED_USER,
                None,
            )

            st.rerun()

    try:
        users = get_users()

    except Exception as exc:
        st.error(
            "Daftar user tidak dapat dibaca."
        )
        st.exception(exc)
        return

    _render_summary(
        users
    )

    st.divider()

    if (
        st.session_state.get(
            KEY_FORM_MODE
        )
        == "CREATE"
    ):
        _render_create_user_form()
        st.divider()

    f1, f2, f3 = st.columns(
        [4.2, 1.5, 1.0]
    )

    with f1:
        search_text = st.text_input(
            "Cari User",
            placeholder=(
                "Cari nama, email, NIP, jabatan, atau unit..."
            ),
            key=KEY_SEARCH,
        )

    with f2:
        status_filter = st.selectbox(
            "Status",
            options=[
                "Semua",
                "Aktif",
                "Nonaktif",
            ],
            key=KEY_STATUS_FILTER,
        )

    with f3:
        st.write("")
        st.write("")

        if st.button(
            "Refresh",
            icon=":material/refresh:",
            use_container_width=True,
            key="mu_refresh",
        ):
            clear_user_management_cache()
            st.rerun()

    filtered_users = _filter_users(
        users,
        search_text,
        status_filter,
    )

    st.caption(
        f"Menampilkan {len(filtered_users)} "
        f"dari {len(users)} user."
    )

    if not filtered_users:
        st.info(
            "Tidak ada user yang sesuai dengan filter."
        )
        return

    selected_user_id = _render_user_table(
        filtered_users
    )

    if not selected_user_id:
        if (
            st.session_state.get(
                KEY_FORM_MODE
            )
            != "CREATE"
        ):
            st.info(
                "Klik satu baris user untuk melihat "
                "dan mengelola access."
            )

        return

    selected_user = _find_user(
        users,
        selected_user_id,
    )

    if selected_user is None:
        st.session_state.pop(
            KEY_SELECTED_USER,
            None,
        )

        st.warning(
            "User yang dipilih tidak ditemukan."
        )
        return

    st.divider()

    _render_selected_user(
        selected_user
    )


def main() -> None:
    if not is_authenticated():
        hide_sidebar()
        render_login_form()
        st.stop()

    render_page()


if __name__ == "__main__":
    main()