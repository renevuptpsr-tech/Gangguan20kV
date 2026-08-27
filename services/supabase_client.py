from __future__ import annotations

import os

import streamlit as st
from supabase import Client, create_client


SESSION_CLIENT_KEY = "_supabase_client"
SESSION_AUTH_KEY = "auth_session"
SESSION_USER_KEY = "auth_user"


class SupabaseSessionExpiredError(RuntimeError):
    """Session Supabase tidak dapat dipulihkan menggunakan refresh token."""


def _get_config() -> tuple[str, str]:
    """
    Membaca konfigurasi Supabase dengan fallback kompatibel:

    1. Environment variables:
       SUPABASE_URL
       SUPABASE_KEY / SUPABASE_ANON_KEY

    2. Top-level .streamlit/secrets.toml:
       SUPABASE_URL = "..."
       SUPABASE_KEY = "..."

    3. Nested .streamlit/secrets.toml:
       [supabase]
       url = "..."
       key = "..."
    """

    env_url = str(
        os.getenv("SUPABASE_URL")
        or ""
    ).strip()

    env_key = str(
        os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or ""
    ).strip()

    secret_url = ""
    secret_key = ""

    try:
        # ------------------------------
        # Top-level secrets
        # ------------------------------
        secret_url = str(
            st.secrets.get(
                "SUPABASE_URL",
                "",
            )
            or ""
        ).strip()

        secret_key = str(
            st.secrets.get(
                "SUPABASE_KEY",
                st.secrets.get(
                    "SUPABASE_ANON_KEY",
                    "",
                ),
            )
            or ""
        ).strip()

        # ------------------------------
        # Nested [supabase] fallback
        # ------------------------------
        if (
            not secret_url
            or not secret_key
        ):
            supabase_config: Any = (
                st.secrets.get(
                    "supabase",
                    {},
                )
            )

            if isinstance(
                supabase_config,
                dict,
            ) or hasattr(
                supabase_config,
                "get",
            ):
                if not secret_url:
                    secret_url = str(
                        supabase_config.get(
                            "url",
                            supabase_config.get(
                                "SUPABASE_URL",
                                "",
                            ),
                        )
                        or ""
                    ).strip()

                if not secret_key:
                    secret_key = str(
                        supabase_config.get(
                            "key",
                            supabase_config.get(
                                "anon_key",
                                supabase_config.get(
                                    "SUPABASE_KEY",
                                    supabase_config.get(
                                        "SUPABASE_ANON_KEY",
                                        "",
                                    ),
                                ),
                            ),
                        )
                        or ""
                    ).strip()

    except (
        FileNotFoundError,
        KeyError,
    ):
        secret_url = ""
        secret_key = ""

    url = (
        env_url
        or secret_url
    )

    key = (
        env_key
        or secret_key
    )

    if not url:
        raise RuntimeError(
            "SUPABASE_URL belum tersedia. "
            "Pastikan .streamlit/secrets.toml masih memuat "
            "konfigurasi Supabase dan tidak tertimpa saat "
            "menambahkan AUTH_COOKIE_FERNET_KEY."
        )

    if not key:
        raise RuntimeError(
            "SUPABASE_KEY / SUPABASE_ANON_KEY belum tersedia. "
            "Pastikan key Supabase masih ada di "
            ".streamlit/secrets.toml."
        )

    return (
        url,
        key,
    )


def _new_client() -> Client:
    url, key = _get_config()

    return create_client(
        url,
        key,
    )


def _get_or_create_client() -> Client:
    client = st.session_state.get(
        SESSION_CLIENT_KEY
    )

    if isinstance(client, Client):
        return client

    client = _new_client()

    st.session_state[
        SESSION_CLIENT_KEY
    ] = client

    return client


def _extract_token(
    session: object,
    name: str,
) -> str:
    value = getattr(
        session,
        name,
        None,
    )

    return str(
        value or ""
    ).strip()


def _store_auth_response(
    response: object,
) -> None:
    session = getattr(
        response,
        "session",
        None,
    )

    user = getattr(
        response,
        "user",
        None,
    )

    if session is not None:
        st.session_state[
            SESSION_AUTH_KEY
        ] = session

    if user is not None:
        st.session_state[
            SESSION_USER_KEY
        ] = user


def clear_supabase_auth_state() -> None:
    st.session_state.pop(
        SESSION_AUTH_KEY,
        None,
    )

    st.session_state.pop(
        SESSION_USER_KEY,
        None,
    )

    st.session_state.pop(
        SESSION_CLIENT_KEY,
        None,
    )


def refresh_supabase_session() -> bool:
    stored_session = st.session_state.get(
        SESSION_AUTH_KEY
    )

    if stored_session is None:
        return False

    access_token = _extract_token(
        stored_session,
        "access_token",
    )

    refresh_token = _extract_token(
        stored_session,
        "refresh_token",
    )

    if not refresh_token:
        clear_supabase_auth_state()
        return False

    client = _get_or_create_client()

    try:
        if access_token:
            response = client.auth.set_session(
                access_token,
                refresh_token,
            )

            _store_auth_response(
                response
            )

            if st.session_state.get(
                SESSION_AUTH_KEY
            ) is not None:
                return True

    except Exception:
        pass

    try:
        response = client.auth.refresh_session(
            refresh_token
        )

        _store_auth_response(
            response
        )

        if st.session_state.get(
            SESSION_AUTH_KEY
        ) is None:
            raise SupabaseSessionExpiredError(
                "Supabase tidak mengembalikan session baru."
            )

        return True

    except Exception as exc:
        clear_supabase_auth_state()

        raise SupabaseSessionExpiredError(
            "Session login telah berakhir dan "
            "refresh token tidak dapat digunakan. "
            "Silakan login kembali."
        ) from exc


def get_supabase_client() -> Client:
    client = _get_or_create_client()

    stored_session = st.session_state.get(
        SESSION_AUTH_KEY
    )

    if stored_session is None:
        return client

    access_token = _extract_token(
        stored_session,
        "access_token",
    )

    refresh_token = _extract_token(
        stored_session,
        "refresh_token",
    )

    if not refresh_token:
        clear_supabase_auth_state()
        return _get_or_create_client()

    try:
        response = client.auth.set_session(
            access_token,
            refresh_token,
        )

        _store_auth_response(
            response
        )

    except Exception:
        refresh_supabase_session()

        client = _get_or_create_client()

        refreshed_session = (
            st.session_state.get(
                SESSION_AUTH_KEY
            )
        )

        if refreshed_session is not None:
            refreshed_access = _extract_token(
                refreshed_session,
                "access_token",
            )

            refreshed_refresh = _extract_token(
                refreshed_session,
                "refresh_token",
            )

            if refreshed_access and refreshed_refresh:
                response = client.auth.set_session(
                    refreshed_access,
                    refreshed_refresh,
                )

                _store_auth_response(
                    response
                )

    return client