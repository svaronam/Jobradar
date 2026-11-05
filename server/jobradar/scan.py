"""Una pasada: busca en LinkedIn, abre solo las ofertas nuevas, las puntúa, guarda y prepara su CV."""
import logging
import threading
import time

from . import cv, linkedin, puntuar, util
from .util import Bloqueado, norm

log = logging.getLogger("jobradar")
estado = {"en_curso": False, "inicio": None, "fase": "", "hechas": 0, "total": 0, "ultimo": None}
_lock = threading.Lock()


def firma(titulo, empresa):
    return norm(titulo) + "|" + norm(empresa)


def _tpr(db):
    """Ventana de fechas para LinkedIn: desde la última pasada buena (+2 h de margen), entre 1 y 7 días."""
    ult = db.ultima_pasada_ok()
    if ult is None:
        return "r604800"
    segundos = int(time.time() - ult) + 7200
    return f"r{min(604800, max(86400, segundos))}"


def pasada(db, cfg, tpr=None):
    if not _lock.acquire(blocking=False):
        return None
    try:
        return _pasada(db, cfg, tpr)
    finally:
        estado["en_curso"] = False
        _lock.release()


def _pasada(db, cfg, tpr):
    primera = db.vacia()
    tpr = tpr or _tpr(db)
    res = {"inicio": time.time(), "peticiones": 0, "tarjetas": 0, "nuevas": 0, "filtradas": 0, "cvs": 0, "error": ""}
    busquedas = [(kw, m) for kw in cfg["palabras_clave"] for m in cfg["modos"]]
    estado.update(en_curso=True, inicio=res["inicio"], fase="Buscando", hechas=0, total=len(busquedas))
    log.info("Pasada (%s, %d búsquedas, primera=%s)", tpr, len(busquedas), primera)

    candidatas, vistos = [], set()
    try:
        for kw, modo in busquedas:
            start = 0
            for _ in range(int(modo.get("paginas", 1))):
                code, tarjetas = linkedin.buscar(kw, modo, start, tpr, cfg["data_dir"] + "/debug")
                start += len(tarjetas)
                res["peticiones"] += 1
                res["tarjetas"] += len(tarjetas)
                for t in tarjetas:
                    if t["job_id"] in vistos:
                        continue
                    vistos.add(t["job_id"])
                    t["modo"], t["busqueda"] = modo["nombre"], f"{kw} · {modo['nombre']} · {modo['location']}"
                    candidatas.append(t)
                util.pausa(cfg)
                if len(tarjetas) < linkedin.POR_PAGINA:
                    break
            estado["hechas"] += 1

        nuevas = [t for t in candidatas if not db.existe("li:" + t["job_id"])]
        estado.update(fase="Leyendo ofertas nuevas", hechas=0, total=len(nuevas))
        log.info("%d tarjetas, %d distintas, %d nuevas", res["tarjetas"], len(candidatas), len(nuevas))
        for t in nuevas:
            _procesar(db, cfg, t, primera, res)
            estado["hechas"] += 1
    except Bloqueado as e:
        res["error"] = f"LinkedIn ha limitado las peticiones ({e})"
        log.warning(res["error"])
        db.add_alerta(f"bloqueo:{time.strftime('%Y-%m-%d')}",
                      "LinkedIn está limitando las peticiones. La pasada se ha cortado; lo reintentaré en la siguiente. "
                      "Si se repite, quita palabras clave o pasadas al día.")
    except Exception as e:  # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {e}"
        log.exception("Error en la pasada")

    res["fin"] = time.time()
    db.add_pasada(res)
    _salud(db, res)
    estado.update(fase="Preparando CV", ultimo=res)
    res["cvs"] = cv.procesar_pendientes(db, cfg)
    estado.update(fase="", ultimo=res)
    log.info("Pasada terminada: %s", res)
    return res


def _procesar(db, cfg, t, primera, res):
    uid = "li:" + t["job_id"]
    base = {"uid": uid, "firma": firma(t["titulo"], t["empresa"]), "titulo": t["titulo"], "empresa": t["empresa"],
            "lugar": t["lugar"], "fecha_pub": t["fecha_pub"], "url": t["url"], "sueldo_txt": t["sueldo_txt"],
            "busqueda": t["busqueda"], "modalidad": t["modo"], "aviso": 0 if primera else 1}

    motivo = puntuar.prefiltro(t["titulo"], cfg)
    if not motivo and db.duplicada(base["firma"]):
        motivo = "Duplicada (misma oferta ya vista)"
    if motivo:
        db.guardar({**base, "nivel": "filtrada", "filtro": motivo, "score": 0, "listo": 1})
        res["filtradas"] += 1
        return

    d = linkedin.detalle(t["job_id"], cfg["data_dir"] + "/debug") or {}
    util.pausa(cfg)
    o = {**t, **{k: v for k, v in d.items() if v}}
    o["modo"] = t["modo"]
    p = puntuar.puntuar(o, cfg)
    necesita_cv = not p["filtro"] and p["score"] >= int(cfg.get("cv_desde_score", 55))
    fila = {**base, "titulo": o.get("titulo") or t["titulo"], "empresa": o.get("empresa") or t["empresa"],
            "lugar": o.get("lugar") or t["lugar"], "descripcion": o.get("descripcion", ""),
            "candidatos": d.get("candidatos"), "seniority": d.get("seniority"), "tipo_empleo": d.get("tipo_empleo"),
            "funcion": d.get("funcion"), "sectores": d.get("sectores"),
            "km": p["km"], "modalidad": p["modalidad"], "rol": p["rol"], "score": p["score"], "nivel": p["nivel"],
            "desglose": p["desglose"], "encaje": p["encaje"], "filtro": p["filtro"], "idioma": p["idioma"],
            "sueldo_txt": p["sueldo_txt"], "sueldo_min": p["sueldo_min"], "sueldo_max": p["sueldo_max"],
            "anios_pedidos": p["anios_pedidos"],
            "cv_estado": "pendiente" if necesita_cv else "",
            "listo": 0 if necesita_cv else 1}
    if db.guardar(fila):
        res["nuevas"] += 1
        if p["filtro"]:
            res["filtradas"] += 1


def _salud(db, res):
    """Alertas que la app notifica cuando algo huele mal."""
    hoy = time.strftime("%Y-%m-%d")
    if not res["error"] and res["peticiones"] and not res["tarjetas"]:
        db.add_alerta(f"vacia:{hoy}", "Una pasada entera sin ninguna oferta en LinkedIn. O no hay nada nuevo o LinkedIn "
                                      "ha cambiado su página: si se repite, pásame server/data/debug/lista_vacia.html.")
    if res["error"] and not res["error"].startswith("LinkedIn ha limitado"):
        db.add_alerta(f"error:{hoy}", f"La pasada ha fallado: {res['error'][:160]}")
