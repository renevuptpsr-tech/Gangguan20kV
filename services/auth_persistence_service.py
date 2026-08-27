from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any

import extra_streamlit_components as stx
import streamlit as st
from cryptography.fernet import Fernet, InvalidToken


AUTH_COOKIE_NAME = "gangguan20kv_auth"
AUTH_COOKIE_DAYS = 7

_COOKIE_MANAGER_STATE_KEY = "_auth_cookie_manager"
_LAST_PERSISTED_REFRESH_KEY = "_auth_last_persisted_refresh_token"
_RESTORE_ATTEMPTED_KEY = "_auth_restore_attempted"


def _get_fernet_key() -> str:
    try:
        secret_value = str(
            st.secrets.get("AUTH_COOKIE_FERNET_KEY", "") or ""
        ).strip()
    except (FileNotFoundError, KeyError):
        secret_value = ""

    value = str(
        os.getenv("AUTH_COOKIE_FERNET_KEY") or secret_value
    ).strip()

    if not value:
        raise RuntimeError("AUTH_COOKIE_FERNET_KEY belum tersedia.")

    try:
        Fernet(value.encode("utf-8"))
    except Exception as exc:
        raise RuntimeError(
            "AUTH_COOKIE_FERNET_KEY tidak valid."
        ) from exc

    return value


def _cookie_secure() -> bool:
    try:
        secret_value: Any = st.secrets.get(
            "AUTH_COOKIE_SECURE", False
        )
    except (FileNotFoundError, KeyError):
        secret_value = False

    raw_value: Any = os.getenv(
        "AUTH_COOKIE_SECURE",
        secret_value,
    )

    if isinstance(raw_value, bool):
        return raw_value

    return str(raw_value).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _cipher() -> Fernet:
    return Fernet(
        _get_fernet_key().encode("utf-8")
    )


def _get_cookie_manager() -> stx.CookieManager:
    manager = st.session_state.get(
        _COOKIE_MANAGER_STATE_KEY
    )

    if isinstance(manager, stx.CookieManager):
        return manager

    manager = stx.CookieManager(
        key="gangguan20kv_auth_cookie_manager"
    )

    st.session_state[
        _COOKIE_MANAGER_STATE_KEY
    ] = manager

    return manager


def _encrypt_refresh_token(
    refresh_token: str,
) -> str:
    payload = json.dumps(
        {
            "version": 1,
            "refresh_token": refresh_token,
        },
        separators=(",", ":"),
    ).encode("utf-8")

    return _cipher().encrypt(
        payload
    ).decode("utf-8")


def _decrypt_refresh_token(
    encrypted_value: str,
) -> str | None:
    value = str(
        encrypted_value or ""
    ).strip()

    if not value:
        return None

    try:
        decrypted = _cipher().decrypt(
            value.encode("utf-8"),
            ttl=AUTH_COOKIE_DAYS * 24 * 60 * 60,
        )

        payload: Any = json.loads(
            decrypted.decode("utf-8")
        )

    except (
        InvalidToken,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(payload, dict):
        return None

    refresh_token = str(
        payload.get("refresh_token", "") or ""
    ).strip()

    return refresh_token or None


def get_persistent_refresh_token() -> str | None:
    try:
        encrypted_value = st.context.cookies.get(
            AUTH_COOKIE_NAME
        )
    except Exception:
        encrypted_value = None

    if encrypted_value is None:
        return None

    return _decrypt_refresh_token(
        str(encrypted_value)
    )


def persist_refresh_token(
    refresh_token: str,
) -> None:
    token = str(
        refresh_token or ""
    ).strip()

    if not token:
        return

    if (
        st.session_state.get(
            _LAST_PERSISTED_REFRESH_KEY
        )
        == token
    ):
        return

    manager = _get_cookie_manager()

    manager.set(
        cookie=AUTH_COOKIE_NAME,
        val=_encrypt_refresh_token(token),
        key="gangguan20kv_auth_cookie_set",
        path="/",
        expires_at=(
            datetime.now()
            + timedelta(days=AUTH_COOKIE_DAYS)
        ),
        secure=_cookie_secure(),
        same_site="strict",
    )

    st.session_state[
        _LAST_PERSISTED_REFRESH_KEY
    ] = token


def clear_persistent_auth() -> None:
    try:
        manager = _get_cookie_manager()

        manager.delete(
            cookie=AUTH_COOKIE_NAME,
            key="gangguan20kv_auth_cookie_delete",
        )
    except Exception:
        pass

    st.session_state.pop(
        _LAST_PERSISTED_REFRESH_KEY,
        None,
    )


def has_restore_been_attempted() -> bool:
    return bool(
        st.session_state.get(
            _RESTORE_ATTEMPTED_KEY,
            False,
        )
    )


def mark_restore_attempted() -> None:
    st.session_state[
        _RESTORE_ATTEMPTED_KEY
    ] = True


def reset_restore_attempt() -> None:
    st.session_state.pop(
        _RESTORE_ATTEMPTED_KEY,
        None,
    )
