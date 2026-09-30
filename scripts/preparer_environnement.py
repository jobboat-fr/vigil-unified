"""E3 — prépare (sans déployer) un environnement Railway hors prod : dev, test ou recette.

Usage :  python scripts/preparer_environnement.py dev|test|recette

- Les deux services (LEARN, passerelle) suivent la branche `env/<nom>` de leur dépôt.
- Réglages non secrets recopiés de la prod ; adresses propres à l'environnement
  (<nom>.app.vtlvs.com, <nom>.api.vtlvs.com).
- Secrets internes régénérés, partagés entre passerelle et LEARN du même environnement,
  jamais affichés. Aucune clé de fournisseur payant, aucune base de prod.
- Relances automatiques coupées (`LEARN_REMINDERS_LOOP=0`) : aucun e-mail ne part d'un
  environnement hors prod.
- `--stage` : les changements attendent d'être validés ; rien ne se déploie.

Prérequis (constaté le 30/09) : `railway environment edit` n'ajoute pas un service absent d'un
environnement (« No changes to apply »). Les instances de service arrivent avec E4 : dupliquer
l'environnement dans le tableau de bord Railway (changements « à valider », rien ne part), lancer
ce script qui remplace secrets, adresses et réglages, brancher la base hors prod (E4), puis
valider. Ne jamais valider une duplication de la prod telle quelle : elle porte la base et les
clés de production.
"""
from __future__ import annotations

import pathlib
import secrets
import shutil
import subprocess
import sys

ENV = sys.argv[1] if len(sys.argv) > 1 else ""
if ENV not in ("dev", "test", "recette"):
    sys.exit("usage : preparer_environnement.py dev|test|recette")

LEARN = "3b96d01c-1c67-459e-9b4f-a383117a4bbd"        # hbs-backend
PASSERELLE = "dc6597d9-fb62-41d3-8da4-3149efabdb07"   # vigil-unified
APP = f"https://{ENV}.app.vtlvs.com"
API = f"https://{ENV}.api.vtlvs.com"
ORIGINES = f"{APP},http://localhost:5173"

partages = {n: secrets.token_urlsafe(48) for n in ("HBS_API_TOKEN", "ORIGIN_EDGE_SECRET", "VTLVS_DELEGATION_SECRET")}
propres = {"LEARN_MAIL_SECRET": secrets.token_urlsafe(48), "WINNY_CRED_KEY": secrets.token_urlsafe(48),
           "WW_SERVICE_TOKEN": secrets.token_urlsafe(48)}

config = {
    LEARN: {
        "source.repo": "jobboat-fr/hbs-backend-",
        "source.branch": f"env/{ENV}",
        "build.builder": "RAILPACK",
        "deploy.startCommand": "uvicorn app.main:app --host 0.0.0.0 --port $PORT",
        "variables": {
            "ALLOWED_ORIGINS": ORIGINES,
            "LEARN_PUBLIC_URL": APP,
            "LEARN_REMINDERS_LOOP": "0",
            "ORIGIN_LOCK_MODE": "enforce",
            "VTLVS_MAIL_FALLBACK_DOMAIN": "vtlvs.com",
            "LEARN_MAIL_SECRET": propres["LEARN_MAIL_SECRET"],
            **partages,
        },
    },
    PASSERELLE: {
        "source.repo": "jobboat-fr/vigil-unified",
        "source.branch": f"env/{ENV}",
        "build.builder": "RAILPACK",
        "variables": {
            "AGENTS_ABONNEMENT_MODE": "enforce",
            "BEYOND_PRESENCE_BASE_URL": "https://api.bey.dev",
            "BEYOND_PRESENCE_DEFAULT_LANGUAGE": "fr",
            "LEARN_API_URL": API,
            "ORIGIN_LOCK_MODE": "enforce",
            "RAILWAY_DOCKERFILE_PATH": "Dockerfile.gateway",
            "TAVUS_BASE_URL": "https://tavusapi.com",
            "TAVUS_DEFAULT_LANGUAGE": "french",
            "WW_CORS_ORIGINS": ORIGINES,
            "WW_DEBUG": "false",
            "WW_LOG_FORMAT": "json",
            "WW_SIGNAL_RUNNER": "0",
            "WINNY_CRED_KEY": propres["WINNY_CRED_KEY"],
            "WW_SERVICE_TOKEN": propres["WW_SERVICE_TOKEN"],
            **partages,
        },
    },
}

args = [shutil.which("railway") or "railway", "environment", "edit", "-e", ENV, "--stage", "--json",
        "-m", f"E3 — {ENV} préparé (base : E4)"]
for service, reglages in config.items():
    for chemin, valeur in reglages.items():
        if chemin == "variables":
            for nom, v in valeur.items():
                args += ["--service-config", service, f"variables.{nom}.value", v]
        else:
            args += ["--service-config", service, chemin, valeur]

r = subprocess.run(args, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=100,
                   cwd=pathlib.Path(__file__).resolve().parent.parent)
# Jamais la commande ni les valeurs : elles portent les secrets. Seulement le verdict, masqué.
sortie = r.stdout + r.stderr
for s in [*partages.values(), *propres.values()]:
    sortie = sortie.replace(s, "•••")
print(ENV, "code", r.returncode)
print(sortie.strip()[-800:])
