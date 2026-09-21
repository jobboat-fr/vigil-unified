# Workflows hérités de Hermes — désactivés

Ce dossier n'est pas `.github/workflows` : GitHub n'y exécute rien.

Ces automatisations viennent du projet Hermes dont VTLVS est issu (publication PyPI, image
Docker, site de documentation, index des compétences, vérifications de contribution…). Elles ne
correspondent ni à nos dépôts ni à nos déploiements : les laisser actives, c'était entretenir des
contrôles qui ne protègent rien et qui masquent les vrais.

La CI de la plateforme est `.github/workflows/vtlvs.yml`. Pour réactiver l'une de celles-ci,
il suffit de la remettre dans `.github/workflows/` — et de vérifier qu'elle parle bien de VTLVS.


## `vtlvs.yml` aussi (21/09/2026)

Il contrôlait — style, tests, types, build, audits — sans jamais rien déployer : les
Workers partent d'un poste vers Cloudflare, et Railway se déclenche sur `git push`.

Les Actions du compte étant bloquées pour facturation, il ne contrôlait plus rien non
plus. Et nous ne comptons pas revenir sur GitHub pour cela : la chaîne est désormais
`vigil-unified/scripts/deployer.sh`, qui joue les mêmes contrôles puis met en ligne dans
l'ordre des dépendances.

La protection des branches a suivi : les contrôles requis ont été retirés de `main`. Une
protection qu'aucune exécution ne peut satisfaire n'est pas une protection, c'est une
branche gelée. L'interdiction de forcer et de supprimer, elle, reste.

Le fichier est conservé : il redevient utile le jour où les Actions repartent.
