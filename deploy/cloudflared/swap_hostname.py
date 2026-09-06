#!/usr/bin/env python
"""Point a vtlvs.com hostname at the gateway through a Cloudflare Tunnel.

Dry run by default. Nothing is created, deleted or repointed without `--apply`, because two
of the four steps are visible on the public internet within seconds.

    # look, change nothing
    CF_API_TOKEN=... python deploy/cloudflared/swap_hostname.py --hostname learn.vtlvs.com

    # do it
    CF_API_TOKEN=... python deploy/cloudflared/swap_hostname.py --hostname learn.vtlvs.com --apply

    # take a hostname that a Worker currently serves (deletes that route)
    CF_API_TOKEN=... python deploy/cloudflared/swap_hostname.py \
        --hostname www.vtlvs.com --take-from-worker --apply

Order is deliberate. The tunnel and its DNS record are created *first*, and the Worker route
is deleted *last*, so the window where the hostname serves nothing is as short as the API
allows. Doing it the other way round — free the name, then build the replacement — is the
same end state with a multi-minute outage in the middle.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"
ACCOUNT = "5abbd8760dd8c66733c664865f56a4cd"
ZONE = "8a20e4eeb0e5a7fe5f5f37622705deb1"
ZONE_NAME = "vtlvs.com"
TUNNEL_NAME = "vigil-learn"


def call(token: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "learn-ops/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")
    except Exception as e:  # network, DNS, timeout
        return 0, {"errors": [{"message": f"{type(e).__name__}: {e}"}]}


def die(msg: str, payload: dict | None = None) -> None:
    print(f"  ✗ {msg}")
    if payload:
        print("   ", json.dumps(payload.get("errors") or payload)[:400])
    sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hostname", required=True,
                    help=f"the name to serve, inside {ZONE_NAME}")
    ap.add_argument("--origin", default="http://127.0.0.1:8000",
                    help="where cloudflared forwards to on the host that runs it")
    ap.add_argument("--take-from-worker", action="store_true",
                    help="delete the Worker route currently serving this hostname. "
                         "Both vtlvs.com/* and www.vtlvs.com/* serve the LIVE landing site")
    ap.add_argument("--apply", action="store_true", help="actually make the changes")
    a = ap.parse_args()

    token = os.environ.get("CF_API_TOKEN", "")
    if not token:
        die("CF_API_TOKEN is not set")
    if not a.hostname.endswith(ZONE_NAME):
        die(f"{a.hostname} is not inside {ZONE_NAME}")

    mode = "APPLY" if a.apply else "DRY RUN — nothing will change"
    print(f"\n  {mode}\n  hostname: {a.hostname}\n  origin:   {a.origin}\n")

    # ---------------------------------------------------------------- 0. token
    s, r = call(token, "GET", "/user/tokens/verify")
    if not r.get("success"):
        die("token did not verify", r)
    print("  ✓ token active")

    # The old token could read Worker routes and nothing else; check the two permissions
    # this actually needs *before* touching anything, so a half-done swap is impossible.
    s, r = call(token, "GET", f"/zones/{ZONE}/dns_records?per_page=1")
    if not r.get("success"):
        die("token cannot read DNS on this zone — add Zone → DNS → Edit, and make sure "
            f"Zone Resources includes {ZONE_NAME}", r)
    print("  ✓ DNS readable")
    s, r = call(token, "GET", f"/accounts/{ACCOUNT}/cfd_tunnel?is_deleted=false")
    if not r.get("success"):
        die("token cannot list tunnels — add Account → Cloudflare Tunnel → Edit", r)
    tunnels = r["result"]
    print(f"  ✓ tunnels listable ({len(tunnels)} existing)")

    # ---------------------------------------------------------------- 1. the tunnel
    tunnel = next((t for t in tunnels if t["name"] == TUNNEL_NAME), None)
    if tunnel:
        print(f"  · tunnel {TUNNEL_NAME} already exists — reusing  id={tunnel['id']}")
    elif not a.apply:
        print(f"  → would create tunnel {TUNNEL_NAME}")
    else:
        s, r = call(token, "POST", f"/accounts/{ACCOUNT}/cfd_tunnel",
                    {"name": TUNNEL_NAME, "config_src": "cloudflare"})
        if not r.get("success"):
            die("could not create the tunnel", r)
        tunnel = r["result"]
        print(f"  ✓ tunnel created  id={tunnel['id']}")

    tunnel_id = tunnel["id"] if tunnel else "<new>"
    target = f"{tunnel_id}.cfargotunnel.com"

    # ---------------------------------------------------------------- 2. ingress
    # config_src=cloudflare means the ingress rules live in Cloudflare, not in a local
    # config.yml — so the host running cloudflared needs only the token, and the routing is
    # editable without redeploying anything.
    ingress = {"config": {"ingress": [
        {"hostname": a.hostname, "service": a.origin},
        {"service": "http_status:404"},
    ]}}
    if a.apply and tunnel:
        s, r = call(token, "PUT",
                    f"/accounts/{ACCOUNT}/cfd_tunnel/{tunnel_id}/configurations", ingress)
        print("  ✓ ingress set" if r.get("success") else f"  ✗ ingress: {json.dumps(r.get('errors'))[:200]}")
    else:
        print(f"  → would route {a.hostname} → {a.origin}, everything else → 404")

    # ---------------------------------------------------------------- 3. the Worker route
    # Read it either way: the operator should see what is being taken even in a dry run.
    s, r = call(token, "GET", f"/zones/{ZONE}/workers/routes")
    routes = r.get("result", []) if r.get("success") else []
    clashing = [x for x in routes
                if x["pattern"].split("/")[0] in (a.hostname, f"*{a.hostname}")]
    for x in clashing:
        print(f"  · {a.hostname} is currently served by Worker '{x['script']}' "
              f"(route {x['pattern']}, id {x['id']})")
    if clashing and not a.take_from_worker:
        die("that hostname belongs to a Worker. Re-run with --take-from-worker if you "
            "intend to take it — on vtlvs.com that is the live landing site")

    # ---------------------------------------------------------------- 4. DNS
    s, r = call(token, "GET", f"/zones/{ZONE}/dns_records?name={a.hostname}")
    existing = r.get("result") or [] if r.get("success") else []

    # Only address records are in the way. MX, TXT, CAA at the same name are unrelated and
    # must survive — the apex carries Zoho mail routing plus SPF and DKIM, and quietly
    # dropping any of those breaks the organisme's email rather than its website.
    addr = [x for x in existing if x["type"] in ("A", "AAAA", "CNAME")]
    other = [x for x in existing if x not in addr]
    for x in other:
        print(f"  · leaving {x['type']} {x['name']} alone")

    record = {"type": "CNAME", "name": a.hostname, "content": target,
              "proxied": True, "ttl": 1,
              "comment": "Cloudflare Tunnel → VIGIL/LEARN gateway"}

    if not addr:
        if not a.apply:
            print(f"  → would create CNAME {a.hostname} → {target} (proxied)")
        else:
            s, r = call(token, "POST", f"/zones/{ZONE}/dns_records", record)
            print("  ✓ DNS created" if r.get("success")
                  else f"  ✗ DNS: {json.dumps(r.get('errors'))[:250]}")
    else:
        for x in addr:
            print(f"  · existing: {x['type']} {x['name']} → {x['content']} "
                  f"(proxied={x.get('proxied')})")
        # A CNAME cannot coexist with A records at the same name, and `www` here carries
        # two of them. So the first is converted in place and the rest are removed —
        # converting leaves the name resolvable at every instant, which deleting first
        # would not.
        if not a.apply:
            print(f"  → would convert {addr[0]['type']} → CNAME {target}"
                  + (f", and delete {len(addr) - 1} sibling record(s)" if len(addr) > 1 else ""))
        else:
            s, r = call(token, "PUT", f"/zones/{ZONE}/dns_records/{addr[0]['id']}", record)
            print("  ✓ DNS repointed" if r.get("success")
                  else f"  ✗ DNS: {json.dumps(r.get('errors'))[:250]}")
            for x in addr[1:]:
                s, r = call(token, "DELETE", f"/zones/{ZONE}/dns_records/{x['id']}")
                print(f"  ✓ removed sibling {x['type']} {x['content']}" if r.get("success")
                      else f"  ✗ sibling: {json.dumps(r.get('errors'))[:200]}")

    # ---------------------------------------------------------------- 5. free the name
    # Last, and only now: the replacement is already live, so the hostname is never
    # unserved for longer than this one call takes.
    for x in clashing:
        if not a.apply:
            print(f"  → would DELETE Worker route {x['pattern']} ({x['script']})")
        else:
            s, r = call(token, "DELETE", f"/zones/{ZONE}/workers/routes/{x['id']}")
            print(f"  ✓ Worker route {x['pattern']} removed" if r.get("success")
                  else f"  ✗ route: {json.dumps(r.get('errors'))[:250]}")

    # ---------------------------------------------------------------- verdict
    # Printed last and loudly. The first two runs of this script "succeeded" from the
    # operator's point of view — the tunnel was created, the run token was printed, and the
    # one line saying DNS had been refused scrolled past above it. A summary that has to be
    # read is worth more than an error that only has to be emitted.
    if a.apply:
        s, r = call(token, "GET", f"/zones/{ZONE}/dns_records?name={a.hostname}")
        now = (r.get("result") or [{}])[0] if r.get("success") else {}
        landed = now.get("type") == "CNAME" and now.get("content") == target
        print("\n  " + "=" * 66)
        if landed:
            print(f"  ✓ {a.hostname} now points at the tunnel.")
        else:
            print(f"  ✗ {a.hostname} does NOT point at the tunnel.")
            print(f"    it is still: {now.get('type')} → {now.get('content')}")
            if now.get("type") == "AAAA" and str(now.get("content")) == "100::":
                print("\n    `AAAA 100::` is how Cloudflare represents a Worker *custom"
                      " domain*.\n    Cloudflare refuses to edit that record while the"
                      " Worker claims the\n    hostname, and the Worker also outranks DNS"
                      " when serving traffic.\n\n    Delete the Worker that owns it"
                      " (Workers & Pages → the worker → Delete);\n    that releases the"
                      " record too. Then re-run this.")
        print("  " + "=" * 66)

    if a.apply and tunnel:
        s, r = call(token, "GET", f"/accounts/{ACCOUNT}/cfd_tunnel/{tunnel_id}/token")
        run_token = r.get("result") if r.get("success") else None
        print("\n  Run the connector on the host that serves the origin:\n")
        if run_token:
            print(f"    cloudflared tunnel run --token {run_token[:24]}…"
                  "   (full token printed below)\n")
            print(f"  FULL RUN TOKEN (treat as a credential):\n    {run_token}\n")
        else:
            print(f"    cloudflared tunnel run {TUNNEL_NAME}\n")
        print(f"  Then set, in the Vercel project for the vitrine:\n"
              f"    LEARN_API_URL=https://{a.hostname}\n"
              f"    LEARN_TENANT_SLUG=hbs\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
