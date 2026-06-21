"""Symmetric secret encryption for stored integration tokens.

Reuses the same Fernet master key as the broker credential store (WINNY_CRED_KEY),
so the whole gateway has one secret-at-rest key. Used to encrypt per-user provider
access tokens (e.g. a Plaid item access_token) before they touch the database.
"""
from __future__ import annotations

from winny.brokerage.credentials import _get_fernet


def encrypt_secret(plaintext: str) -> str:
    """Fernet-encrypt a secret → urlsafe token string (safe to store)."""
    return _get_fernet().encrypt((plaintext or "").encode()).decode()


def decrypt_secret(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt_secret`."""
    return _get_fernet().decrypt((token or "").encode()).decode()


def mask_secret(plaintext: str) -> str:
    """first4…last4 for safe display."""
    if not plaintext or len(plaintext) <= 8:
        return "****"
    return f"{plaintext[:4]}…{plaintext[-4:]}"
