#!/usr/bin/env bash
# Les mêmes contrôles que la CI (.github/workflows/vtlvs.yml), joués sur cette machine.
#
# Pourquoi ce script existe : GitHub Actions est arrêté sur l'organisation jobboat-fr
# (« account is locked due to a billing issue », constaté le 19/09/2026). Tant que la
# facturation n'est pas rétablie, la branche protégée ne peut pas recevoir de contrôle vert
# — la règle « on ne déploie qu'après le vert » tient donc ici, à la main, avant chaque
# `wrangler deploy` ou `railway up`.
#
#   bash scripts/avant-deploiement.sh            # tout
#   bash scripts/avant-deploiement.sh rapide     # sans les audits de dépendances (~1 min)
#
# Sortie 0 = rien ne s'oppose au déploiement. Toute autre sortie = on ne déploie pas.

set -uo pipefail
cd "$(dirname "$0")/.."

RAPIDE=${1:-}
ECHECS=()
PY=$([ -x .venv/Scripts/python.exe ] && echo .venv/Scripts/python.exe || echo python3)

etape() {
  local titre=$1; shift
  printf '\n\033[1m── %s\033[0m\n' "$titre"
  if "$@"; then
    printf '   \033[32mok\033[0m\n'
  else
    printf '   \033[31mÉCHEC\033[0m\n'
    ECHECS+=("$titre")
  fi
}

etape "Passerelle — style (ruff)"        "$PY" -m ruff check winny_gateway winny/council services/meeting_agent
etape "Passerelle — tests"               "$PY" -m pytest -q tests/winny_gateway tests/meeting_agent
etape "Application — types"              npx tsc -b web
etape "Application — build"              npm run build --workspace web
etape "Bordure API — compilation"        npx wrangler deploy --dry-run --outdir .wrangler/verif-api --config deploy/cloudflare-api/wrangler.jsonc
etape "Bordure App — compilation"        npx wrangler deploy --dry-run --outdir .wrangler/verif-app --config deploy/cloudflare-app/wrangler.jsonc

if [ "$RAPIDE" != "rapide" ]; then
  etape "Dépendances Python"             "$PY" -m pip_audit --skip-editable     --ignore-vuln GHSA-4xh5-x5gv-qwph     --ignore-vuln PYSEC-2026-3721     --ignore-vuln PYSEC-2026-3447
  # Ce qui part chez Cloudflare, c'est `web` — et lui seul. L'arbre racine contient
  # `agent-browser`, l'automatisation de navigateur héritée de Hermes : elle n'est
  # déployée nulle part, et ses alertes noieraient celles qui comptent. On l'affiche
  # quand même, sans bloquer, pour que personne ne découvre son existence un jour de
  # crise.
  etape "Dépendances npm (application)"  npm audit --workspace web --omit=dev --audit-level=high
  printf '
[1m── Arbre racine hérité de Hermes (pour information)[0m
'
  npm audit --workspaces=false --omit=dev 2>&1 | tail -3
fi

printf '\n'
if [ ${#ECHECS[@]} -eq 0 ]; then
  printf '\033[32mTout est vert — le déploiement peut partir.\033[0m\n'
  exit 0
fi
printf '\033[31mOn ne déploie pas. %d contrôle(s) en échec :\033[0m\n' "${#ECHECS[@]}"
printf '  · %s\n' "${ECHECS[@]}"
exit 1
