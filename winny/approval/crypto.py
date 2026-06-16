"""Ed25519 approval grant primitives — SPECS.md §3.4.4.

The sole authority over what becomes a real order. Every submit_order call
must present a grant that passes `GrantVerifier.verify(...)` against:
  1. signature (Ed25519, our key)
  2. expiry (not past)
  3. clock skew (issued_at not absurdly future — defense against replay-with-future-clock)
  4. approval_id match (wrapper field == payload field)
  5. order_intent_hash match (this grant authorizes THIS intent only)

Replay protection lives in `winny.approval.store.ApprovalStore.consume_grant`
which atomically records (approval_id, nonce). Second consumption raises
GrantReplayError.

Key material:
  - private key: 32 raw bytes at WINNY_APPROVAL_KEY_PATH, mode 0600 on POSIX.
  - Generated on first run if missing.
  - Rotation (§3.4.4): every 90 days; old keys move to keys/archive/<date>/.
    Verifier MAY try archived keys for grants issued before rotation —
    deferred to v0.2 (current grants live ≤5 min so rotation is low-impact).

Threat model addressed (§3.4.2):
  - Replay of stolen grant         → nonce + ApprovalStore.consume_grant
  - Long-lived grant abuse         → TTL ≤ 5 min, cryptographically signed in payload
  - Compromised LLM forging grant  → signature is the gate; LLM cannot mint
  - User phishing                  → orthogonal (handled at chat layer)
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from winny.common.errors import (
    ApprovalError,
    GrantClockSkewError,
    GrantExpiredError,
    GrantIntentMismatchError,
    GrantMalformedError,
    GrantMismatchError,
    GrantSignatureInvalidError,
)
from winny.common.ids import ApprovalId, DecisionId
from winny.common.types import ApprovalGrant, OrderIntent

# ---------- canonical JSON (shared shape with audit log) ----------


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _b64url_encode(b: bytes) -> str:
    """RFC 4648 §5 url-safe base64, no padding."""
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    """Strict url-safe base64 decode. Rejects any non-alphabet character."""
    pad = "=" * (-len(s) % 4)
    # urlsafe_b64decode doesn't have `validate`; use b64decode with altchars instead.
    return base64.b64decode((s + pad).encode("ascii"), altchars=b"-_", validate=True)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------- intent hashing ----------


def canonical_intent_hash(intent: OrderIntent) -> str:
    """sha256 over the canonical-JSON form of an OrderIntent.

    This is what gets baked into the ApprovalGrant; the verifier rejects any
    submit_order whose recomputed hash differs — even by one byte. Eliminates
    the "approve for $100, switch to $10,000 before submit" attack.
    """
    payload = intent.model_dump(mode="json")
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


# ---------- key management ----------


class ApprovalKeyManager:
    """Loads or generates the Ed25519 keypair at `key_path`.

    File format: 32 raw bytes (Ed25519PrivateFormat.Raw). On POSIX we chmod 0600
    after writing; on Windows the file inherits ACLs from the parent dir.
    """

    def __init__(self, key_path: Path | str) -> None:
        self.key_path = Path(key_path)
        self._private: Ed25519PrivateKey | None = None

    def load_or_generate(self) -> Ed25519PrivateKey:
        """Return the live private key, creating + persisting one if absent."""
        if self._private is not None:
            return self._private
        if self.key_path.exists():
            self._private = self._load()
        else:
            self._private = self._generate_and_persist()
        return self._private

    def public_key(self) -> Ed25519PublicKey:
        return self.load_or_generate().public_key()

    def _load(self) -> Ed25519PrivateKey:
        try:
            raw = self.key_path.read_bytes()
        except OSError as e:
            raise ApprovalError(f"cannot read approval key at {self.key_path}: {e}") from e
        if len(raw) != 32:
            raise ApprovalError(
                f"approval key file is {len(raw)} bytes, expected 32 raw Ed25519 bytes"
            )
        return Ed25519PrivateKey.from_private_bytes(raw)

    def _generate_and_persist(self) -> Ed25519PrivateKey:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        # Best-effort tighten parent dir perms on POSIX; Windows is a no-op.
        with contextlib.suppress(OSError):
            self.key_path.parent.chmod(0o700)

        key = Ed25519PrivateKey.generate()
        raw = key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self.key_path.write_bytes(raw)
        with contextlib.suppress(OSError):
            self.key_path.chmod(0o600)
        return key


# ---------- verified payload ----------


@dataclass(frozen=True, slots=True)
class VerifiedGrant:
    """Result of GrantVerifier.verify — the trusted payload plus the nonce
    that ApprovalStore.consume_grant will use to detect replay.
    """

    approval_id: ApprovalId
    decision_id: DecisionId
    order_intent_hash: str
    issued_at: datetime
    expires_at: datetime
    nonce: str
    max_uses: int


# ---------- signer ----------


class GrantSigner:
    """Issues ApprovalGrant tokens. One per process; thread-safe under cryptography lib."""

    def __init__(
        self,
        key_manager: ApprovalKeyManager,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._keys = key_manager
        self._clock = clock

    def issue(
        self,
        *,
        approval_id: ApprovalId,
        decision_id: DecisionId,
        order_intent_hash: str,
        ttl: timedelta,
    ) -> ApprovalGrant:
        """Create + sign a fresh grant. TTL MUST be ≤ 5 min per §1.3."""
        if ttl <= timedelta(0):
            raise ApprovalError(f"ttl must be positive, got {ttl}")
        if ttl > timedelta(minutes=5):
            raise ApprovalError(f"ttl exceeds the §1.3 cap of 5 minutes: {ttl}")
        if len(order_intent_hash) != 64:
            raise ApprovalError(
                f"order_intent_hash must be 64 hex chars (sha256), got {len(order_intent_hash)}"
            )

        now = self._clock()
        payload: dict[str, Any] = {
            "approval_id": str(approval_id),
            "decision_id": str(decision_id),
            "order_intent_hash": order_intent_hash,
            "issued_at": now.isoformat(),
            "expires_at": (now + ttl).isoformat(),
            "nonce": secrets.token_urlsafe(16),
            "max_uses": 1,
        }
        payload_bytes = _canonical_json(payload).encode("utf-8")
        sig = self._keys.load_or_generate().sign(payload_bytes)
        token = f"{_b64url_encode(payload_bytes)}.{_b64url_encode(sig)}"
        return ApprovalGrant(
            grant_token=token,
            approval_id=approval_id,
            expires_at=now + ttl,
        )


# ---------- verifier ----------


class GrantVerifier:
    """Validates ApprovalGrants. Stateless beyond the public key + clock."""

    def __init__(
        self,
        key_manager: ApprovalKeyManager,
        *,
        clock: Callable[[], datetime] = _utcnow,
        clock_skew_tolerance: timedelta = timedelta(seconds=30),
    ) -> None:
        self._keys = key_manager
        self._clock = clock
        self._tolerance = clock_skew_tolerance

    def verify(self, grant: ApprovalGrant, *, expected_intent_hash: str) -> VerifiedGrant:
        """Validate signature, expiry, skew, and intent binding.

        Raises a specific ApprovalError subclass on each failure mode.
        Returns the trusted VerifiedGrant on success (caller passes nonce to
        ApprovalStore.consume_grant for replay protection).
        """
        # 1. Structure
        if grant.grant_token.count(".") != 1:
            raise GrantMalformedError("token must be exactly '<payload>.<sig>' (one period)")
        payload_b64, sig_b64 = grant.grant_token.split(".", 1)

        try:
            payload_bytes = _b64url_decode(payload_b64)
            sig = _b64url_decode(sig_b64)
        except Exception as e:
            raise GrantMalformedError(f"token base64 decode failed: {e}") from e

        # 2. Signature
        try:
            self._keys.public_key().verify(sig, payload_bytes)
        except InvalidSignature as e:
            raise GrantSignatureInvalidError("Ed25519 signature verification failed") from e

        # 3. Payload JSON
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise GrantMalformedError(f"payload is not valid JSON: {e}") from e

        # 4. Required fields
        required = {
            "approval_id",
            "decision_id",
            "order_intent_hash",
            "issued_at",
            "expires_at",
            "nonce",
            "max_uses",
        }
        missing = required - payload.keys()
        if missing:
            raise GrantMalformedError(f"payload missing required fields: {sorted(missing)}")

        # 5. Timing
        try:
            issued_at = datetime.fromisoformat(payload["issued_at"])
            expires_at = datetime.fromisoformat(payload["expires_at"])
        except ValueError as e:
            raise GrantMalformedError(f"bad ISO8601 timestamp: {e}") from e
        if issued_at.tzinfo is None or expires_at.tzinfo is None:
            raise GrantMalformedError("timestamps must be tz-aware")

        now = self._clock()
        if now >= expires_at:
            raise GrantExpiredError(
                f"grant expired at {expires_at.isoformat()}, now {now.isoformat()}"
            )
        if issued_at > now + self._tolerance:
            raise GrantClockSkewError(
                f"grant issued_at {issued_at.isoformat()} exceeds now+tolerance "
                f"({(now + self._tolerance).isoformat()})"
            )

        # 6. Wrapper ↔ payload consistency
        if payload["approval_id"] != str(grant.approval_id):
            raise GrantMismatchError(
                f"wrapper approval_id {grant.approval_id!r} != payload {payload['approval_id']!r}"
            )

        # 7. Intent binding
        if payload["order_intent_hash"] != expected_intent_hash:
            raise GrantIntentMismatchError(
                "grant authorizes a different OrderIntent — refusing to submit"
            )

        return VerifiedGrant(
            approval_id=ApprovalId(payload["approval_id"]),
            decision_id=DecisionId(payload["decision_id"]),
            order_intent_hash=payload["order_intent_hash"],
            issued_at=issued_at,
            expires_at=expires_at,
            nonce=payload["nonce"],
            max_uses=int(payload["max_uses"]),
        )
