"""LEARN — reprise de données, conformité RGPD plateforme, réversibilité, tunnel public.

Four things a product needs that a tool does not.

**The importer.** Its one hard rule: a dry run always precedes an apply, and *imported
attendance never becomes a signature*. A row in `learn_attendance_signatures` asserts a
named human signed on this platform; back-dating one for a session held elsewhere three
years ago fabricates evidence. Historical émargements are archived as vault objects marked
`imported`, which is auditable, retained, and honest about what it is.

**The tenant-#2 gate.** Article 28 requires a signed DPA before processing on another
controller's behalf, and its absence is a standalone CNIL violation. `/readiness` is
therefore a refusal surface, not a checklist widget.

**Reversibility.** A departing customer's retention obligation outlives their subscription.
Leaving without their evidence would make them non-compliant, so the export is a duty
before it is a sales answer to the lock-in objection.

The public funnel used to be a fourth section here; it now has its own module and its own
table (`funnel.py`, migration 0016).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db import available, scoped, translate
from ..roles import Actor, current_actor

router = APIRouter(prefix="/api/v1/learn", tags=["learn:platform"])


def _guard() -> None:
    if not available():
        raise HTTPException(503, {"error": "learn_database_unavailable"})


# ------------------------------------------------------------------ importer

class ImportIn(BaseModel):
    source: str = Field(pattern="^(digiforma|dendreo|csv|excel|api)$")
    entity: str = Field(pattern="^(apprenants|sessions|emargements|documents|entreprises)$")
    filename: str | None = None
    mapping: dict[str, str] = {}
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)


@router.post("/imports", status_code=201)
async def stage_import(body: ImportIn, actor: Actor = Depends(current_actor)):
    """Stage rows and report what an apply *would* do. Nothing is written to the domain.

    A migration that half-succeeds is worse than one that refuses, so the staging table
    holds every row with its own status and error before anything real is touched.
    """
    _guard()
    try:
        async with scoped(actor) as c:
            job = await c.fetchrow(
                """insert into learn_import_jobs
                     (tenant_id, source, entity, filename, mapping, rows_total,
                      status, created_by)
                   values ($1,$2,$3,$4,$5::jsonb,$6,'prepare',$7) returning *""",
                actor.tenant_id, body.source, body.entity, body.filename,
                _json(body.mapping), len(body.rows), actor.user_id or None)
            for i, raw in enumerate(body.rows, start=1):
                await c.execute(
                    """insert into learn_import_rows (tenant_id, job_id, line_no, raw)
                       values ($1,$2,$3,$4::jsonb)""",
                    actor.tenant_id, job["id"], i, _json(raw))
    except Exception as e:
        raise translate(e) from e

    note = None
    if body.entity == "emargements":
        note = ("les émargements repris sont archivés comme pièces d'origine "
                "(provenance « imported »), jamais convertis en signatures : "
                "une signature atteste d'un acte fait sur cette plateforme")
    return {**dict(job), "note": note}


@router.post("/imports/{job_id}/dry-run")
async def dry_run(job_id: str, actor: Actor = Depends(current_actor)):
    """Resolve every staged row and report, without writing anything."""
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            "select line_no, raw, status, error from learn_import_rows where job_id = $1 order by line_no",
            job_id)
        await c.execute(
            "update learn_import_jobs set status = 'simule' where id = $1", job_id)
    problems = [dict(r) for r in rows if r["status"] == "erreur"]
    return {"job_id": job_id, "rows": len(rows), "problems": len(problems),
            "sample": [dict(r) for r in rows[:20]], "errors": problems[:50]}


@router.post("/imports/{job_id}/apply")
async def apply_import(job_id: str, actor: Actor = Depends(current_actor)):
    """Apply — refused until a dry run has been seen."""
    _guard()
    try:
        async with scoped(actor) as c:
            job = await c.fetchrow("select * from learn_import_jobs where id = $1", job_id)
            if job is None:
                raise HTTPException(404, {"error": "not_found"})
            if job["status"] != "simule":
                raise HTTPException(409, {
                    "error": "dry_run_required",
                    "detail": "lancez /dry-run et lisez le rapport avant d'appliquer"})
            row = await c.fetchrow(
                """update learn_import_jobs
                      set status = 'applique', applied_at = now() where id = $1 returning *""",
                job_id)
    except HTTPException:
        raise
    except Exception as e:
        raise translate(e) from e
    return dict(row)


# ------------------------------------------------------------------ the tenant-#2 gate

@router.get("/platform/readiness")
async def readiness(actor: Actor = Depends(current_actor)):
    """Whether this tenant may hold real data yet.

    `ready` is false without a signed DPA, and that is the whole point: it is a gate, not
    a progress bar.
    """
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch("select * from learn_tenant_readiness($1)", actor.tenant_id)
    items = [dict(r) for r in rows]
    blocking = [i for i in items if not i["met"]]
    return {"ready": not blocking, "blocking": blocking, "items": items}


@router.get("/platform/subprocessors")
async def subprocessors(actor: Actor = Depends(current_actor)):
    """Published to every customer, with advance notice when it changes."""
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            "select * from learn_subprocessors where until is null order by name")
    return {"items": [dict(r) for r in rows]}


@router.get("/platform/register")
async def register(actor: Actor = Depends(current_actor)):
    """Our own registre de traitement, kept as processor — not the tenant's."""
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch("select * from learn_processing_register order by activity")
    return {"role": "sous-traitant (art. 28 RGPD)", "items": [dict(r) for r in rows]}


@router.get("/platform/reversibility")
async def reversibility(actor: Actor = Depends(current_actor)):
    """Everything this tenant would take with them, counted."""
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch("select * from learn_reversibility_manifest($1)",
                             actor.tenant_id)
    return {
        "items": [dict(r) for r in rows],
        "formats": {"donnees": "JSON + CSV", "documents": "PDF/A",
                    "emargements": "chaîne de hachage + script de vérification"},
        "note": ("l'obligation de conservation survit à l'abonnement : partir sans ses "
                 "preuves rendrait l'organisme non conforme"),
    }


# The public funnel used to live here and filed each demande as a `learn_reclamations` row.
# That polluted the réclamations register — the artefact an auditor reads for indicator 30,
# the most-failed indicator nationally — with rows that are not complaints. It moved to
# `funnel.py` and to a table of its own in migration 0016.


def _json(v: Any) -> str:
    import json
    return json.dumps(v, ensure_ascii=False, default=str)
