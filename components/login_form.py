import streamlit as st

from services.auth_service import sign_in


def render_login_form() -> None:
    st.title("Gangguan Penyulang 20 kV")
    st.caption("Silakan masuk untuk melanjutkan.")

    with st.form("login_form"):
        email = st.text_input(
            "Email",
            placeholder="nama@domain.com",
        )

        password = st.text_input(
            "Password",
            type="password",
        )

        submitted = st.form_submit_button(
            "Masuk",
            use_container_width=True,
        )

    if submitted:
        if not email or not password:
            st.warning("Email dan password wajib diisi.")
            return

        try:
            sign_in(email.strip(), password)

            st.success("Login berhasil.")
            st.rerun()

        except Exception as exc:
            st.error("Email atau password tidak valid.")
            st.exception(exc)