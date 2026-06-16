"""Vault — user document store that grounds the agent in real content.

Users upload legal documents, contracts, invoices. The flow:

  1. POST /v1/vault/documents  (JSON: filename + base64 content)
       → raw file lands in the private Supabase Storage bucket `vault`
       → a vault_documents row is inserted with status='processing'
       → text extraction (pypdf for PDFs, utf-8 decode for text) runs inline
       → classification runs as a background task: the Hermes agent on OVH
         labels the doc (category/title/parties/key dates/amounts/risk flags
         /summary) and the row flips to 'ready' (or 'failed', with the error).
  2. The agent sees the vault two ways:
       a. mcp-winnywoo tools (vault_list / vault_search / vault_get) hit the
          /v1/vault endpoints with the service token + user_id param — the
          agent pulls full text on demand during chat or meetings.
       b. gateway/routes/assistant.py injects a compact vault index into the
          chat context so the agent knows what documents exist without a
          tool roundtrip.

Auth model: per-user JWT scoping. With a service token (trusted backend,
e.g. mcp-winnywoo running inside Hermes) a `user_id` query param selects
the subject user; with a normal user JWT the param is ignored and the
token's sub wins — a user can never read another user's vault.

Risk surfacing (the "declare potential issues" requirement): risk_flags
from classification are returned in every list/index payload, so both the
UI and the agent see e.g. "auto-renews in 30 days" without opening the doc.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from winny_gateway.auth import get_current_user
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/vault", tags=["vault"])

MAX_FILE_BYTES = 15 * 1024 * 1024  # 15 MB cap per document
EXTRACT_CHAR_LIMIT = 50_000        # stored grounding text cap
CLASSIFY_TEXT_LIMIT = 12_000       # how much we show the classifier

ALLOWED_MIME_PREFIXES = (
    "application/pdf",
    "text/",
    "application/json",
    "application/xml",
    "image/",  # stored but not text-extracted
)

CATEGORIES = (
    "contract", "invoice", "legal", "identity",
    "financial", "correspondence", "other",
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _subject_user_id(user: dict[str, Any], requested: str | None) -> str:
    """Service token may act for any user; a real JWT is pinned to its sub."""
    if user.get("service_token") and requested:
        return requested
    return str(user.get("sub", "anon"))


def _db(request: Request) -> Any:
    from winny_gateway.db import get_admin_client

    return get_admin_client()


def _extract_text(filename: str, mime: str, blob: bytes) -> str:
    """Best-effort plain-text extraction. Empty string = nothing extractable."""
    try:
        if mime.startswith("application/pdf") or filename.lower().endswith(".pdf"):
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(blob))
            pages = []
            for page in reader.pages[:200]:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    continue
            return "\n".join(pages)[:EXTRACT_CHAR_LIMIT]
        if mime.startswith("text/") or mime in ("application/json", "application/xml"):
            return blob.decode("utf-8", errors="replace")[:EXTRACT_CHAR_LIMIT]
    except Exception as exc:
        logger.warning("vault extract failed for %s: %s", filename, exc)
    return ""


CLASSIFY_PROMPT = """You are a document classification engine. Analyze the document below and reply with ONLY a JSON object — no prose, no markdown fences.

Schema:
{{
  "category": one of {categories},
  "title": short human title (e.g. "Office lease — 12 Rue X, Paris"),
  "parties": ["names of involved parties"],
  "key_dates": [{{"label": "signature|expiry|due|renewal|other", "date": "YYYY-MM-DD"}}],
  "amounts": [{{"label": "total|monthly|deposit|other", "value": number, "currency": "EUR"}}],
  "risk_flags": [{{"severity": "high|medium|low", "note": "specific issue, e.g. auto-renewal clause, missing signature, past-due date, unlimited liability"}}],
  "summary": "3-4 sentence factual summary"
}}

Rules: dates in ISO form; if unknown use empty arrays; NEVER invent facts not present in the text; flag genuinely risky clauses only.

Filename: {filename}

Document text:
---
{text}
---"""


def parse_classification(raw: str) -> dict[str, Any]:
    """Parse the agent's JSON reply; tolerate fences and stray prose."""
    text = (raw or "").strip()
    # Strip markdown fences if the model added them anyway
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    # Take the outermost {...} block if there's prose around it
    if not text.startswith("{"):
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            text = m.group(0)
    data = json.loads(text)  # raises on garbage — caller marks 'failed'
    category = str(data.get("category", "other")).lower()
    if category not in CATEGORIES:
        category = "other"
    return {
        "category": category,
        "title": str(data.get("title") or "")[:300] or None,
        "parties": data.get("parties") or [],
        "key_dates": data.get("key_dates") or [],
        "amounts": data.get("amounts") or [],
        "risk_flags": data.get("risk_flags") or [],
        "summary": str(data.get("summary") or "")[:2000] or None,
    }


