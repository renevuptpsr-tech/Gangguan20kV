from __future__ import annotations

import html

import streamlit as st

from services.access_service import (
    can_input,
    can_manage_access,
    can_verify,
    can_view,
    clear_access_cache,
    get_role_labels,
)
from services.auth_service import (
    get_current_user,
    sign_out,
)
from services.hierarchy_service import (
    clear_hierarchy_cache,
)


# ==========================================================
# MENU RULES
# ==========================================================


def _can_open_monthly_workflow() -> bool:
    return can_input() or can_verify()


def _can_open_monthly_monitoring() -> bool:
    # Monitoring dapat dilihat semua user yang mempunyai hak view.
    return can_view()


def _can_open_transformer_import() -> bool:
    """
    Gunakan capability, bukan nama/label role.

    Sebelumnya menu Tools dicek berdasarkan label:
    ADMIN / SUPER_ADMIN.

    Di UI role dapat tampil sebagai "Super Administrator",
    sehingga pengecekan string tersebut gagal.

    can_manage_access() sudah menjadi capability yang tepat
    untuk ADMIN / SUPER_ADMIN pada aplikasi ini.
    """
    return can_manage_access()


# ==========================================================
# LOGIN SIDEBAR VISIBILITY
# ==========================================================


def hide_sidebar() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] {
            display: none;
        }

        [data-testid="collapsedControl"] {
            display: none;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ==========================================================
# SIDEBAR STYLE
# ==========================================================


def _apply_sidebar_style() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] {
            min-width: 300px;
            max-width: 300px;
        }

        [data-testid="stSidebar"] > div:first-child {
            padding-top: 0.95rem;
            padding-left: 0.9rem;
            padding-right: 0.9rem;
        }

        [data-testid="stSidebar"] [data-testid="stPageLink"] {
            border-radius: 10px;
            margin-bottom: 0.12rem;
            transition:
                background-color 0.15s ease,
                transform 0.15s ease;
        }

        [data-testid="stSidebar"] [data-testid="stPageLink"]:hover {
            background: rgba(128, 128, 128, 0.08);
        }

        [data-testid="stSidebar"] hr {
            margin-top: 0.85rem;
            margin-bottom: 0.85rem;
            opacity: 0.45;
        }

        .sidebar-brand {
            padding: 0.15rem 0.1rem 0.25rem 0.1rem;
        }

        .sidebar-brand-title {
            font-size: 1.08rem;
            font-weight: 760;
            letter-spacing: -0.015em;
            line-height: 1.25;
            margin-bottom: 0.16rem;
        }

        .sidebar-brand-subtitle {
            font-size: 0.75rem;
            font-weight: 500;
            line-height: 1.35;
            opacity: 0.62;
            max-width: 250px;
        }

        .sidebar-section-label {
            font-size: 0.66rem;
            font-weight: 720;
            letter-spacing: 0.075em;
            text-transform: uppercase;
            opacity: 0.46;
            margin-top: 0.05rem;
            margin-bottom: 0.28rem;
        }

        [data-testid="stSidebar"] details {
            border: 0;
            background: transparent;
        }

        [data-testid="stSidebar"] details > summary {
            border-radius: 10px;
            padding-top: 0.45rem;
            padding-bottom: 0.45rem;
            font-size: 0.86rem;
            font-weight: 620;
        }

        [data-testid="stSidebar"] details > summary:hover {
            background: rgba(128, 128, 128, 0.08);
        }

        [data-testid="stSidebar"] details [data-testid="stPageLink"] {
            margin-left: 0.35rem;
        }

        .sidebar-user-label {
            font-size: 0.69rem;
            font-weight: 500;
            opacity: 0.55;
            margin-bottom: 0.10rem;
        }

        .sidebar-user-value {
            font-size: 0.83rem;
            font-weight: 620;
            line-height: 1.35;
            word-break: break-word;
            margin-bottom: 0.48rem;
        }

        .sidebar-role-badge {
            display: inline-block;
            padding: 0.16rem 0.46rem;
            margin: 0.05rem 0.10rem 0.05rem 0;
            border: 1px solid rgba(120, 120, 120, 0.26);
            border-radius: 999px;
            font-size: 0.68rem;
            font-weight: 650;
            line-height: 1.25;
            background: rgba(128, 128, 128, 0.045);
        }

        [data-testid="stSidebar"] button[kind="secondary"] {
            border-radius: 10px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ==========================================================
# SESSION / LOGOUT
# ==========================================================


def _clear_local_session_after_logout() -> None:
    try:
        clear_access_cache()
    except Exception:
        pass

    try:
        clear_hierarchy_cache()
    except Exception:
        pass

    for key in list(st.session_state.keys()):
        st.session_state.pop(key, None)


def _logout() -> None:
    logout_error: Exception | None = None

    try:
        sign_out()
    except Exception as exc:
        logout_error = exc

    _clear_local_session_after_logout()

    if logout_error is not None:
        st.session_state["logout_warning"] = (
            "Session lokal sudah ditutup. "
            "Logout ke server tidak dapat dikonfirmasi "
            "karena kendala koneksi."
        )

    st.switch_page("app.py")


# ==========================================================
# NAVIGATION HELPERS
# ==========================================================


def _section_label(text: str) -> None:
    st.markdown(
        (
            '<div class="sidebar-section-label">'
            f"{html.escape(text)}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


# ==========================================================
# NAVIGATION
# ==========================================================


def _render_navigation() -> None:
    # ======================================================
    # UTAMA
    # ======================================================

    if can_view():
        _section_label("Utama")

        st.page_link(
            "app.py",
            label="Dashboard",
            icon=":material/dashboard:",
        )

        st.page_link(
            "pages/omc_dashboard_gangguan.py",
            label="OMC Dashboard Gangguan",
            icon=":material/monitoring:",
        )

    # ======================================================
    # OPERASIONAL
    # ======================================================

    if can_input() or can_view():
        st.divider()
        _section_label("Operasional")

        if can_input():
            st.page_link(
                "pages/input_kejadian.py",
                label="Input Gangguan / Manuver",
                icon=":material/add_circle:",
            )

        if can_view():
            st.page_link(
                "pages/gangguan_aktif.py",
                label="Gangguan Aktif",
                icon=":material/bolt:",
            )

            st.page_link(
                "pages/riwayat_kejadian.py",
                label="Riwayat Operasi",
                icon=":material/history:",
            )

    # ======================================================
    # LAPORAN DROPDOWN
    # ======================================================

    show_monthly_report = _can_open_monthly_workflow()
    show_monthly_monitoring = _can_open_monthly_monitoring()

    if show_monthly_report or show_monthly_monitoring:
        st.divider()

        with st.expander(
            "Laporan",
            icon=":material/description:",
            expanded=False,
        ):
            if show_monthly_report:
                st.page_link(
                    "pages/laporan_bulanan.py",
                    label="Laporan Bulanan",
                    icon=":material/article:",
                )

            if show_monthly_monitoring:
                st.page_link(
                    "pages/monitoring_laporan_bulanan.py",
                    label="Monitoring Laporan Bulanan",
                    icon=":material/monitoring:",
                )

    # ======================================================
    # TOOLS DROPDOWN
    # ======================================================

    if _can_open_transformer_import():
        st.divider()

        with st.expander(
            "Tools",
            icon=":material/build:",
            expanded=False,
        ):
            st.page_link(
                "pages/master_transformer.py",
                label="Import Data Trafo PST",
                icon=":material/database_upload:",
            )

    # ======================================================
    # AKUN & ADMINISTRASI DROPDOWN
    # ======================================================

    st.divider()

    with st.expander(
        "Akun & Administrasi",
        icon=":material/account_circle:",
        expanded=False,
    ):
        st.page_link(
            "pages/profil_saya.py",
            label="Profil Saya",
            icon=":material/person:",
        )

        if can_manage_access():
            st.page_link(
                "pages/manajemen_user.py",
                label="Manajemen User",
                icon=":material/manage_accounts:",
            )


# ==========================================================
# ACCOUNT SUMMARY
# ==========================================================


def _render_account(user: object) -> None:
    email = getattr(user, "email", None)
    role_labels = get_role_labels()

    safe_email = html.escape(str(email or "-"))

    st.markdown(
        '<div class="sidebar-user-label">Akun Aktif</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        (
            '<div class="sidebar-user-value">'
            f"{safe_email}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    if role_labels:
        st.markdown(
            '<div class="sidebar-user-label">Role</div>',
            unsafe_allow_html=True,
        )

        role_html = "".join(
            (
                '<span class="sidebar-role-badge">'
                f"{html.escape(str(role))}"
                "</span>"
            )
            for role in role_labels
        )

        st.markdown(
            role_html,
            unsafe_allow_html=True,
        )


# ==========================================================
# SIDEBAR
# ==========================================================


def render_sidebar() -> None:
    user = get_current_user()

    if user is None:
        return

    with st.sidebar:
        _apply_sidebar_style()

        st.markdown(
            """
            <div class="sidebar-brand">
                <div class="sidebar-brand-title">
                    ⚡ Gangguan 20 kV UPT PSR
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.divider()

        _render_navigation()

        st.divider()

        _render_account(user)

        st.write("")

        if st.button(
            "Keluar",
            icon=":material/logout:",
            use_container_width=True,
            type="secondary",
            key="sidebar_logout_button",
        ):
            _logout()