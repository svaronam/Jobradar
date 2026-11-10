"""Visitas al portfolio, sin servicios de terceros.

La web (GitHub Pages) manda un aviso pequeño a la Pi en cada página que se abre. La Pi lo recibe por un servidor
aparte que solo entiende /v (el panel no queda expuesto) y que se publica en internet con Tailscale Funnel.
Cada visita nueva genera una alerta que la APK enseña como notificación.

Qué se guarda: hora, páginas vistas, de dónde viene (LinkedIn, Google, el CV de una oferta...), idioma y zona
horaria del navegador, tipo de dispositivo y cuánto tiempo se queda. La IP no se guarda: solo un resumen cifrado
que cambia cada día (para saber si es la misma persona que vuelve hoy) y para comprobar la lista de IPs ignoradas.
"""
import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("jobradar")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS visitas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sesion TEXT UNIQUE,                -- aleatorio por pestaña (sessionStorage del navegador)
  inicio REAL, ultimo REAL, segundos INTEGER DEFAULT 0,
  paginas TEXT,                      -- JSON: rutas vistas en orden
  origen TEXT, ref TEXT,             -- origen legible (LinkedIn, Google, CV · Empresa...) y referrer en crudo
  oferta_id INTEGER,                 -- si llega desde el enlace de un CV adaptado
  idioma TEXT, zona TEXT, dispositivo TEXT, navegador TEXT, pantalla TEXT,
  red TEXT,                          -- hash diario de la IP: misma red el mismo día
  avisada INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_vis_inicio ON visitas(inicio);
