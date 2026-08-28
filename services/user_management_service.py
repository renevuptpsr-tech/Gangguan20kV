from __future__ import annotations

import json
from typing import Any, cast

import streamlit as st

from services.access_service import can_manage_access
from services.supabase_client import get_supabase_client


UserRow = dict[str, Any]
AssignmentRow = dict[str, Any]
RoleRow = dict[str, Any]
FunctlocRow = dict[str, Any]
CreateUserResult = dict[str, Any]


def _require_manage_access() -> None:
    if not can_manage_access():
        raise PermissionError(
            "User tidak memiliki akses Manajemen User."
        )


def _clean_optional_text(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    result = str(value).strip()
    return result if result else None


def _clean_required_text(
    value: str | None,
    field_name: str,
) -> str:
    result = str(value or "").strip()

    if not result:
        raise ValueError(
            f"{field_name} wajib diisi."
        )

    return result


def _clean_string_list(
    values: list[str] | tuple[str, ...] | None,
) -> list[str]:
    if not values:
        return []

    result: list[str] = []

    for value in values:
        item = str(value or "").strip()

        if item and item not in result:
            result.append(item)

    return result


def _normalize_function_response(
    response: Any,
) -> dict[str, Any]:
    data = getattr(
        response,
        "data",
        response,
    )

    if data is None:
        return {}

    if isinstance(data, dict):
        return cast(
            dict[str, Any],
            data,
        )

    if isinstance(data, bytes):
        try:
            decoded = data.decode("utf-8")
        except Exception:
            return {"raw": str(data)}

        try:
            parsed = json.loads(decoded)

            if isinstance(parsed, dict):
                return cast(
                    dict[str, Any],
                    parsed,
                )

            return {"data": parsed}

        except Exception:
            return {"raw": decoded}

    if isinstance(data, str):
        try:
            parsed = json.loads(data)

            if isinstance(parsed, dict):
                return cast(
                    dict[str, Any],
                    parsed,
                )

            return {"data": parsed}

        except Exception:
            return {"raw": data}

    return {"data": data}


def _extract_exception_message(
    exc: Exception,
) -> str:
    try:
        to_dict = getattr(
            exc,
            "to_dict",
            None,
        )

        if callable(to_dict):
            info = to_dict()

            if isinstance(info, dict):
                for key in (
                    "message",
                    "error",
                    "msg",
                ):
                    value = info.get(key)

                    if value:
                        return str(value)

    except Exception:
        pass

    return str(exc)


def clear_user_management_cache() -> None:
    _load_users.clear()
    _load_user_assignments.clear()
    _load_assignable_roles.clear()
    _load_manageable_functlocs.clear()


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def _load_users() -> list[UserRow]:
    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_manage_users_list"
        )
        .execute()
    )

    if not response.data:
        return []

    return cast(
        list[UserRow],
        response.data,
    )


def get_users() -> list[UserRow]:
    _require_manage_access()
    return _load_users()


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def _load_user_assignments(
    user_id: str,
) -> list[AssignmentRow]:
    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_manage_user_assignments",
            {
                "p_user_id":
                    user_id,
            },
        )
        .execute()
    )

    if not response.data:
        return []

    return cast(
        list[AssignmentRow],
        response.data,
    )


def get_user_assignments(
    user_id: str,
) -> list[AssignmentRow]:
    _require_manage_access()

    user_id_clean = _clean_required_text(
        user_id,
        "User ID",
    )

    return _load_user_assignments(
        user_id_clean
    )


@st.cache_data(
    ttl=300,
    show_spinner=False,
)
def _load_assignable_roles() -> list[RoleRow]:
    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_manage_assignable_roles"
        )
        .execute()
    )

    if not response.data:
        return []

    return cast(
        list[RoleRow],
        response.data,
    )


def get_assignable_roles() -> list[RoleRow]:
    _require_manage_access()
    return _load_assignable_roles()


