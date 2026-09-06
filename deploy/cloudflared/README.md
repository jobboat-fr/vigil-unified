# Exposing the gateway through a Cloudflare Tunnel

The gateway (`winny_gateway` + `learn/`) has no public origin. That is the concrete blocker
for the LEARN tunnel: the vitrine runs on Vercel, so `LEARN_API_URL` cannot point at
`localhost`, and until it has a real HTTPS origin `/preinscription` degrades to the contact
path on the live site.

A Cloudflare Tunnel fixes that without opening a port: `cloudflared` dials **out** to
Cloudflare and Cloudflare routes a hostname down that connection. Nothing is exposed on the
host's own firewall, which is the reason to prefer it over a public port on OVH.

## What was found on the zone, 2026-09-05

Zone `vtlvs.com` — id `8a20e4eeb0e5a7fe5f5f37622705deb1`, account `5abbd8760dd8c66733c664865f56a4cd`.

| Worker route | Script |
|---|---|
| `vtlvs.com/*` | `vtlvs-landing-beta` |
| `www.vtlvs.com/*` | `vtlvs-landing-beta` |

No Cloudflare Tunnels exist on the account yet.

**Both of those routes serve the live VTLVS landing site** — the public acquisition, SEO,
legal, FAQ and signup surface described in `VTLVS-OPERATIONS-HANDOFF-2026-08-28.md`.
Deleting either one takes that page off that hostname; there is no second route behind it.

Adding a new subdomain takes nothing away, which is why the steps below use one.

## Token scope — measured, 2026-09-05

The token supplied on 2026-09-05 (`cfut_132Xb…`, logged for rotation) verifies active but is
**read-only for everything this needs**. Probed, not assumed:

| Call | Result |
|---|---|
| `GET /user/tokens/verify` | ✅ active |
| `GET /zones` | ✅ `vtlvs.com` |
| `GET /zones/{z}/workers/routes` | ✅ two routes, both `vtlvs-landing-beta` |
| `GET /accounts/{a}/cfd_tunnel` | ✅ empty list |
| `POST /accounts/{a}/cfd_tunnel` | ❌ **403** — cannot create a tunnel |
| `GET /zones/{z}/dns_records` | ❌ **403** |
| `POST /zones/{z}/dns_records` | ❌ **403** — cannot write DNS |
| `GET /accounts/{a}/workers/domains` | ❌ 403 |

A tunnel hostname *is* a DNS record — a CNAME to `<tunnel-id>.cfargotunnel.com` — so with
this token the hostname cannot be created, and neither can the tunnel it would point at.

Issue a token with:

```
Account → Cloudflare Tunnel → Edit
Zone    → DNS               → Edit      (zone: vtlvs.com)
Zone    → Workers Routes    → Edit      (only needed to move a hostname off the Worker)
```

### If the hostname really is to be taken from the landing site

Order matters, because doing it the other way round leaves the site dark for the length of
the gap:

1. create the tunnel and its credentials file;
2. start `cloudflared` and confirm the origin answers;
3. **only then** delete the Worker route (`www.vtlvs.com/*`, id `bc81e44b…`, or
   `vtlvs.com/*`, id `49c4cf0f…`);
4. repoint the DNS record for that hostname to `<tunnel-id>.cfargotunnel.com`.

Between 3 and 4 the hostname serves nothing. Keep it short, and do it outside business
hours — that page is VTLVS's public acquisition surface.

## Steps once the token can write DNS

```bash
# 1. cloudflared, portable, no admin rights needed
#    https://github.com/cloudflare/cloudflared/releases/latest  (cloudflared-windows-amd64.exe)

# 2. Authenticate this machine against the account (opens a browser)
cloudflared tunnel login

# 3. Create the named tunnel — this writes ~/.cloudflared/<id>.json
cloudflared tunnel create vigil-learn

# 4. Bind the hostname. This is the step the current token cannot do.
cloudflared tunnel route dns vigil-learn learn.vtlvs.com

# 5. Run it against the local gateway
cloudflared tunnel --config deploy/cloudflared/config.yml run vigil-learn
```

Then point the vitrine at it — in Vercel, for the `HBS` project:

```
LEARN_API_URL=https://learn.vtlvs.com
LEARN_TENANT_SLUG=hbs
```

## Running the gateway behind it

```bash
# LEARN_DATABASE_URL comes from .env.learn (gitignored). The pooler, session mode:
#   postgresql://postgres.<ref>:<pw>@aws-1-eu-west-3.pooler.supabase.com:5432/postgres
# Session mode matters: LEARN opens one transaction per request and holds `set local role`
# and `set_config(..., is_local => true)` for its duration.
uvicorn winny_gateway.app:create_app --factory --host 127.0.0.1 --port 8000
```

## Two things to decide before pointing a hostname at this

1. **The gateway is not a static site.** Whatever host runs `cloudflared` has to stay up for
   the hostname to answer. A laptop is fine for driving the routes today; it is not where
   `learn.vtlvs.com` should live permanently. OVH is the obvious home — the same host
   already runs the Hermes agent and Caddy.
2. **`vtlvs.com` is VTLVS's zone, not LEARN's.** Serving an AZZ&CO product for tenant HBS
   from a hostname under the VTLVS brand couples two unrelated businesses in DNS, in TLS,
   and in whatever an auditor reads off the certificate. `learn.vtlvs.com` is fine as a
   staging origin; a tenant-facing name belongs under `hbs-formation.fr`, and the product's
   own name belongs under whatever domain AZZ&CO ends up owning.
