"""Symmetric encryption for credentials stored at rest (e.g. LLM provider API keys).

The DB (SQLite file) must never contain cleartext API keys: a stolen DB file or a
leaked backup would otherwise expose every configured provider's credential.
Values are encrypted with Fernet (AES-128-CBC + HMAC) using a server-side secret.
"""

import base64
import hashlib
import os
from functools import lru_cache
from pathlib import Path

import structlog
from cryptography.fernet import Fernet, InvalidToken

from core.config import settings

logger = structlog.get_logger()

# Dev-only fallback: generated on first run and stored next to the backend package
# so restarts can still decrypt existing rows. Gitignored. PRODUCTION MUST set
# SYNAPSE_SECRET_KEY so the secret lives in the environment / a secrets manager.
_DEV_KEY_FILE = Path(__file__).resolve().parent.parent / ".synapse_secret_key"


def _derive_fernet_key(secret: str) -> bytes:
    """Accept any secret string, not just a 32-byte urlsafe-base64 Fernet key."""
    raw = secret.encode("utf-8")
    try:
        if len(base64.urlsafe_b64decode(raw)) == 32:
            return raw
    except Exception:
        pass
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())


def _load_or_create_dev_secret() -> str:
    if _DEV_KEY_FILE.exists():
        existing = _DEV_KEY_FILE.read_text().strip()
        if existing:
            return existing
    secret = Fernet.generate_key().decode()
    _DEV_KEY_FILE.write_text(secret)
    try:
        os.chmod(_DEV_KEY_FILE, 0o600)
    except OSError:  # non-POSIX filesystems
        pass
    logger.warning(
        "synapse_secret_key_generated",
        path=str(_DEV_KEY_FILE),
        detail="DEV-ONLY: set SYNAPSE_SECRET_KEY in production",
    )
    return secret


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    secret = (settings.secret_key or "").strip() or _load_or_create_dev_secret()
    return Fernet(_derive_fernet_key(secret))


def encrypt(plaintext: str) -> str:
    """Encrypt a credential for storage. Empty input stays empty (no key configured)."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    """Decrypt a stored credential. Returns "" if it cannot be decrypted."""
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # Wrong/rotated secret, or a legacy plaintext row. Never fall back to
        # returning the raw value: that would send a bad credential upstream.
        logger.error("api_key_decrypt_failed", detail="secret key mismatch or corrupt value")
        return ""