@st.cache_data(
    ttl=300,
    show_spinner=False,
)
def _load_manageable_functlocs() -> list[FunctlocRow]:
    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_manage_functlocs"
        )
        .execute()
    )

    if not response.data:
        return []

    return cast(
        list[FunctlocRow],
        response.data,
    )


def get_manageable_functlocs() -> list[FunctlocRow]:
    _require_manage_access()
    return _load_manageable_functlocs()


def create_user(
    *,
    email: str,
    password: str,
    full_name: str,
    employee_id: str | None,
    position_name: str | None,
    role_codes: list[str],
    functloc_ids: list[str],
    include_children: bool = True,
    is_active: bool = True,
) -> CreateUserResult:
    """
    Membuat user langsung pada Supabase Auth tanpa email invitation,
    dengan password yang ditentukan administrator.

    Mendukung multiple Role dan multiple Unit Access.

    Untuk role non-SUPER_ADMIN, backend akan membuat kombinasi:
    setiap role x setiap unit access.

    SUPER_ADMIN harus berdiri sendiri dan menggunakan scope Global.
    """

    _require_manage_access()

    email_clean = _clean_required_text(
        email,
        "Email",
    ).lower()

    password_clean = str(
        password
        or ""
    )

    full_name_clean = _clean_required_text(
        full_name,
        "Nama Lengkap",
    )

    employee_id_clean = _clean_optional_text(
        employee_id
    )

    position_name_clean = _clean_optional_text(
        position_name
    )

    role_codes_clean = [
        item.upper()
        for item
        in _clean_string_list(
            role_codes
        )
    ]

    functloc_ids_clean = _clean_string_list(
        functloc_ids
    )

    if "@" not in email_clean:
        raise ValueError(
            "Format email tidak valid."
        )

    if len(password_clean) < 8:
        raise ValueError(
            "Password minimal 8 karakter."
        )

    if not role_codes_clean:
        raise ValueError(
            "Minimal satu Role wajib dipilih."
        )

    has_super_admin = (
        "SUPER_ADMIN"
        in role_codes_clean
    )

    if (
        has_super_admin
        and len(role_codes_clean) > 1
    ):
        raise ValueError(
            "SUPER_ADMIN harus dipilih sendiri "
            "tanpa role lain."
        )

    if (
        not has_super_admin
        and not functloc_ids_clean
    ):
        raise ValueError(
            "Minimal satu Unit Access wajib dipilih."
        )

    payload: dict[str, Any] = {
        "email":
            email_clean,

        "password":
            password_clean,

        "full_name":
            full_name_clean,

        "employee_id":
            employee_id_clean,

        "position_name":
            position_name_clean,

        "role_codes":
            role_codes_clean,

        "functloc_ids":
            (
                []
                if has_super_admin
                else functloc_ids_clean
            ),

        "include_children":
            (
                True
                if has_super_admin
                else bool(include_children)
            ),

        "is_active":
            bool(is_active),
    }

    supabase = get_supabase_client()

    try:
        response = (
            supabase
            .functions
            .invoke(
                "manage-create-user",
                invoke_options={
                    "body":
                        payload,
                },
            )
        )

    except Exception as exc:
        message = (
            _extract_exception_message(
                exc
            )
        )

        raise RuntimeError(
            "User tidak berhasil dibuat. "
            f"{message}"
        ) from exc

    result = (
        _normalize_function_response(
            response
        )
    )

    error_message = result.get(
        "error"
    )

    if error_message:
        raise RuntimeError(
            str(error_message)
        )

    if not bool(
        result.get("success")
    ):
        raise RuntimeError(
            "User tidak berhasil dibuat."
        )

    clear_user_management_cache()

    return result



