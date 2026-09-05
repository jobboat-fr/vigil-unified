#!/usr/bin/env python
"""Run SQL against a Supabase project through the Management API.

Supabase's PostgREST endpoint cannot execute DDL, and the database password is a separate
credential we do not have. The Management API exposes a SQL endpoint that accepts a
personal access token, which is what this uses to apply migrations and read results back.

Credentials are read from ../.env.learn (gitignored) — never passed on the command line,
so they do not land in shell history.

Usage
-----
  python learn/tools/sbq.py --projects                 list projects the token can see
  python learn/tools/sbq.py --file learn/migrations/0001_x.sql
  python learn/tools/sbq.py --sql "select 1"
  python learn/tools/sbq.py --sql "..." --project <ref>
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.supabase.com/v1"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env.learn"


def load_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        sys.exit(f"missing {ENV_FILE} — see learn/README.md")
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def call(method: str, path: str, token: str, body: dict | None = None):
    req = urllib.request.Request(
        f"{API}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            # Cloudflare in front of the Management API rejects urllib's default
            # user-agent with a 1010; any conventional client string is accepted.
            "User-Agent": "learn-migrate/1.0 (+azzco)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:600]
        return {"__error__": f"HTTP {e.code}", "detail": detail}
    except Exception as e:  # network, DNS, timeout
        return {"__error__": type(e).__name__, "detail": str(e)}
    if not raw.strip():
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"__raw__": raw[:600]}


def show(result) -> int:
    if isinstance(result, dict) and "__error__" in result:
        print(f"  ✗ {result['__error__']}: {result.get('detail', '')}")
        return 1
    if isinstance(result, dict):
        print(json.dumps(result, indent=2, ensure_ascii=False)[:2000])
        return 0
    if not result:
        print("  (no rows)")
        return 0
    cols = list(result[0].keys())
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in result)) for c in cols}
    widths = {c: min(w, 46) for c, w in widths.items()}
    print("  " + " | ".join(c.ljust(widths[c]) for c in cols))
    print("  " + "-+-".join("-" * widths[c] for c in cols))
    for r in result[:200]:
        print("  " + " | ".join(str(r.get(c, ""))[: widths[c]].ljust(widths[c]) for c in cols))
    if len(result) > 200:
        print(f"  … {len(result) - 200} more rows")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sql")
    ap.add_argument("--file")
    ap.add_argument("--project")
    ap.add_argument("--projects", action="store_true")
    a = ap.parse_args()

    env = load_env()
    token = env.get("SUPABASE_PAT")
    if not token:
        sys.exit("SUPABASE_PAT missing from .env.learn")
    ref = a.project or env.get("LEARN_PROJECT_REF")

    if a.projects:
        res = call("GET", "/projects", token)
        if isinstance(res, dict) and "__error__" in res:
            return show(res)
        for p in res:
            print(f"  {p.get('id'):24} {p.get('name','')[:34]:34} "
                  f"{p.get('region',''):12} {p.get('status','')}")
        return 0

    sql = a.sql
    if a.file:
        sql = Path(a.file).read_text(encoding="utf-8")
    if not sql:
        sys.exit("nothing to run — pass --sql or --file")
    if not ref:
        sys.exit("no project ref — pass --project or set LEARN_PROJECT_REF")

    print(f"→ {ref}: {(a.file or sql.strip().splitlines()[0])[:70]}")
    return show(call("POST", f"/projects/{ref}/database/query", token, {"query": sql}))


if __name__ == "__main__":
    raise SystemExit(main())