"""

RX_BOT = re.compile(r"bot|crawl|spider|slurp|headless|lighthouse|preview|facebookexternalhit|embedly|python|curl|wget"
                    r"|phantom|selenium|puppeteer|playwright", re.I)
ORIGENES = [  # (regex sobre el referrer, nombre)
    (r"linkedin\.|lnkd\.in|com\.linkedin\.android", "LinkedIn"),
    (r"google\.|com\.google\.android", "Google"),
    (r"bing\.com", "Bing"), (r"duckduckgo\.", "DuckDuckGo"),
    (r"github\.com", "GitHub"),
    (r"infojobs\.", "InfoJobs"), (r"tecnoempleo\.", "Tecnoempleo"), (r"indeed\.", "Indeed"),
    (r"jobgether\.", "Jobgether"), (r"glassdoor\.", "Glassdoor"),
    (r"mail\.|outlook\.|gmail", "Correo"),
    (r"t\.co$|twitter\.|x\.com", "X/Twitter"), (r"whatsapp|wa\.me", "WhatsApp"), (r"t\.me|telegram", "Telegram"),
]
# valores de ?r= que se pueden poner a mano en un enlace (svaronam.github.io/portfolio/?r=li)
ETIQUETAS_R = {"cv": "CV", "li": "LinkedIn (perfil)", "gh": "GitHub", "mail": "Correo", "carta": "Carta de presentación"}
MAX_CUERPO = 2048
LIMITE_IP = (40, 600)       # como mucho 40 avisos por red cada 10 min
MAX_AVISOS_DIA = 40         # notificaciones al móvil por día, por si alguien abusa del endpoint


def preparar(db):
    with db._c() as c:
        c.executescript(ESQUEMA)


def cfg_vis(cfg):
    return {"activo": True, "puerto": 8797, "notificar": True, "ignorar_ips": [], "sitio": "",
            "origenes": ["https://svaronam.github.io"], **(cfg.get("visitas") or {})}


def _sal(cfg):
    """Sal secreta para el hash de la IP (se crea una vez y no sale de la Pi)."""
    p = os.path.join(cfg["data_dir"], "visitas_sal")
    if not os.path.exists(p):
        with open(p, "w") as f:
            f.write(secrets.token_hex(16))
        os.chmod(p, 0o600)
    with open(p) as f:
        return f.read().strip()


def hash_red(cfg, ip, dia=None):
    dia = dia or time.strftime("%Y-%m-%d")
    return hashlib.sha256(f"{_sal(cfg)}|{dia}|{ip}".encode()).hexdigest()[:12]


def ignorada(ip, lista):
    if not ip:
        return False
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for x in lista or []:
        try:
            if a in ipaddress.ip_network(str(x).strip(), strict=False):
                return True
        except ValueError:
            continue
    return False


def origen(ref, r, oferta=None):
    """Nombre legible de por dónde ha llegado."""
    if oferta:
        return f"CV enviado a {oferta.get('empresa') or 'una oferta'}"
    if r:
        r = str(r)[:20].lower()
        return ETIQUETAS_R.get(r, f"enlace «{r}»")
    if not ref:
        return "Directo (enlace pegado, PDF o app)"
    host = urllib.parse.urlparse(ref).netloc.lower() or ref.lower()
    if "svaronam.github.io" in host:
        return "Directo (enlace pegado, PDF o app)"
    for rx, nombre in ORIGENES:
        if re.search(rx, host):
            return nombre
    return host[:60]


def dispositivo(ua):
    ua = ua or ""
    if re.search(r"iPad|Tablet", ua):
        tipo = "tablet"
    elif re.search(r"Mobi|Android|iPhone", ua):
        tipo = "móvil"
    else:
        tipo = "ordenador"
    so = next((n for rx, n in [(r"Windows", "Windows"), (r"Android", "Android"), (r"iPhone|iPad|iOS", "iOS"),
                               (r"Mac OS", "macOS"), (r"CrOS", "ChromeOS"), (r"Linux", "Linux")] if re.search(rx, ua)), "")
    nav = next((n for rx, n in [(r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"SamsungBrowser", "Samsung"),
                                (r"LinkedInApp|com\.linkedin", "app de LinkedIn"), (r"Firefox/", "Firefox"),
                                (r"Chrome/", "Chrome"), (r"Safari/", "Safari")] if re.search(rx, ua)), "")
    return tipo, " · ".join(x for x in (so, nav) if x)


ZONAS = {"Europe/Madrid": "España", "Atlantic/Canary": "Canarias", "Africa/Ceuta": "España", "Europe/Lisbon": "Portugal",
         "Europe/London": "Reino Unido", "Europe/Dublin": "Irlanda", "Europe/Paris": "Francia", "Europe/Berlin": "Alemania",
         "Europe/Amsterdam": "Países Bajos", "Europe/Brussels": "Bélgica", "Europe/Rome": "Italia",
         "Europe/Zurich": "Suiza", "Europe/Warsaw": "Polonia", "Europe/Prague": "Chequia", "Europe/Belgrade": "Serbia",
         "Asia/Nicosia": "Chipre", "Asia/Famagusta": "Chipre", "Europe/Stockholm": "Suecia",
         "America/New_York": "EE. UU. (este)", "America/Chicago": "EE. UU. (centro)", "America/Los_Angeles": "EE. UU. (oeste)",
         "America/Mexico_City": "México", "America/Bogota": "Colombia", "America/Argentina/Buenos_Aires": "Argentina",
         "Asia/Kolkata": "India"}


def lugar(zona, idioma):
    """No hay geolocalización por IP (haría falta un servicio externo): se usa la zona horaria del navegador."""
    z = ZONAS.get(zona or "")
    if not z and zona:
        z = zona.split("/")[-1].replace("_", " ")
    return z or (idioma or "")


class Registro:
    def __init__(self, db, cfg):
        self.db, self.cfg = db, cfg
        self.lock = threading.Lock()
        self.por_ip = {}
        preparar(db)

    def _limite(self, red):
        ahora = time.time()
        with self.lock:
            v = [t for t in self.por_ip.get(red, []) if ahora - t < LIMITE_IP[1]]
            if len(v) >= LIMITE_IP[0]:
                self.por_ip[red] = v
                return True
            v.append(ahora)
            self.por_ip[red] = v
            if len(self.por_ip) > 5000:
                self.por_ip = {k: x for k, x in self.por_ip.items() if x and ahora - x[-1] < LIMITE_IP[1]}
        return False

    def recibir(self, d, ip, ua):
        """Un aviso de la web: e = "ver" (página abierta) o "fin" (se va; trae los segundos). Devuelve motivo si se ignora."""
        cv = cfg_vis(self.cfg)
        if not cv["activo"]:
            return "desactivado"
        if RX_BOT.search(ua or "") or not ua:
            return "bot"
        if ignorada(ip, cv["ignorar_ips"]):
            return "ip ignorada"
        sesion = re.sub(r"[^a-zA-Z0-9]", "", str(d.get("s") or ""))[:32]
        if len(sesion) < 8:
            return "sin sesión"
        red = hash_red(self.cfg, ip or "?")
        if self._limite(red):
            return "demasiadas"
        ahora = time.time()
        pagina = str(d.get("p") or "/")[:120]
        if d.get("e") == "fin":
            seg = max(0, min(4 * 3600, int(float(d.get("t") or 0))))
            with self.db.lock, self.db._c() as c:
                c.execute("UPDATE visitas SET segundos=MAX(segundos, ?), ultimo=? WHERE sesion=?", (seg, ahora, sesion))
            return None
        with self.db.lock, self.db._c() as c:
            r = c.execute("SELECT id, paginas FROM visitas WHERE sesion=?", (sesion,)).fetchone()
            if r:  # otra página de la misma visita
                pags = json.loads(r["paginas"] or "[]")
                if not pags or pags[-1] != pagina:
                    pags = (pags + [pagina])[-30:]
                c.execute("UPDATE visitas SET paginas=?, ultimo=? WHERE id=?", (json.dumps(pags, ensure_ascii=False),
                                                                                 ahora, r["id"]))
                return None
        oferta = None
        m = re.fullmatch(r"\d{1,9}", str(d.get("cv") or ""))
        if m:
            oferta = self.db.oferta(int(m.group(0)))
        ref = str(d.get("ref") or "")[:300]
        if not ref and re.search(r"LinkedInApp|com\.linkedin", ua):
            ref = "linkedin.com"  # el navegador de la app de LinkedIn no siempre manda el referrer
        tipo, nav = dispositivo(ua)
        fila = {"sesion": sesion, "inicio": ahora, "ultimo": ahora, "paginas": json.dumps([pagina], ensure_ascii=False),
                "origen": origen(ref, d.get("r") or ("cv" if m else None), oferta), "ref": ref, "oferta_id": oferta["id"] if oferta else None,
                "idioma": str(d.get("l") or "")[:20], "zona": str(d.get("z") or "")[:40], "dispositivo": tipo,
                "navegador": nav[:60], "pantalla": str(d.get("w") or "")[:12], "red": red}
        with self.db.lock, self.db._c() as c:
            antes = c.execute("SELECT COUNT(*) n FROM visitas WHERE red=? AND inicio>?",
                              (red, ahora - 86400)).fetchone()["n"]
            vid = c.execute(f"INSERT OR IGNORE INTO visitas ({', '.join(fila)}) VALUES ({', '.join('?' * len(fila))})",
                            list(fila.values())).lastrowid
        if vid and cv["notificar"]:
            self._avisar(vid, fila, oferta, antes)
        return None

    def _avisar(self, vid, f, oferta, antes):
        hoy = time.strftime("%Y-%m-%d")
        with self.db._c() as c:
            n = c.execute("SELECT COUNT(*) n FROM alertas WHERE tipo='visita' AND clave LIKE ?", (f"visita:{hoy}:%",)).fetchone()["n"]
        if n >= MAX_AVISOS_DIA:
            return
        donde = lugar(f["zona"], f["idioma"])
        pag = json.loads(f["paginas"])[0]
        texto = " · ".join(x for x in (f["origen"], donde, f["dispositivo"]) if x)
        datos = {"visita": vid, "origen": f["origen"], "lugar": donde, "dispositivo": f["dispositivo"],
                 "navegador": f["navegador"], "pagina": pag, "vuelve": antes, "oferta_id": f["oferta_id"],
                 "oferta": (f"{oferta.get('titulo')} · {oferta.get('empresa')}" if oferta else None)}
        self.db.add_alerta(f"visita:{hoy}:{vid}", texto, tipo="visita", oferta_id=f["oferta_id"], datos=datos)
        log.info("Visita al portfolio: %s", texto)


# ------------------------------------------------------------------ consultas para el panel
def _fila(r):
    d = dict(r)
    d["paginas"] = json.loads(d.get("paginas") or "[]")
    d["lugar"] = lugar(d.get("zona"), d.get("idioma"))
    d.pop("red", None)
    return d


def listar(db, limite=100):
    with db._c() as c:
        filas = [_fila(r) for r in c.execute("SELECT * FROM visitas ORDER BY id DESC LIMIT ?", (limite,))]
    ofertas = {}
    for f in filas:
        if f.get("oferta_id"):
            o = ofertas.setdefault(f["oferta_id"], db.oferta(f["oferta_id"]))
            f["oferta"] = {"id": o["id"], "titulo": o["titulo"], "empresa": o["empresa"]} if o else None
    return filas


def resumen(db):
    ahora = time.time()
    with db._c() as c:
        cuenta = lambda seg: c.execute("SELECT COUNT(*) n FROM visitas WHERE inicio>?", (ahora - seg,)).fetchone()["n"]  # noqa: E731
        orig = [dict(r) for r in c.execute("SELECT origen, COUNT(*) n FROM visitas WHERE inicio>? GROUP BY origen "
                                           "ORDER BY n DESC LIMIT 8", (ahora - 30 * 86400,))]
        total = c.execute("SELECT COUNT(*) n FROM visitas").fetchone()["n"]
        return {"hoy": cuenta(86400), "semana": cuenta(7 * 86400), "mes": cuenta(30 * 86400), "total": total,
                "origenes_mes": orig}


def borrar(db, vid=None):
    with db.lock, db._c() as c:
        if vid:
            c.execute("DELETE FROM visitas WHERE id=?", (vid,))
        else:
            c.execute("DELETE FROM visitas")


# ------------------------------------------------------------------ servidor público (solo /v)
def _handler(reg, cfg):
    class V(BaseHTTPRequestHandler):
        server_version = "v"
        sys_version = ""

        def log_message(self, fmt, *a):
            pass

        def _cors(self):
            o = self.headers.get("Origin") or ""
            permitidos = cfg_vis(cfg)["origenes"]
            if o and (o in permitidos or "*" in permitidos):
                self.send_header("Access-Control-Allow-Origin", o)
                self.send_header("Vary", "Origin")

        def _fin(self, code=204):
            self.send_response(code)
            self._cors()
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "86400")
            self.end_headers()

        def do_GET(self):
            self._fin(404)

        def do_POST(self):
            if urllib.parse.urlparse(self.path).path != "/v":
                return self._fin(404)
            o = self.headers.get("Origin") or ""
            permitidos = cfg_vis(cfg)["origenes"]
            if o and o not in permitidos and "*" not in permitidos:
                return self._fin(403)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n <= 0 or n > MAX_CUERPO:
                    return self._fin(413)
                d = json.loads(self.rfile.read(n).decode("utf-8"))
                if not isinstance(d, dict):
                    return self._fin(400)
            except (ValueError, UnicodeDecodeError):
                return self._fin(400)
            # Tailscale Funnel pasa la IP real en X-Forwarded-For; si no, la del socket
            ip = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or self.client_address[0]
            try:
                motivo = reg.recibir(d, ip, self.headers.get("User-Agent") or "")
                if motivo:
                    log.debug("Visita ignorada (%s)", motivo)
            except Exception:  # noqa: BLE001
                log.exception("Error guardando una visita")
            self._fin(204)
    return V


def servir(db, cfg):
    """Arranca el receptor en 127.0.0.1 (Tailscale Funnel lo publica). Devuelve el Registro."""
    cv = cfg_vis(cfg)
    reg = Registro(db, cfg)
    if not cv["activo"]:
        return reg
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", int(cv["puerto"])), _handler(reg, cfg))
    except OSError as e:
        log.error("No se pudo abrir el receptor de visitas en el puerto %s: %s", cv["puerto"], e)
        return reg
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("Visitas al portfolio: escuchando en http://127.0.0.1:%s/v", cv["puerto"])
    return reg