def bulk_create_users(
    *,
    rows: list[dict[str, Any]],
    password: str,
    include_children: bool = True,
    is_active: bool = True,
) -> list[dict[str, Any]]:
    """
    Membuat beberapa user sekaligus menggunakan create_user()
    yang sudah ada.

    Satu kegagalan tidak menghentikan user lainnya.
    """

    _require_manage_access()

    password_clean = str(
        password
        or ""
    )

    if len(password_clean) < 8:
        raise ValueError(
            "Password awal minimal 8 karakter."
        )

    results: list[dict[str, Any]] = []

    for row in rows:
        row_number = int(
            row.get("row_number")
            or 0
        )

        email = str(
            row.get("email")
            or ""
        ).strip().lower()

        try:
            result = create_user(
                email=email,
                password=password_clean,
                full_name=str(
                    row.get("full_name")
                    or ""
                ).strip(),
                employee_id=(
                    str(
                        row.get("employee_id")
                        or ""
                    ).strip()
                    or None
                ),
                position_name=(
                    str(
                        row.get("position_name")
                        or ""
                    ).strip()
                    or None
                ),
                role_codes=[
                    str(item)
                    for item in (
                        row.get("role_codes")
                        or []
                    )
                ],
                functloc_ids=[
                    str(item)
                    for item in (
                        row.get("functloc_ids")
                        or []
                    )
                ],
                include_children=bool(
                    include_children
                ),
                is_active=bool(
                    is_active
                ),
            )

            results.append(
                {
                    "row_number":
                        row_number,

                    "email":
                        email,

                    "status":
                        "Berhasil",

                    "message":
                        "User berhasil dibuat.",

                    "user_id":
                        str(
                            result.get("user_id")
                            or ""
                        ).strip(),

                    "assignment_count":
                        int(
                            result.get(
                                "assignment_count"
                            )
                            or 0
                        ),
                }
            )

        except Exception as exc:
            results.append(
                {
                    "row_number":
                        row_number,

                    "email":
                        email,

                    "status":
                        "Gagal",

                    "message":
                        str(exc),

                    "user_id":
                        "",

                    "assignment_count":
                        0,
                }
            )

    clear_user_management_cache()

    return results


def reset_user_password(
    *,
    user_id: str,
    password: str,
) -> bool:
    """
    Mengganti password Supabase Auth user melalui Edge Function
    manage-reset-user-password.

    Password tidak disimpan di database aplikasi.
    """

    _require_manage_access()

    user_id_clean = _clean_required_text(
        user_id,
        "User ID",
    )

    password_clean = str(
        password
        or ""
    )

    if len(password_clean) < 8:
        raise ValueError(
            "Password minimal 8 karakter."
        )

    supabase = get_supabase_client()

    try:
        response = (
            supabase
            .functions
            .invoke(
                "manage-reset-user-password",
                invoke_options={
                    "body": {
                        "user_id":
                            user_id_clean,

                        "password":
                            password_clean,
                    },
                },
            )
        )

    except Exception as exc:
        message = (
            _extract_exception_message(
                exc
            )
        )

        raise RuntimeError(
            "Password user tidak berhasil diperbarui. "
            f"{message}"
        ) from exc

    result = (
        _normalize_function_response(
            response
        )
    )

    error_message = result.get(
        "error"
    )

    if error_message:
        raise RuntimeError(
            str(
                error_message
            )
        )

    if not bool(
        result.get(
            "success"
        )
    ):
        raise RuntimeError(
            "Password user tidak berhasil diperbarui."
        )

    return True

def update_user_profile(
    *,
    user_id: str,
    full_name: str,
    employee_id: str | None,
    position_name: str | None,
    default_functloc_id: str | None,
) -> bool:
    _require_manage_access()

    user_id_clean = _clean_required_text(
        user_id,
        "User ID",
    )

    full_name_clean = _clean_required_text(
        full_name,
        "Nama Lengkap",
    )

    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_manage_update_user_profile",
            {
                "p_user_id":
                    user_id_clean,

                "p_employee_id":
                    _clean_optional_text(
                        employee_id
                    ),

                "p_full_name":
                    full_name_clean,

                "p_position_name":
                    _clean_optional_text(
                        position_name
                    ),

                "p_default_functloc_id":
                    _clean_optional_text(
                        default_functloc_id
                    ),
            },
        )
        .execute()
    )

    if response.data is not True:
        raise RuntimeError(
            "Profile user tidak berhasil diperbarui."
        )

    clear_user_management_cache()

    return True


