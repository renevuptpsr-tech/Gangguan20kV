import streamlit as st

from components.login_form import render_login_form
from components.sidebar import hide_sidebar
from pages.dashboard import render as render_dashboard_page
from services.auth_service import is_authenticated


st.set_page_config(
    page_title="Gangguan Penyulang 20 kV",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    # ======================================================
    # AUTHENTICATION GATE
    # ======================================================
    #
    # app.py menjadi entry point resmi aplikasi.
    # Setelah login, halaman utama menggunakan renderer yang
    # sama dengan pages/dashboard.py.
    # ======================================================

    if not is_authenticated():
        hide_sidebar()
        render_login_form()
        st.stop()

    # ======================================================
    # DASHBOARD
    # ======================================================
    #
    # Jangan duplikasi isi Dashboard di app.py.
    # Seluruh UI Dashboard berada di pages/dashboard.py.
    # ======================================================

    render_dashboard_page()


if __name__ == "__main__":
    main()