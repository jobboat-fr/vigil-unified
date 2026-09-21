#!/usr/bin/env bash
# Puits de journaux VTLVS sur le serveur OVH : Loki (stockage, 90 jours) + Grafana (lecture, alertes).
# Idempotent. À lancer en root : sudo bash installer.sh
#
#   Loki     127.0.0.1:3100  — réception via https://logs.vtlvs.com/loki/api/v1/push (authentification basique)
#   Grafana  127.0.0.1:3300  — https://grafana.vtlvs.com (compte admin, inscription fermée)
#
# Secrets générés une fois, lisibles par root seulement :
#   /etc/vtlvs/observabilite/loki-push.pass     mot de passe de l'utilisateur « vtlvs » pour pousser des journaux
#   /etc/vtlvs/observabilite/grafana-admin.pass mot de passe admin de Grafana
set -euo pipefail
ICI="$(cd "$(dirname "$0")" && pwd)"
SECRETS=/etc/vtlvs/observabilite
install -d -m 700 "$SECRETS"

# ── Paquets (dépôt officiel Grafana : loki et grafana) ──────────────────────
if [ ! -f /etc/yum.repos.d/grafana.repo ]; then
  cat > /etc/yum.repos.d/grafana.repo <<'REPO'
[grafana]
name=grafana
baseurl=https://rpm.grafana.com
repo_gpgcheck=1
enabled=1
gpgcheck=1
gpgkey=https://rpm.grafana.com/gpg.key
sslverify=1
sslcacert=/etc/pki/tls/certs/ca-bundle.crt
REPO
fi
rpm -q loki grafana >/dev/null 2>&1 || dnf install -y loki grafana

# ── Loki ────────────────────────────────────────────────────────────────────
install -d -o loki -g loki -m 750 /var/lib/loki
install -m 644 "$ICI/loki.yaml" /etc/loki/config.yml
systemctl enable --now loki
systemctl restart loki

# ── Grafana ─────────────────────────────────────────────────────────────────
[ -s "$SECRETS/grafana-admin.pass" ] || (umask 077; openssl rand -base64 24 | tr -d '\n' > "$SECRETS/grafana-admin.pass")
install -m 640 -g grafana "$ICI/grafana.ini" /etc/grafana/grafana.ini
install -d -m 755 /etc/grafana/provisioning/datasources /etc/grafana/provisioning/dashboards /etc/grafana/provisioning/alerting /var/lib/grafana/dashboards
install -m 644 "$ICI/grafana-datasource.yaml" /etc/grafana/provisioning/datasources/loki.yaml
install -m 644 "$ICI/grafana-dashboards.yaml" /etc/grafana/provisioning/dashboards/vtlvs.yaml
install -m 644 "$ICI/tableau-vtlvs.json" /var/lib/grafana/dashboards/vtlvs.json
install -m 644 "$ICI/alertes.yaml" /etc/grafana/provisioning/alerting/vtlvs.yaml
# Le point de contact et la politique de notification. Sans ce fichier, les quatre règles
# se declenchent et ne previennent personne — ce qui a ete le cas jusqu'au 21/09.
envsubst < "$ICI/contacts.yaml" > /etc/grafana/provisioning/alerting/contacts.yaml
chmod 644 /etc/grafana/provisioning/alerting/contacts.yaml
chown -R grafana:grafana /var/lib/grafana/dashboards
# Le mot de passe admin n'est écrit que par variable d'environnement de l'unité, jamais dans grafana.ini.
install -d /etc/systemd/system/grafana-server.service.d
cat > /etc/systemd/system/grafana-server.service.d/vtlvs.conf <<UNIT
[Service]
Environment=GF_SECURITY_ADMIN_PASSWORD=$(cat "$SECRETS/grafana-admin.pass")
UNIT
chmod 600 /etc/systemd/system/grafana-server.service.d/vtlvs.conf
systemctl daemon-reload
systemctl enable --now grafana-server
systemctl restart grafana-server

# ── Accès à la réception des journaux ───────────────────────────────────────
[ -s "$SECRETS/loki-push.pass" ] || (umask 077; openssl rand -base64 30 | tr -d '\n/+=' > "$SECRETS/loki-push.pass")
HASH=$(caddy hash-password --plaintext "$(cat "$SECRETS/loki-push.pass")")
install -d -m 750 -o root -g caddy /etc/caddy/vtlvs
cat > /etc/caddy/vtlvs/observabilite.caddy <<CADDY
logs.vtlvs.com {
	@push path /loki/api/v1/push
	handle @push {
		basicauth {
			vtlvs ${HASH}
		}
		reverse_proxy 127.0.0.1:3100
	}
	handle /ready {
		reverse_proxy 127.0.0.1:3100
	}
	handle {
		respond "Réception des journaux VTLVS." 404
	}
}

grafana.vtlvs.com {
	reverse_proxy 127.0.0.1:3300
}
CADDY
chmod 640 /etc/caddy/vtlvs/observabilite.caddy; chgrp caddy /etc/caddy/vtlvs/observabilite.caddy
grep -q "import /etc/caddy/vtlvs/\*.caddy" /etc/caddy/Caddyfile || printf '\nimport /etc/caddy/vtlvs/*.caddy\n' >> /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl reload caddy

sleep 5
echo "loki: $(curl -s -m 5 http://127.0.0.1:3100/ready)"
echo "grafana: $(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:3300/api/health)"
