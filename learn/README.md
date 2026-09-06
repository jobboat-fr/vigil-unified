# LEARN moved — the package is no longer here

**2026-09-06.** The LEARN platform (the VTLVS product) lives in
[`jobboat-fr/hbs-backend-`](https://github.com/jobboat-fr/hbs-backend-) at `app/learn/`.

It was built here, on the reasoning in `../../hbs-backend/PLAN_V2.md` §12.0 — grow the
existing gateway into the LMS rather than start a repo. That reasoning stopped holding the
moment the API needed a permanent home: `winny_gateway` is deployed nowhere, and the
product needed an origin that stays up. `hbs-backend` was already on Railway, so LEARN went
there and `api.vtlvs.com` points at it.

For one day the package existed in both repos. The copies had already begun to diverge
before anyone edited them deliberately — which is the whole argument for not keeping two.

## Where things are now

| | |
|---|---|
| `app/learn/` in `hbs-backend-` | the package — routes, roles, db, 19 migrations |
| `tests/learn/` in `hbs-backend-` | 133 tests, including the live isolation guard |
| `tools/learn/` in `hbs-backend-` | `sbq.py` (migration runner), `verify_funnel.sql` |
| `web/` here | the SPA — still in this repo, deployed to `app.vtlvs.com` |
| `deploy/cloudflare-app/` here | the Worker config for that SPA |

The only file that differs between a `winny_gateway`-hosted and an `hbs-backend`-hosted copy
is the auth seam — `app/learn/gateway_auth.py` there. Nothing else about the package changed
in the move, and that is deliberate: two copies of an authorization rule drift, and the
drift is the hole.

## The SPA is the next thing to move

`web/` still lives here while serving a VTLVS hostname. That is the same split that just
cost a day, one layer up — worth closing before it costs it twice.
