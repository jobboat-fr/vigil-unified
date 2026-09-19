# Workflows hérités de Hermes — désactivés

Ce dossier n'est pas `.github/workflows` : GitHub n'y exécute rien.

Ces automatisations viennent du projet Hermes dont VTLVS est issu (publication PyPI, image
Docker, site de documentation, index des compétences, vérifications de contribution…). Elles ne
correspondent ni à nos dépôts ni à nos déploiements : les laisser actives, c'était entretenir des
contrôles qui ne protègent rien et qui masquent les vrais.

La CI de la plateforme est `.github/workflows/vtlvs.yml`. Pour réactiver l'une de celles-ci,
il suffit de la remettre dans `.github/workflows/` — et de vérifier qu'elle parle bien de VTLVS.
