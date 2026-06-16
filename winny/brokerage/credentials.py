"""Per-user credential store for exchange API keys.

Stores encrypted API keys per user+broker. In-memory with optional file
persistence. In production this would use a proper secrets vault (AWS
Secrets Manager, HashiCorp Vault, or Supabase Vault).

Security:
  - Keys encrypted at rest with Fernet (AES-128-CBC)
  - Master key from WINNY_CRED_KEY env var or auto-generated per process
  - Keys never returned in plaintext after storage (write-only)
  - Masked display: first 4 chars + '...' + last 4 chars
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

# PBKDF2 work factor for deriving a Fernet key from a non-Fernet passphrase.
# OWASP-recommended floor for PBKDF2-HMAC-SHA256 (2023+).
_KDF_ITERATIONS = 600_000


def _is_production() -> bool:
    """True when running in a production deployment.

    Production must never silently fall back to an ephemeral encryption key —
    that would make every stored broker credential undecryptable after a
    restart/redeploy (audit finding F5).
    """
    env = os.environ.get("WINNY_ENV", os.environ.get("ENV", "")).strip().lower()
    return env in ("production", "prod")


def _get_fernet() -> Fernet:
    """Resolve the Fernet instance used to encrypt credentials at rest.

    Key resolution (priority order):
      1. ``WINNY_CRED_KEY`` is a valid 32-byte urlsafe-base64 Fernet key →
         use it directly (the recommended production setup).
      2. ``WINNY_CRED_KEY`` is any other non-empty string → treat it as a
         passphrase and derive a *stable* Fernet key via PBKDF2-HMAC-SHA256.
         Deterministic, so credentials stay decryptable across restarts.
      3. ``WINNY_CRED_KEY`` unset:
           * production → raise (fail closed).
           * dev/test → generate an ephemeral key (persisted to the process env
             so every call in this process shares it) with a loud warning.
    """
    key = os.environ.get("WINNY_CRED_KEY", "").strip()

    if not key:
        if _is_production():
            raise RuntimeError(
                "WINNY_CRED_KEY is required in production. Refusing to encrypt "
                "broker credentials with an ephemeral key (they would become "
                "undecryptable after the next restart)."
            )
        # Dev/test only: ephemeral key. Persist to env so the credential_store
        # singleton and the settings.py persistence path share one key within
        # this process (otherwise round-tripping would silently fail).
        logger.warning(
            "WINNY_CRED_KEY unset — using an EPHEMERAL key (dev only). Stored "
            "credentials will NOT survive a restart. Set WINNY_CRED_KEY."
        )
        generated = Fernet.generate_key()
        os.environ["WINNY_CRED_KEY"] = generated.decode()
        return Fernet(generated)

    # 1. Already a valid Fernet key — use directly.
    try:
        return Fernet(key.encode())
    except Exception:
        pass

    # 2. Non-Fernet passphrase — derive a stable key with a real KDF instead of
    #    the previous null-pad/truncate (which had no salt and no stretching).
    salt = os.environ.get("WINNY_CRED_SALT", "winny-cred-kdf-v1").encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    derived = base64.urlsafe_b64encode(kdf.derive(key.encode()))
    return Fernet(derived)


@dataclass
class BrokerCredentials:
    """Stored credentials for one user+broker pair."""

    broker_id: str
    api_key_encrypted: bytes
    api_secret_encrypted: bytes
    api_password_encrypted: bytes = b""
    is_testnet: bool = False
    label: str = ""  # user-friendly label, e.g. "My Binance Main"
    permissions: list[str] = field(default_factory=list)  # e.g. ["read", "trade"]


@dataclass
class CredentialMask:
    """Safe-to-display representation of stored credentials."""

    broker_id: str
    api_key_masked: str
    has_secret: bool
    has_password: bool
    is_testnet: bool
    label: str
    permissions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "broker_id": self.broker_id,
            "api_key_masked": self.api_key_masked,
            "has_secret": self.has_secret,
            "has_password": self.has_password,
            "is_testnet": self.is_testnet,
            "label": self.label,
            "permissions": self.permissions,
        }


def _mask_key(plaintext: str) -> str:
    """Mask a key for safe display: first4...last4."""
    if len(plaintext) <= 8:
        return "****"
    return f"{plaintext[:4]}...{plaintext[-4:]}"


class CredentialStore:
    """Encrypted per-user credential store.

    Usage:
        store = CredentialStore()
        store.save("user-123", "binance", api_key="abc", api_secret="xyz")
        creds = store.get_decrypted("user-123", "binance")
    """

    def __init__(self, persist_path: Path | None = None) -> None:
        self._fernet = _get_fernet()
        # { user_id: { broker_id: BrokerCredentials } }
        self._store: dict[str, dict[str, BrokerCredentials]] = {}
        self._persist_path = persist_path
        if persist_path and persist_path.exists():
            self._load_from_disk()

    def save(
        self,
        user_id: str,
        broker_id: str,
        *,
        api_key: str,
        api_secret: str = "",
        api_password: str = "",
        is_testnet: bool = False,
        label: str = "",
        permissions: list[str] | None = None,
    ) -> CredentialMask:
        """Encrypt and store credentials. Returns masked view."""
        cred = BrokerCredentials(
            broker_id=broker_id,
            api_key_encrypted=self._fernet.encrypt(api_key.encode()),
            api_secret_encrypted=self._fernet.encrypt(api_secret.encode()) if api_secret else b"",
            api_password_encrypted=self._fernet.encrypt(api_password.encode()) if api_password else b"",
            is_testnet=is_testnet,
            label=label or f"{broker_id.title()} API Key",
            permissions=permissions or ["read", "trade"],
        )

        if user_id not in self._store:
            self._store[user_id] = {}
        self._store[user_id][broker_id] = cred

        # Also set env vars for the current process (so CcxtBrokerage picks them up)
        os.environ["WINNY_CCXT_API_KEY"] = api_key
        if api_secret:
            os.environ["WINNY_CCXT_SECRET"] = api_secret
        if api_password:
            os.environ["WINNY_CCXT_PASSWORD"] = api_password
        os.environ["WINNY_BROKER_CR"] = broker_id

        if self._persist_path:
            self._save_to_disk()

        return CredentialMask(
            broker_id=broker_id,
            api_key_masked=_mask_key(api_key),
            has_secret=bool(api_secret),
            has_password=bool(api_password),
            is_testnet=is_testnet,
            label=cred.label,
            permissions=cred.permissions,
        )

    def get_masked(self, user_id: str, broker_id: str) -> CredentialMask | None:
        """Get masked (safe-to-display) credentials."""
        cred = self._store.get(user_id, {}).get(broker_id)
        if cred is None:
            return None

        api_key_plain = self._fernet.decrypt(cred.api_key_encrypted).decode()
        return CredentialMask(
            broker_id=cred.broker_id,
            api_key_masked=_mask_key(api_key_plain),
            has_secret=bool(cred.api_secret_encrypted),
            has_password=bool(cred.api_password_encrypted),
            is_testnet=cred.is_testnet,
            label=cred.label,
            permissions=cred.permissions,
        )

    def get_all_masked(self, user_id: str) -> list[CredentialMask]:
        """Get all stored credentials for a user (masked)."""
        user_creds = self._store.get(user_id, {})
        result: list[CredentialMask] = []
        for broker_id in user_creds:
            mask = self.get_masked(user_id, broker_id)
            if mask:
                result.append(mask)
        return result

    def get_decrypted(self, user_id: str, broker_id: str) -> dict[str, str] | None:
        """Get decrypted credentials (for internal use only, never expose via API)."""
        cred = self._store.get(user_id, {}).get(broker_id)
        if cred is None:
            return None

        result: dict[str, str] = {
            "api_key": self._fernet.decrypt(cred.api_key_encrypted).decode(),
        }
        if cred.api_secret_encrypted:
            result["api_secret"] = self._fernet.decrypt(cred.api_secret_encrypted).decode()
        if cred.api_password_encrypted:
            result["api_password"] = self._fernet.decrypt(cred.api_password_encrypted).decode()
        return result

    def delete(self, user_id: str, broker_id: str) -> bool:
        """Delete stored credentials. Returns True if found and deleted."""
        user_creds = self._store.get(user_id, {})
        if broker_id in user_creds:
            del user_creds[broker_id]
            if self._persist_path:
                self._save_to_disk()
            return True
        return False

    def has_credentials(self, user_id: str, broker_id: str | None = None) -> bool:
        """Check if user has stored credentials (optionally for a specific broker)."""
        user_creds = self._store.get(user_id, {})
        if broker_id:
            return broker_id in user_creds
        return len(user_creds) > 0

    def _save_to_disk(self) -> None:
        """Persist encrypted store to disk (JSON with base64 bytes)."""
        if not self._persist_path:
            return
        data: dict[str, Any] = {}
        for user_id, brokers in self._store.items():
            data[user_id] = {}
            for broker_id, cred in brokers.items():
                data[user_id][broker_id] = {
                    "broker_id": cred.broker_id,
                    "api_key_encrypted": base64.b64encode(cred.api_key_encrypted).decode(),
                    "api_secret_encrypted": base64.b64encode(cred.api_secret_encrypted).decode(),
                    "api_password_encrypted": base64.b64encode(cred.api_password_encrypted).decode(),
                    "is_testnet": cred.is_testnet,
                    "label": cred.label,
                    "permissions": cred.permissions,
                }
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._persist_path.write_text(json.dumps(data, indent=2))

    def _load_from_disk(self) -> None:
        """Load encrypted store from disk."""
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            raw = json.loads(self._persist_path.read_text())
            for user_id, brokers in raw.items():
                self._store[user_id] = {}
                for broker_id, cred_data in brokers.items():
                    self._store[user_id][broker_id] = BrokerCredentials(
                        broker_id=cred_data["broker_id"],
                        api_key_encrypted=base64.b64decode(cred_data["api_key_encrypted"]),
                        api_secret_encrypted=base64.b64decode(cred_data["api_secret_encrypted"]),
                        api_password_encrypted=base64.b64decode(cred_data["api_password_encrypted"]),
                        is_testnet=cred_data.get("is_testnet", False),
                        label=cred_data.get("label", ""),
                        permissions=cred_data.get("permissions", []),
                    )
        except (json.JSONDecodeError, KeyError):
            pass  # Corrupted file — start fresh


# ── Module-level singleton ─────────────────────────────────────────────────────

_DATA_DIR = Path(os.environ.get("WINNY_DATA_DIR", "data"))
_CRED_FILE = _DATA_DIR / ".credentials.enc.json"

credential_store = CredentialStore(persist_path=_CRED_FILE)