async def _classify_via_hermes(cfg: Any, filename: str, text: str) -> dict[str, Any]:
    """One-shot classification turn against the Hermes shim on OVH."""
    if not cfg.hermes_url:
        raise RuntimeError("hermes_not_configured")
    prompt = CLASSIFY_PROMPT.format(
        categories=list(CATEGORIES),
        filename=filename,
        text=text[:CLASSIFY_TEXT_LIMIT] if text else "(no machine-readable text — classify from the filename only)",
    )
    headers = {
        "content-type": "application/json",
        "x-hermes-proxy-auth": cfg.hermes_proxy_secret or "",
    }
    async with httpx.AsyncClient(timeout=cfg.hermes_timeout_seconds) as client:
        resp = await client.post(
            cfg.hermes_url.rstrip("/") + "/chat/message",
            headers=headers,
            json={
                "message": prompt,
                # Stateless session — classification must not pollute any
                # user's conversation memory.
                "session_id": f"vault-classify:{datetime.now(UTC).timestamp()}",
            },
        )
    resp.raise_for_status()
    reply = resp.json().get("reply") or ""
    return parse_classification(reply)


async def _classify_and_update(app_state: Any, doc_id: str, filename: str, text: str) -> None:
    """Background task: classify, then flip the row to ready/failed."""
    from winny_gateway.db import get_admin_client

    try:
        fields = await _classify_via_hermes(app_state.config, filename, text)
        fields["status"] = "ready"
        fields["classify_error"] = None
    except Exception as exc:
        logger.warning("vault classify failed for %s: %s", doc_id, exc)
        fields = {"status": "failed", "classify_error": str(exc)[:500]}
    fields["updated_at"] = datetime.now(UTC).isoformat()
    try:
        client = get_admin_client()
        await asyncio.to_thread(
            lambda: client.table("vault_documents").update(fields).eq("id", doc_id).execute()
        )
    except Exception as exc:
        logger.error("vault row update failed for %s: %s", doc_id, exc)


def _public_row(row: dict[str, Any], *, include_text: bool = False) -> dict[str, Any]:
    out = {
        k: row.get(k)
        for k in (
            "id", "filename", "mime_type", "size_bytes", "status", "category",
            "title", "summary", "parties", "key_dates", "amounts", "risk_flags",
            "classify_error", "created_at", "updated_at",
        )
    }
    if include_text:
        out["extracted_text"] = row.get("extracted_text")
    return out


# ─── Bodies ──────────────────────────────────────────────────────────────────


