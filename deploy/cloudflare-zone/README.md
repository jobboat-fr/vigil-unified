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
agents.

## La limitation de débit de l'API ne fonctionne pas (constaté le 21/09/2026)

Ce document affirmait que « la limitation de débit de l'API est faite par le Worker
`deploy/cloudflare-api` ». **C'est faux en production.** Mesuré sur
`POST /api/v1/learn/public/mot-de-passe`, une route du palier serré (20 requêtes / 60 s) :

* 45 requêtes à la suite : aucune refusée ;
* 60 requêtes en parallèle : aucune refusée ;
* 13 demandes de réinitialisation pour une adresse valide : treize `200`.

Le binding est pourtant déclaré dans `wrangler.jsonc` et wrangler l'affiche au
déploiement — `env.LIMITE_SENSIBLE (20 requests/60s)`. Il rend simplement `success: true`
à chaque appel. L'hypothèse la plus probable est que la limitation de débit des Workers
n'est pas ouverte sur ce compte ; elle échoue alors en silence, ce qui est le pire des
comportements pour une protection.

Ce que cela expose : rien ne plafonne l'activation, la réinitialisation de mot de passe,
la désinscription ni les formulaires publics. L'énumération de comptes reste impossible
(la réponse est toujours `envoye_si_compte`), mais dès que l'envoi d'e-mails sera
configuré, la route de réinitialisation devient un moyen d'inonder une boîte.

**Ce qui bloque le correctif :** la zone est sur l'offre **Free**, qui n'autorise
**qu'une seule règle** de limitation de débit — déjà prise par les tableaux des agents.
`limite-debit.json` contient désormais les deux règles souhaitées ; les appliquer telles
quelles demande soit une offre payante, soit de choisir laquelle des deux surfaces
protéger. À arbitrer, ce n'est pas une décision technique.

Il faut donc, dans l'ordre : vérifier dans le tableau de bord Cloudflare si la limitation
de débit des Workers est disponible sur le compte ; sinon, trancher entre les deux règles
ou passer à une offre qui les accepte toutes les deux.
