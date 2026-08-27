from typing import Any

import streamlit as st

from services.auth_persistence_service import (
    clear_persistent_auth,
    get_persistent_refresh_token,
    has_restore_been_attempted,
    mark_restore_attempted,
    persist_refresh_token,
    reset_restore_attempt,
)
from services.supabase_client import (
    SESSION_AUTH_KEY,
    SESSION_USER_KEY,
    SupabaseSessionExpiredError,
    clear_supabase_auth_state,
    get_supabase_client,
    refresh_supabase_session,
)


def _extract_refresh_token(
    session: object | None,
) -> str:
    if session is None:
        return ""

    value = getattr(
        session,
        "refresh_token",
        None,
    )

    return str(
        value or ""
    ).strip()


def _persist_current_session() -> None:
    session = st.session_state.get(
        SESSION_AUTH_KEY
    )

    refresh_token = _extract_refresh_token(
        session
    )

    if refresh_token:
        persist_refresh_token(
            refresh_token
        )


def sign_in(
    email: str,
    password: str,
) -> bool:
    email_clean = str(
        email or ""
    ).strip()

    password_value = str(
        password or ""
    )

    if not email_clean or not password_value:
        raise ValueError(
            "Email dan password wajib diisi."
        )

    client = get_supabase_client()

    response = client.auth.sign_in_with_password(
        {
            "email": email_clean,
            "password": password_value,
        }
    )

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

    if session is None or user is None:
        clear_supabase_auth_state()
        clear_persistent_auth()
        return False

    st.session_state[
        SESSION_AUTH_KEY
    ] = session

    st.session_state[
        SESSION_USER_KEY
    ] = user

    client.auth.set_session(
        session.access_token,
        session.refresh_token,
    )

    _persist_current_session()
    reset_restore_attempt()

    return True


def sign_in_with_password(
    email: str,
    password: str,
) -> bool:
    return sign_in(
        email,
        password,
    )


def get_current_user() -> object | None:
    return st.session_state.get(
        SESSION_USER_KEY
    )


def get_current_session() -> object | None:
    return st.session_state.get(
        SESSION_AUTH_KEY
    )


def restore_persistent_session() -> bool:
    if (
        st.session_state.get(
            SESSION_USER_KEY
        )
        is not None
        and st.session_state.get(
            SESSION_AUTH_KEY
        )
        is not None
    ):
        return True

    if has_restore_been_attempted():
        return False

    mark_restore_attempted()

    refresh_token = (
        get_persistent_refresh_token()
    )

    if not refresh_token:
        return False

    client = get_supabase_client()

    try:
        response = client.auth.refresh_session(
            refresh_token
        )

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

        if session is None or user is None:
            raise SupabaseSessionExpiredError(
                "Supabase tidak mengembalikan session/user."
            )

        st.session_state[
            SESSION_AUTH_KEY
        ] = session

        st.session_state[
            SESSION_USER_KEY
        ] = user

        client.auth.set_session(
            session.access_token,
            session.refresh_token,
        )

        _persist_current_session()

        return True

    except Exception:
        clear_supabase_auth_state()
        clear_persistent_auth()
        return False


def refresh_session() -> bool:
    try:
        refreshed = (
            refresh_supabase_session()
        )

        if refreshed:
            _persist_current_session()

        return refreshed

    except SupabaseSessionExpiredError:
        clear_persistent_auth()
        return False


def is_authenticated() -> bool:
    user = st.session_state.get(
        SESSION_USER_KEY
    )

    session = st.session_state.get(
        SESSION_AUTH_KEY
    )

    if user is None or session is None:
        if not restore_persistent_session():
            return False

    try:
        if not refresh_supabase_session():
            clear_persistent_auth()
            return False

    except SupabaseSessionExpiredError:
        clear_persistent_auth()
        return False

    _persist_current_session()

    return (
        st.session_state.get(
            SESSION_USER_KEY
        )
        is not None
        and st.session_state.get(
            SESSION_AUTH_KEY
        )
        is not None
    )


def sign_out() -> None:
    client = None

    try:
        client = get_supabase_client()
    except Exception:
        client = None

    try:
        if client is not None:
            client.auth.sign_out()
    finally:
        clear_supabase_auth_state()
        clear_persistent_auth()
        reset_restore_attempt()