class UploadBody(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(default="application/octet-stream", max_length=128)
    content_base64: str = Field(min_length=1)


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    body: UploadBody,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Store a document + kick off agent classification."""
    user_id = _subject_user_id(user, None)

    mime = body.mime_type.lower()
    if not any(mime.startswith(p) for p in ALLOWED_MIME_PREFIXES):
        raise HTTPException(400, f"unsupported_type: {mime}")
    try:
        blob = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "bad_base64") from exc
    if len(blob) > MAX_FILE_BYTES:
        raise HTTPException(413, f"file_too_large: max {MAX_FILE_BYTES} bytes")
    if not blob:
        raise HTTPException(400, "empty_file")

    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", body.filename)[-120:]
    storage_path = f"{user_id}/{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{safe_name}"

    client = _db(request)
    try:
        await asyncio.to_thread(
            lambda: client.storage.from_("vault").upload(
                storage_path, blob, {"content-type": mime},
            )
        )
    except Exception as exc:
        logger.error("vault storage upload failed: %s", exc)
        raise HTTPException(502, "storage_upload_failed") from exc

    text = _extract_text(body.filename, mime, blob)

    row = {
        "user_id": user_id,
        "filename": body.filename,
        "mime_type": mime,
        "size_bytes": len(blob),
        "storage_path": storage_path,
        "status": "processing",
        "extracted_text": text or None,
    }
    try:
        res = await asyncio.to_thread(
            lambda: client.table("vault_documents").insert(row).execute()
        )
        doc = (getattr(res, "data", None) or [{}])[0]
    except Exception as exc:
        logger.error("vault row insert failed: %s", exc)
        raise HTTPException(502, "db_insert_failed") from exc

    doc_id = str(doc.get("id", ""))
    if doc_id:
        # Fire-and-forget classification; UI polls status.
        asyncio.create_task(
            _classify_and_update(request.app.state, doc_id, body.filename, text)
        )

    # Audit trail — uploads are evidence-grade events.
    try:
        from winny_gateway.routes.audit import _get_store  # type: ignore

        store = _get_store()
        if store is not None:
            store.append(
                "vault.upload",
                {"doc_id": doc_id, "filename": body.filename, "size": len(blob)},
                actor_email=user.get("email"),
                component="vault",
            )
    except Exception:
        pass

    return {"ok": True, "data": _public_row(doc)}


@router.get("/documents")
async def list_documents(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    user_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    uid = _subject_user_id(user, user_id)
    client = _db(request)
    res = await asyncio.to_thread(
        lambda: client.table("vault_documents")
        .select("id,filename,mime_type,size_bytes,status,category,title,summary,"
                "parties,key_dates,amounts,risk_flags,classify_error,created_at,updated_at")
        .eq("user_id", uid)
        .order("created_at", desc=True)
        .limit(max(1, min(limit, 200)))
        .execute()
    )
    rows = getattr(res, "data", None) or []
    return {"ok": True, "data": {"documents": rows, "count": len(rows)}}


@router.get("/documents/{doc_id}")
async def get_document(
    doc_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    user_id: str | None = None,
    include_text: bool = False,
) -> dict[str, Any]:
    uid = _subject_user_id(user, user_id)
    client = _db(request)
    res = await asyncio.to_thread(
        lambda: client.table("vault_documents")
        .select("*").eq("id", doc_id).eq("user_id", uid).limit(1).execute()
    )
    rows = getattr(res, "data", None) or []
    if not rows:
        raise HTTPException(404, "document_not_found")
    return {"ok": True, "data": _public_row(rows[0], include_text=include_text)}


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    user_id: str | None = None,
) -> dict[str, Any]:
    uid = _subject_user_id(user, user_id)
    client = _db(request)
    res = await asyncio.to_thread(
        lambda: client.table("vault_documents")
        .select("id,storage_path").eq("id", doc_id).eq("user_id", uid).limit(1).execute()
    )
    rows = getattr(res, "data", None) or []
    if not rows:
        raise HTTPException(404, "document_not_found")
    storage_path = rows[0].get("storage_path")
    try:
        if storage_path:
            await asyncio.to_thread(
                lambda: client.storage.from_("vault").remove([storage_path])
            )
    except Exception as exc:
        logger.warning("vault storage delete failed (%s): %s", storage_path, exc)
    await asyncio.to_thread(
        lambda: client.table("vault_documents").delete().eq("id", doc_id).execute()
    )
    return {"ok": True, "data": {"deleted": doc_id}}


@router.get("/search")
async def search_documents(
    q: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    user_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Full-text search across title/summary/extracted text — the agent's grep."""
    uid = _subject_user_id(user, user_id)
    if not q.strip():
        raise HTTPException(400, "empty_query")
    client = _db(request)

    def _query() -> Any:
        # PostgREST or-filter over ilike columns: portable and index-assisted
        # enough at vault scale (hundreds of docs, not millions).
        pattern = f"%{q.strip()[:80]}%"
        return (
            client.table("vault_documents")
            .select("id,filename,status,category,title,summary,risk_flags,created_at")
            .eq("user_id", uid)
            .or_(
                f"title.ilike.{pattern},summary.ilike.{pattern},"
                f"extracted_text.ilike.{pattern},filename.ilike.{pattern}"
            )
            .order("created_at", desc=True)
            .limit(max(1, min(limit, 25)))
            .execute()
        )

    res = await asyncio.to_thread(_query)
    rows = getattr(res, "data", None) or []
    return {"ok": True, "data": {"documents": rows, "count": len(rows), "query": q}}


# ─── Agent-grounding index (used by assistant.py + meeting contexts) ─────────


async def build_vault_index(user_id: str, limit: int = 25) -> list[dict[str, Any]]:
    """Compact per-user document index the agent can hold in context.

    Returns [] on any failure — grounding is additive, never blocking.
    """
    try:
        from winny_gateway.db import get_admin_client

        client = get_admin_client()
        res = await asyncio.to_thread(
            lambda: client.table("vault_documents")
            .select("id,filename,category,title,summary,risk_flags,status,created_at")
            .eq("user_id", user_id)
            .eq("status", "ready")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return getattr(res, "data", None) or []
    except Exception:
        return []
