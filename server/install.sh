#!/usr/bin/env bash
# Instala JobRadar como servicio en la Raspberry (Raspberry Pi OS Lite). Ejecutar desde la carpeta server/:
#   bash install.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
USUARIO="$(whoami)"

echo "== JobRadar en $DIR (usuario $USUARIO)"
sudo apt-get update -qq
# bs4: leer el HTML de LinkedIn · reportlab: generar los PDF · poppler-utils: leer el PDF que subes
# fonts-sil-charis: la letra de tu CV (Charter); si no está se usa Times
sudo apt-get install -y -qq python3 python3-bs4 python3-reportlab poppler-utils sqlite3 fonts-sil-charis || \
  sudo apt-get install -y -qq python3 python3-bs4 python3-reportlab poppler-utils sqlite3

[ -f "$DIR/config.json" ] || cp "$DIR/config.example.json" "$DIR/config.json"
mkdir -p "$DIR/data/cv" "$DIR/data/cvs" "$DIR/data/debug"
chmod 700 "$DIR/data"

sudo tee /etc/systemd/system/jobradar.service >/dev/null <<EOF
[Unit]
Description=JobRadar - ofertas de LinkedIn puntuadas y CV adaptado
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=$USUARIO
WorkingDirectory=$DIR
ExecStart=/usr/bin/python3 $DIR/run.py servir
Restart=always
RestartSec=15
Environment=PYTHONUNBUFFERED=1
Environment=TZ=Europe/Madrid
# la Pi 3 tiene 1 GB: que no se coma la RAM de los demás bots
MemoryMax=300M

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now jobradar
sleep 2
systemctl --no-pager --lines=5 status jobradar || true

# Enlazarlo en Pi Monitor (si el agente está instalado en esta Pi)
if [ -f /etc/pi-agent/config.json ]; then
  sudo python3 - <<'PY'
import json, os
p = "/etc/pi-agent/config.json"
st = os.stat(p)
cfg = json.load(open(p))
bots = cfg.setdefault("bots", [])
if not any(b.get("unit") == "jobradar.service" for b in bots):
    bots.append({"managed": False, "autorestart": True, "max_restarts": 3, "hang_after": 15,
                 "unit": "jobradar.service", "name": "jobradar", "cat": "otros"})
    tmp = p + ".tmp"
    json.dump(cfg, open(tmp, "w"), indent=2, ensure_ascii=False)
    os.chmod(tmp, 0o600); os.chown(tmp, st.st_uid, st.st_gid); os.replace(tmp, p)
    print("  Enlazado en Pi Monitor")
PY
  sudo systemctl restart pi-agent 2>/dev/null || true
fi

IP_TS="$(tailscale ip -4 2>/dev/null | head -1 || true)"
echo
echo "== Listo. Abre en el móvil (con Tailscale activo):"
echo "   http://$(hostname):8796     ó   http://${IP_TS:-<ip-tailscale>}:8796"
echo "== Antes de nada, comprueba que lee LinkedIn:   python3 $DIR/run.py probar"
echo "== Logs: journalctl -u jobradar -f    ó   tail -f $DIR/data/jobradar.log"
