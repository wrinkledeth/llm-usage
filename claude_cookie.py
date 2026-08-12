from __future__ import annotations

import ctypes
import hashlib
import json
import pathlib
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import rookiepy

SESSION_COOKIE_NAMES = (
    "sessionKeyV3",
    "sessionKey",
    "__Secure-next-auth.session-token",
)
_CHROMIUM_EPOCH_OFFSET_SECONDS = 11_644_473_600
_COMMON_CRYPTO_PATH = "/usr/lib/system/libcommonCrypto.dylib"


class ClaudeCookieError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _MacCookieSource:
    relative_root: tuple[str, ...]
    keychain_service: str
    keychain_account: str
    uses_profiles: bool = True


@dataclass(frozen=True, slots=True)
class _CookieRecord:
    host: str
    name: str
    value: str
    encrypted_value: bytes
    expires_utc: int


_MAC_COOKIE_SOURCES = {
    "chrome": _MacCookieSource(
        relative_root=("Library", "Application Support", "Google", "Chrome"),
        keychain_service="Chrome Safe Storage",
        keychain_account="Chrome",
    ),
    "brave": _MacCookieSource(
        relative_root=(
            "Library",
            "Application Support",
            "BraveSoftware",
            "Brave-Browser",
        ),
        keychain_service="Brave Safe Storage",
        keychain_account="Brave",
    ),
    "edge": _MacCookieSource(
        relative_root=("Library", "Application Support", "Microsoft Edge"),
        keychain_service="Microsoft Edge Safe Storage",
        keychain_account="Microsoft Edge",
    ),
}


def get_claude_session_cookie(
    browser: str,
    home: pathlib.Path | None = None,
) -> tuple[str | None, str | None]:
    profile_error: Exception | None = None
    if sys.platform == "darwin" and browser in _MAC_COOKIE_SOURCES:
        try:
            result = _find_macos_session_cookie(
                _MAC_COOKIE_SOURCES[browser],
                home or pathlib.Path.home(),
            )
            if result is not None:
                return result
        except Exception as exc:
            profile_error = exc

    try:
        loader = getattr(rookiepy, browser)
        for cookie in loader(["claude.ai"]):
            name = cookie.get("name")
            value = cookie.get("value")
            if name in SESSION_COOKIE_NAMES and isinstance(value, str) and value:
                return name, value
    except Exception as exc:
        if profile_error is not None:
            raise ClaudeCookieError(
                f"profile read failed: {profile_error}; rookiepy fallback failed: {exc}"
            ) from exc
        raise

    if profile_error is not None:
        raise ClaudeCookieError(str(profile_error)) from profile_error
    return None, None


def _find_macos_session_cookie(
    source: _MacCookieSource,
    home: pathlib.Path,
) -> tuple[str, str] | None:
    root = home.joinpath(*source.relative_root)
    profile_dirs = _ordered_profile_dirs(root) if source.uses_profiles else [root]
    errors: list[str] = []

    for profile_dir in profile_dirs:
        for cookie_path in (profile_dir / "Cookies", profile_dir / "Network" / "Cookies"):
            if not cookie_path.is_file():
                continue
            try:
                records = _read_session_cookie_records(cookie_path)
            except sqlite3.Error as exc:
                errors.append(f"{cookie_path}: {exc}")
                continue

            for record in records:
                if _cookie_is_expired(record.expires_utc):
                    errors.append(f"{cookie_path}: Claude session cookie expired.")
                    continue
                if record.value:
                    return record.name, record.value
                if not record.encrypted_value:
                    continue
                try:
                    key = _macos_cookie_key(
                        source.keychain_service,
                        source.keychain_account,
                    )
                    value = _decrypt_chromium_cookie(
                        record.host,
                        record.encrypted_value,
                        key,
                    )
                except Exception as exc:
                    errors.append(f"{cookie_path}: {exc}")
                    continue
                if value:
                    return record.name, value

    if errors:
        raise ClaudeCookieError(errors[0])
    return None


