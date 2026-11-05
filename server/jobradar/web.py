"""Servidor HTTP sin dependencias: el panel (que también es la app) y la API que consulta la APK para avisar."""
import datetime as dt
import json
import logging
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, cv, gemini, planificador, puntuar, scan

log = logging.getLogger("jobradar")
STATIC = os.path.join(os.path.dirname(__file__), "static")
ESTADOS = {"nueva", "vista", "favorita", "aplicada", "descartada"}
VERSION = "1.0.0"
MAX_PDF = 6 * 1024 * 1024


def make_handler(db, cfg):
    class H(BaseHTTPRequestHandler):
        server_version = "JobRadar/" + VERSION

        def log_message(self, fmt, *a):
            log.debug("%s %s", self.address_string(), fmt % a)

        def _json(self, obj, code=200):
            b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)

        def _archivo(self, path, tipo, nombre=None, descargar=False):
            if not path or not os.path.exists(path):
                return self._json({"error": "no existe"}, 404)
            with open(path, "rb") as f:
                b = f.read()
            self.send_response(200)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            if nombre:
                disp = "attachment" if descargar else "inline"
                self.send_header("Content-Disposition", f"{disp}; filename=\"{nombre}\"")
            self.end_headers()
            self.wfile.write(b)

        def _auth(self, qs):
            tok = cfg.get("token") or ""
            if not tok:
                return True
            if (self.headers.get("X-Token") or (qs.get("token") or [""])[0]) == tok:
                return True
            self._json({"error": "token incorrecto"}, 401)
            return False

        def _crudo(self, limite):
            n = int(self.headers.get("Content-Length") or 0)
            if n > limite:
                raise ValueError("Archivo demasiado grande")
            return self.rfile.read(n) if n else b""

        def _body(self):
            try:
                return json.loads(self._crudo(1024 * 1024).decode("utf-8") or "{}")
            except ValueError:
                return {}

        # ---------------------------------------------------- GET
        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            q1 = lambda k, d=None: (qs.get(k) or [d])[0]  # noqa: E731
            if u.path in ("/", "/index.html"):
                return self._archivo(os.path.join(STATIC, "index.html"), "text/html; charset=utf-8")
            if not u.path.startswith("/api/"):
                return self._json({"error": "no encontrado"}, 404)
            if not self._auth(qs):
                return
            parts = u.path.strip("/").split("/")

            if u.path == "/api/ofertas":
                return self._json({"items": db.listar(nivel=q1("nivel"), estado=q1("estado"), q=q1("q"),
                                                      modalidad=q1("modalidad"), filtradas=q1("filtradas") == "1",
                                                      limite=int(q1("limite", 300)))})
            if len(parts) == 3 and parts[:2] == ["api", "ofertas"]:
                o = db.oferta(int(parts[2]))
                return self._json(o) if o else self._json({"error": "no existe"}, 404)
            if len(parts) == 4 and parts[:2] == ["api", "ofertas"] and parts[3] == "cv.pdf":
                o = db.oferta(int(parts[2]))
                if not o or not o.get("cv_archivo"):
                    return self._json({"error": "esta oferta aún no tiene CV"}, 404)
                return self._archivo(os.path.join(cfg["data_dir"], "cvs", o["cv_archivo"]), "application/pdf",
                                     o["cv_archivo"], q1("descargar") == "1")
            if u.path == "/api/nuevas":
                # la APK guarda el último id que notificó y pregunta por los siguientes que ya tengan su CV listo
                desde, desde_al = int(q1("desde", "0")), int(q1("desde_alerta", "-1"))
                tope = db.max_id(solo_listas=True)
                res = {"items": [], "max_id": tope, "alertas": [], "max_alerta": db.max_alerta()}
                if desde >= 0:
                    items = db.listar(nivel=",".join(cfg["notificar_niveles"]), desde_id=desde, solo_listas=True,
                                      solo_aviso=True, limite=50)
                    res["items"] = [i for i in items if i["id"] <= tope and i["estado"] != "descartada"]
                if desde_al >= 0:
                    res["alertas"] = db.alertas_desde(desde_al)
                return self._json(res)
            if u.path == "/api/estado":
                return self._json({"version": VERSION, "pasada": scan.estado, "pasadas": db.pasadas(8),
                                   "contadores": db.contar(), "frecuencia": planificador.describir(cfg),
                                   "proxima": planificador.proxima(cfg, _ultima(db)).timestamp(),
                                   "pasadas_al_dia": planificador.pasadas_al_dia(cfg),
                                   "alertas": db.alertas_recientes(72), "gemini": bool(cfg.get("gemini_api_key")),
                                   "cv": {i: bool(cv.base(cfg, i)) for i in cv.IDIOMAS}, "ahora": time.time()})
            if u.path == "/api/cv":
                return self._json(cv.info(cfg))
            if len(parts) == 3 and parts[:2] == ["api", "cv"] and parts[2] in ("base_es.pdf", "base_en.pdf"):
                return self._archivo(os.path.join(cfg["data_dir"], "cv", parts[2]), "application/pdf", parts[2])
            if len(parts) == 3 and parts[:2] == ["api", "cv"] and parts[2] in ("vista_es.pdf", "vista_en.pdf"):
                # el CV estructurado pintado con el generador, para comprobar que se ve bien
                idioma = parts[2][6:8]
                base = cv.base(cfg, idioma)
                if not base:
                    return self._json({"error": "no hay CV en ese idioma"}, 404)
                from . import pdfcv
                p = os.path.join(cfg["data_dir"], "cvs", f"_vista_{idioma}.pdf")
                pdfcv.generar(base, p)
                return self._archivo(p, "application/pdf", f"CV_base_{idioma}.pdf")
            if u.path == "/api/ajustes":
                return self._json(config.publico(cfg))
            if u.path == "/api/baremo":
                return self._json(baremo(cfg))
            return self._json({"error": "no encontrado"}, 404)

        # ---------------------------------------------------- POST
        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            if not self._auth(qs):
                return
            parts = u.path.strip("/").split("/")
            try:
                if u.path == "/api/pasada":
                    if scan.estado["en_curso"]:
                        return self._json({"ok": False, "mensaje": "Ya hay una pasada en curso"})
                    threading.Thread(target=scan.pasada, args=(db, cfg), daemon=True).start()
                    return self._json({"ok": True, "mensaje": "Pasada lanzada"})

                if len(parts) == 4 and parts[:2] == ["api", "ofertas"]:
                    oid = int(parts[2])
                    if not db.oferta(oid):
                        return self._json({"error": "no existe"}, 404)
                    if parts[3] == "estado":
                        est = self._body().get("estado")
                        if est not in ESTADOS:
                            return self._json({"error": "estado no válido"}, 400)
                        db.actualizar(oid, estado=est)
                        return self._json({"ok": True})
                    if parts[3] == "cv":
                        idioma = self._body().get("idioma") or None
                        nombre = cv.adaptar(db, cfg, oid, idioma)
                        return self._json({"ok": True, "archivo": nombre, "oferta": db.oferta(oid)})

                if len(parts) == 4 and parts[:2] == ["api", "cv"] and parts[2] in cv.IDIOMAS:
                    idioma = parts[2]
                    if parts[3] == "subir":
                        msg = cv.subir(cfg, idioma, self._crudo(MAX_PDF))
                        return self._json({"ok": True, "mensaje": msg, "cv": cv.info(cfg)})
                    if parts[3] == "json":
                        cv.guardar_json(cfg, idioma, self._body())
                        return self._json({"ok": True, "cv": cv.info(cfg)})

                if u.path == "/api/ajustes":
                    b = self._body()
                    if "gemini_api_key" in b and not (b["gemini_api_key"] or "").strip():
                        b.pop("gemini_api_key")  # vacío = no cambiar
                    if "frecuencia" in b or "horas_pasada" in b:
                        b["frecuencia"], b["horas_pasada"] = planificador.validar(
                            b.get("frecuencia") or planificador.frecuencia(cfg), b.get("horas_pasada", cfg["horas_pasada"]))
                    config.guardar_ajustes(cfg, b)
                    res = {"ok": True, "ajustes": config.publico(cfg), "frecuencia": planificador.describir(cfg),
                           "proxima": planificador.proxima(cfg, _ultima(db)).timestamp()}
                    if any(k in b for k in ("perfil", "excluir_titulo", "excluir_empresas")):
                        res["recalculo"] = puntuar.recalcular(db, cfg)  # sueldo, km o exclusiones cambian la nota
                    return self._json(res)
                if u.path == "/api/baremo":
                    b = self._body()
                    if b.get("restablecer"):
                        cambios = {"pesos": {}, "niveles": dict(puntuar.NIVELES_DEFECTO)}
                    else:
                        cambios = {"pesos": puntuar.validar_pesos(b.get("pesos") or {}),
                                   "niveles": puntuar.validar_niveles(b.get("niveles") or {})}
                    config.guardar_ajustes(cfg, cambios)
                    res = {"ok": True, "baremo": baremo(cfg)}
                    if b.get("recalcular", True):
                        res["recalculo"] = puntuar.recalcular(db, cfg)
                    return self._json(res)
                if u.path == "/api/gemini/probar":
                    txt = gemini.generar(cfg, "Responde solo con la palabra: funciona", temperature=0)
                    return self._json({"ok": True, "respuesta": txt[:60]})
            except (ValueError, gemini.GeminiError) as e:
                return self._json({"ok": False, "error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                log.exception("Error en %s", u.path)
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
            return self._json({"error": "no encontrado"}, 404)

    return H


def baremo(cfg):
    P = puntuar.pesos(cfg)
    return {"pesos": P, "defecto": puntuar.PESOS, "niveles": {**puntuar.NIVELES_DEFECTO, **(cfg.get("niveles") or {})},
            "niveles_defecto": puntuar.NIVELES_DEFECTO, "maximo": puntuar.maximo(P),
            "stack": [n for n, _, _ in puntuar.STACK], "zona_max_km": cfg["perfil"]["zona_max_km"],
            "anios": cfg["perfil"]["anios_experiencia"], "personalizado": bool(cfg.get("pesos"))}


def _ultima(db):
    t = db.ultima_pasada_inicio()
    return dt.datetime.fromtimestamp(t) if t else None


def programador(db, cfg):
    """Lanza las pasadas cuando toca según la frecuencia de ⚙ Ajustes (se relee en cada vuelta: los cambios
    se aplican al momento, sin reiniciar)."""
    time.sleep(30)  # que la red y Tailscale se levanten tras un reinicio
    while True:
        try:
            prox = planificador.proxima(cfg, _ultima(db))
            if prox <= dt.datetime.now() and not scan.estado["en_curso"]:
                log.info("Pasada programada (%s)", planificador.describir(cfg))
                scan.pasada(db, cfg)
        except Exception:  # noqa: BLE001 - que un fallo no pare las búsquedas para siempre
            log.exception("Error en el programador")
        time.sleep(30)


def servir(db, cfg):
    threading.Thread(target=programador, args=(db, cfg), daemon=True).start()
    srv = ThreadingHTTPServer((cfg["host"], int(cfg["puerto"])), make_handler(db, cfg))
    log.info("JobRadar %s escuchando en http://%s:%s", VERSION, cfg["host"], cfg["puerto"])
    srv.serve_forever()
