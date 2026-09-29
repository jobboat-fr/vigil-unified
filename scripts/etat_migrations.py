"""État des migrations de la passerelle — l'équivalent de `hbs-backend/scripts/migrer.py --etat`.

La passerelle n'a pas de table de suivi : ses migrations (winny_gateway/migrations/*.sql) ont
été appliquées à la main. Ce script vérifie, fichier par fichier, que ce que chacun crée
(tables, colonnes ajoutées, fonctions) existe bien en base. Lecture seule, dans une
transaction en lecture seule. `_retirees/` est ignoré : ces migrations ne s'appliquent pas.

    LEARN_DATABASE_URL=… python scripts/etat_migrations.py

Sortie 0 si tout est présent, 1 sinon.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

import asyncpg

DOSSIER = Path(__file__).resolve().parent.parent / "winny_gateway" / "migrations"


def objets(sql: str) -> tuple[set[str], list[tuple[str, str]], set[str]]:
    s = re.sub(r"--[^\n]*", "", sql).lower()
    tables = set(re.findall(r"create table(?: if not exists)? (?:public\.)?([a-z_0-9]+)", s))
    colonnes = re.findall(
        r"alter table (?:if exists )?(?:only )?(?:public\.)?([a-z_0-9]+)\s+add column(?: if not exists)? ([a-z_0-9]+)", s)
    fonctions = set(re.findall(r"create (?:or replace )?function (?:public\.)?([a-z_0-9]+)", s))
    return tables, colonnes, fonctions


async def main() -> int:
    url = os.environ.get("LEARN_DATABASE_URL")
    if not url:
        print("LEARN_DATABASE_URL absent", file=sys.stderr)
        return 2
    c = await asyncpg.connect(url)
    manquants = 0
    try:
        async with c.transaction(readonly=True):
            for f in sorted(DOSSIER.glob("*.sql")):
                tables, colonnes, fonctions = objets(f.read_text(encoding="utf-8"))
                absents: list[str] = []
                for t in tables:
                    if not await c.fetchval("select to_regclass('public.' || $1) is not null", t):
                        absents.append(f"table {t}")
                for t, col in colonnes:
                    if not await c.fetchval(
                            "select count(*) from information_schema.columns "
                            "where table_schema = 'public' and table_name = $1 and column_name = $2", t, col):
                        absents.append(f"colonne {t}.{col}")
                for fn in fonctions:
                    if not await c.fetchval("select count(*) from pg_proc where proname = $1", fn):
                        absents.append(f"fonction {fn}")
                manquants += bool(absents)
                etat = "ok       " if not absents else "MANQUANTE"
                print(f"  {etat}  {f.name}" + (f"  → {', '.join(absents)}" if absents else ""))
    finally:
        await c.close()
    return 1 if manquants else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