def add_user_assignment(
    *,
    user_id: str,
    role_code: str,
    functloc_id: str | None,
    include_children: bool = True,
    is_primary: bool = False,
) -> str:
    _require_manage_access()

    user_id_clean = _clean_required_text(
        user_id,
        "User ID",
    )

    role_code_clean = _clean_required_text(
        role_code,
        "Role",
    ).upper()

    functloc_id_clean = _clean_optional_text(
        functloc_id
    )

    if (
        role_code_clean
        != "SUPER_ADMIN"
        and functloc_id_clean is None
    ):
        raise ValueError(
            "Scope Unit wajib dipilih."
        )

    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_manage_add_assignment",
            {
                "p_user_id":
                    user_id_clean,

                "p_role_code":
                    role_code_clean,

                "p_functloc_id":
                    (
                        None
                        if role_code_clean
                        == "SUPER_ADMIN"
                        else functloc_id_clean
                    ),

                "p_include_children":
                    (
                        True
                        if role_code_clean
                        == "SUPER_ADMIN"
                        else bool(
                            include_children
                        )
                    ),

                "p_is_primary":
                    bool(is_primary),
            },
        )
        .execute()
    )

    if response.data is None:
        raise RuntimeError(
            "Role / scope tidak berhasil ditambahkan."
        )

    clear_user_management_cache()

    return str(
        response.data
    )


def add_multiple_user_assignments(
    *,
    user_id: str,
    role_codes: list[str],
    functloc_ids: list[str],
    include_children: bool = True,
) -> int:
    """
    Menambahkan multiple Role x multiple Unit Access
    untuk user yang sudah ada.
    """

    _require_manage_access()

    roles = [
        item.upper()
        for item
        in _clean_string_list(
            role_codes
        )
    ]

    scopes = _clean_string_list(
        functloc_ids
    )

    if not roles:
        return 0

    has_super_admin = (
        "SUPER_ADMIN"
        in roles
    )

    if (
        has_super_admin
        and len(roles) > 1
    ):
        raise ValueError(
            "SUPER_ADMIN harus dipilih sendiri "
            "tanpa role lain."
        )

    if (
        not has_super_admin
        and not scopes
    ):
        raise ValueError(
            "Minimal satu Unit Access wajib dipilih."
        )

    total = 0

    if has_super_admin:
        add_user_assignment(
            user_id=user_id,
            role_code="SUPER_ADMIN",
            functloc_id=None,
            include_children=True,
            is_primary=False,
        )

        total = 1

    else:
        for role_code in roles:
            for functloc_id in scopes:
                add_user_assignment(
                    user_id=user_id,
                    role_code=role_code,
                    functloc_id=functloc_id,
                    include_children=include_children,
                    is_primary=False,
                )

                total += 1

    clear_user_management_cache()

    return total




