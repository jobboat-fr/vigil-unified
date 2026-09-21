#!/usr/bin/env bash
# Le déploiement de VTLVS, en une commande — contrôles compris.
#
#   bash scripts/deployer.sh                tout : contrôles puis mise en ligne
#   bash scripts/deployer.sh --controles    les contrôles seuls, rien n'est déployé
#   bash scripts/deployer.sh --sans-controles   mise en ligne seule (à ses risques)
#
# ── Pourquoi ce script, et pas GitHub Actions ───────────────────────────────────────────
#
# Nous ne déployons pas depuis GitHub. Les Workers partent d'ici vers Cloudflare, et
# Railway se déclenche sur `git push`. Les workflows GitHub n'ont jamais rien déployé ; ils
# ne servaient qu'à faire tourner les contrôles — et depuis que les Actions du compte sont
# bloquées pour facturation (21/09/2026), ils ne les font même plus tourner.
#
# La règle « on ne déploie qu'après le vert » tient donc ici : `avant-deploiement.sh` joue
# les mêmes contrôles (style, tests, types, build, compilation des Workers, audits de
# dépendances) et ce script refuse de continuer s'il échoue.
#
# ── L'ordre compte ──────────────────────────────────────────────────────────────────────
#
# La bordure avant l'application : l'application appelle `api.vtlvs.com`, pas l'inverse.
# Une bordure en retard ferait échouer des appels que la nouvelle application attend déjà.
# Railway (LEARN, passerelle) part de son côté sur `git push` — il n'y a rien à lancer ici,
# mais il faut le savoir, car une migration doit être appliquée AVANT le code qui s'en sert
# (`hbs-backend/scripts/migrer.py`).

set -uo pipefail
cd "$(dirname "$0")/.."

RACINE_SITES="../winny woo"
MODE=${1:-}
ECHECS=()

titre() { printf '\n\033[1m── %s\033[0m\n' "$1"; }

deployer() {
  local nom=$1 config=$2 dossier=${3:-.}
  titre "$nom"
  if (cd "$dossier" && npx wrangler deploy --config "$config" 2>&1 | tail -3); then
    printf '   \033[32men ligne\033[0m\n'
  else
    printf '   \033[31mÉCHEC\033[0m\n'
    ECHECS+=("$nom")
  fi
}

if [ "$MODE" != "--sans-controles" ]; then
  titre "Contrôles avant déploiement"
  if ! bash scripts/avant-deploiement.sh; then
    printf '\n\033[31mContrôles en échec — rien n%ba été déployé.\033[0m\n' "'"
    exit 1
  fi
  [ "$MODE" = "--controles" ] && exit 0
fi

# Cloudflare, dans l'ordre des dépendances.
deployer "Bordure API (api.vtlvs.com)"     deploy/cloudflare-api/wrangler.jsonc
deployer "Application (app.vtlvs.com)"     deploy/cloudflare-app/wrangler.jsonc
deployer "Site (vtlvs.com)"                demo/landing/wrangler.jsonc      "$RACINE_SITES"
deployer "Documentation (docs)"            demo/sites/docs/wrangler.jsonc   "$RACINE_SITES"
deployer "État des services (status)"      demo/sites/status/wrangler.jsonc "$RACINE_SITES"
deployer "Académie"                        demo/wrangler.jsonc              "$RACINE_SITES"

printf '\n'
if [ ${#ECHECS[@]} -eq 0 ]; then
  printf '\033[32mTout est en ligne.\033[0m\n'
  printf 'Railway (LEARN, passerelle) suit son propre déclenchement sur `git push`.\n'
  printf 'Vérification : https://status.vtlvs.com/api/etat\n'
  exit 0
fi
printf '\033[31m%d déploiement(s) en échec :\033[0m\n' "${#ECHECS[@]}"
printf '  · %s\n' "${ECHECS[@]}"
exit 1
