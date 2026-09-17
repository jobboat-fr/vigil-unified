# Zone vtlvs.com — règles Cloudflare (offre Free)

Appliquées le 2026-09-17 par l'API (`PUT /zones/{zone}/rulesets/phases/<phase>/entrypoint`).
Ce dossier est la référence : toute modification passe par ces fichiers, puis par un nouveau `PUT`.

| Fichier | Phase | Effet |
|---|---|---|
| `regles-pare-feu.json` | `http_request_firewall_custom` | bloque les chemins de scanners et les méthodes HTTP inutiles |
| `limite-debit.json` | `http_ratelimit` | 100 requêtes / 10 s par IP sur les tableaux des agents |

Réglages de zone : TLS minimum 1.2, HTTPS forcé, SSL `full`, TLS 1.3 actif.
Le jeu de règles géré gratuit de Cloudflare est actif d'office.

**Bot Fight Mode : volontairement désactivé.** Sur l'offre Free, aucune règle ne peut l'exempter. Il
défierait les appels de serveur à serveur dont la plateforme dépend : Vercel → api.vtlvs.com,
passerelle Railway → api.vtlvs.com, webhooks Resend et LiveKit → app.vtlvs.com, proxy des tableaux →
agents. La limitation de débit de l'API est faite par le Worker `deploy/cloudflare-api`.