def _ordered_profile_dirs(root: pathlib.Path) -> list[pathlib.Path]:
    profile_names: list[str] = []
    local_state = root / "Local State"
    try:
        payload = json.loads(local_state.read_text())
    except (OSError, json.JSONDecodeError):
        payload = {}

    profile = payload.get("profile")
    if isinstance(profile, dict):
        last_used = profile.get("last_used")
        if _valid_profile_name(last_used):
            profile_names.append(last_used)

        info_cache = profile.get("info_cache")
        if isinstance(info_cache, dict):
            ordered_cache = sorted(
                info_cache.items(),
                key=lambda item: _profile_active_time(item[1]),
                reverse=True,
            )
            profile_names.extend(
                name for name, _metadata in ordered_cache if _valid_profile_name(name)
            )

    profile_names.append("Default")
    try:
        profile_names.extend(
            path.name
            for path in root.iterdir()
            if path.is_dir() and _valid_profile_name(path.name)
        )
    except OSError:
        pass

    unique_names = list(dict.fromkeys(profile_names))
    return [root / name for name in unique_names]


def _profile_active_time(metadata: Any) -> float:
    if not isinstance(metadata, dict):
        return 0.0
    value = metadata.get("active_time")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _valid_profile_name(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value == "Default":
        return True
    return value.startswith("Profile ") and pathlib.Path(value).name == value


def _read_session_cookie_records(cookie_path: pathlib.Path) -> list[_CookieRecord]:
    placeholders = ",".join("?" for _name in SESSION_COOKIE_NAMES)
    query = f"""
        SELECT host_key, name, value, encrypted_value, expires_utc
        FROM cookies
        WHERE host_key IN ('claude.ai', '.claude.ai')
          AND name IN ({placeholders})
        ORDER BY last_access_utc DESC
    """
    uri = f"file:{cookie_path}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=1.0) as connection:
        rows = connection.execute(query, SESSION_COOKIE_NAMES).fetchall()
    return [
        _CookieRecord(
            host=str(row[0]),
            name=str(row[1]),
            value=str(row[2] or ""),
            encrypted_value=bytes(row[3] or b""),
            expires_utc=int(row[4] or 0),
        )
        for row in rows
    ]


def _cookie_is_expired(expires_utc: int) -> bool:
    if expires_utc <= 0:
        return False
    now_utc = int((time.time() + _CHROMIUM_EPOCH_OFFSET_SECONDS) * 1_000_000)
    return expires_utc <= now_utc


@lru_cache(maxsize=None)
def _macos_cookie_key(service: str, account: str) -> bytes:
    try:
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-w",
                "-s",
                service,
                "-a",
                account,
            ],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ClaudeCookieError(f"Could not read {service} from Keychain.") from exc

    password = result.stdout.rstrip(b"\r\n")
    if not password:
        raise ClaudeCookieError(f"{service} was empty in Keychain.")
    return hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, 16)


def _decrypt_chromium_cookie(host: str, encrypted_value: bytes, key: bytes) -> str:
    if not encrypted_value.startswith((b"v10", b"v11")):
        raise ClaudeCookieError("Unsupported Chromium cookie encryption version.")

    plaintext = _common_crypto_decrypt(encrypted_value[3:], key)
    host_digest = hashlib.sha256(host.encode()).digest()
    if plaintext.startswith(host_digest):
        plaintext = plaintext[len(host_digest) :]
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ClaudeCookieError("Decrypted Chromium cookie was not UTF-8.") from exc


def _common_crypto_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    try:
        common_crypto = ctypes.CDLL(_COMMON_CRYPTO_PATH)
    except OSError as exc:
        raise ClaudeCookieError("CommonCrypto is unavailable.") from exc

    common_crypto.CCCrypt.argtypes = [
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    common_crypto.CCCrypt.restype = ctypes.c_int32

    output = ctypes.create_string_buffer(len(ciphertext) + 16)
    output_length = ctypes.c_size_t()
    status = common_crypto.CCCrypt(
        1,  # kCCDecrypt
        0,  # kCCAlgorithmAES
        1,  # kCCOptionPKCS7Padding
        key,
        len(key),
        b" " * 16,
        ciphertext,
        len(ciphertext),
        output,
        len(output),
        ctypes.byref(output_length),
    )
    if status != 0:
        raise ClaudeCookieError(f"CommonCrypto failed with status {status}.")
    return output.raw[: output_length.value]