def sync_user_access(
    *,
    user_id: str,
    role_codes: list[str],
    functloc_ids: list[str],
    include_children: bool = True,
) -> dict[str, Any]:
    """
    Menyamakan kondisi akhir Role + Unit Access user dengan pilihan form.

    Backend akan:
    - membuat / mengaktifkan kombinasi Role x Unit yang dipilih;
    - menonaktifkan assignment manageable yang sudah tidak dipilih;
    - mempertahankan audit trail karena assignment tidak dihapus.
    """

    _require_manage_access()

    user_id_clean = _clean_required_text(
        user_id,
        "User ID",
    )

    roles = [
        item.upper()
        for item
        in _clean_string_list(
            role_codes
        )
    ]

    scopes = _clean_string_list(
        functloc_ids
    )

    if not roles:
        raise ValueError(
            "Minimal satu Role wajib dipilih."
        )

    has_super_admin = (
        "SUPER_ADMIN"
        in roles
    )

    if (
        has_super_admin
        and len(roles) > 1
    ):
        raise ValueError(
            "SUPER_ADMIN harus dipilih sendiri tanpa role lain."
        )

    if (
        not has_super_admin
        and not scopes
    ):
        raise ValueError(
            "Minimal satu Unit Access wajib dipilih."
        )

    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_manage_sync_user_access",
            {
                "p_user_id":
                    user_id_clean,

                "p_role_codes":
                    roles,

                "p_functloc_ids":
                    (
                        []
                        if has_super_admin
                        else scopes
                    ),

                "p_include_children":
                    (
                        True
                        if has_super_admin
                        else bool(
                            include_children
                        )
                    ),
            },
        )
        .execute()
    )

    data = response.data

    if not isinstance(
        data,
        dict,
    ):
        raise RuntimeError(
            "Response sinkronisasi access tidak valid."
        )

    result = cast(
        dict[str, Any],
        data,
    )

    if not bool(
        result.get(
            "success"
        )
    ):
        raise RuntimeError(
            "Sinkronisasi access tidak berhasil."
        )

    clear_user_management_cache()

    return result

def set_multiple_assignments_active(
    *,
    assignment_ids: list[str],
    is_active: bool,
) -> int:
    """
    Mengaktifkan / menonaktifkan beberapa assignment sekaligus
    melalui RPC backend.
    """

    _require_manage_access()

    clean_ids = [
        str(item).strip()
        for item
        in assignment_ids
        if str(item).strip()
    ]

    if not clean_ids:
        return 0

    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_manage_set_assignments_active",
            {
                "p_assignment_ids":
                    clean_ids,

                "p_is_active":
                    bool(
                        is_active
                    ),
            },
        )
        .execute()
    )

    raw_count = response.data

    if isinstance(
        raw_count,
        bool,
    ):
        count = int(
            raw_count
        )

    elif isinstance(
        raw_count,
        (int, float),
    ):
        count = int(
            raw_count
        )

    elif isinstance(
        raw_count,
        str,
    ):
        try:
            count = int(
                raw_count
            )
        except ValueError:
            count = 0

    else:
        count = 0

    clear_user_management_cache()

    return count

def set_assignment_active(
    *,
    assignment_id: str,
    is_active: bool,
) -> bool:
    _require_manage_access()

    assignment_id_clean = (
        _clean_required_text(
            assignment_id,
            "Assignment ID",
        )
    )

    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_manage_set_assignment_active",
            {
                "p_assignment_id":
                    assignment_id_clean,

                "p_is_active":
                    bool(is_active),
            },
        )
        .execute()
    )

    if response.data is not True:
        raise RuntimeError(
            "Status role / scope tidak berhasil diperbarui."
        )

    clear_user_management_cache()

    return True


def set_user_active(
    *,
    user_id: str,
    is_active: bool,
) -> bool:
    _require_manage_access()

    user_id_clean = _clean_required_text(
        user_id,
        "User ID",
    )

    supabase = get_supabase_client()

    response = (
        supabase
        .rpc(
            "fn_manage_set_user_active",
            {
                "p_user_id":
                    user_id_clean,

                "p_is_active":
                    bool(is_active),
            },
        )
        .execute()
    )

    if response.data is not True:
        raise RuntimeError(
            "Status user tidak berhasil diperbarui."
        )

    clear_user_management_cache()

    return True


def get_role_map() -> dict[str, RoleRow]:
    return {
        str(
            row.get("role_code")
            or ""
        ).strip().upper():
            row
        for row
        in get_assignable_roles()
        if str(
            row.get("role_code")
            or ""
        ).strip()
    }


def get_functloc_map() -> dict[str, FunctlocRow]:
    return {
        str(
            row.get("functloc_id")
            or ""
        ).strip():
            row
        for row
        in get_manageable_functlocs()
        if str(
            row.get("functloc_id")
            or ""
        ).strip()
    }