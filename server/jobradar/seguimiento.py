"""Tareas diarias que no son buscar: el resumen del día y los recordatorios de candidaturas sin respuesta.
Las dos llegan al móvil como alertas con tipo ("resumen" / "seguimiento") por el mismo canal que el resto."""
import datetime as dt
import logging
import time

from .db import FASES_ACTIVAS

log = logging.getLogger("jobradar")
_ultima_revision = {"seguimiento": 0.0}

DEFECTO_RESUMEN = {"activo": True, "hora": "20:00", "n": 3}
TEXTOS = {
    "aplicada": "Hace {d} días que aplicaste a «{titulo}» en {empresa} y no hay novedades. Buen momento para escribir al recruiter.",
    "entrevista": "Hace {d} días de la entrevista en {empresa} («{titulo}»). Pregunta por los siguientes pasos.",
    "prueba": "Hace {d} días de la prueba técnica en {empresa} («{titulo}»). Pregunta qué tal fue.",
}


def resumen_cfg(cfg):
    return {**DEFECTO_RESUMEN, **(cfg.get("resumen") or {})}


def validar_resumen(r):
    import re
    r = {**DEFECTO_RESUMEN, **(r or {})}
    if not re.fullmatch(r"\d{1,2}:\d{2}", str(r["hora"])) or int(r["hora"].split(":")[0]) > 23 or int(r["hora"].split(":")[1]) > 59:
        raise ValueError("Hora del resumen no válida (HH:MM)")
    n = int(r["n"])
    if not 1 <= n <= 10:
        raise ValueError("El resumen lleva entre 1 y 10 ofertas")
    h, m = r["hora"].split(":")
    return {"activo": bool(r["activo"]), "hora": f"{int(h):02d}:{int(m):02d}", "n": n}


def resumen_del_dia(db, cfg, ahora=None, forzar=False):
    """A la hora elegida, las N mejores ofertas de las últimas 24 h que aún no has abierto. Una vez al día."""
    r = resumen_cfg(cfg)
    ahora = ahora or dt.datetime.now()
    if not r["activo"] and not forzar:
        return False
    h, m = map(int, r["hora"].split(":"))
    inicio = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
    if not forzar and not (inicio <= ahora < inicio + dt.timedelta(hours=3)):
        return False
    clave = f"resumen:{ahora.date().isoformat()}"
    ofertas = db.mejores_sin_abrir(time.time() - 86400, r["n"], cfg.get("notificar_niveles") or ["prioritaria"])
    if not ofertas:
        return False
    n = len(ofertas)
    texto = (f"{'La mejor oferta' if n == 1 else f'Las {n} mejores ofertas'} de hoy que aún no has abierto: "
             + " · ".join(f"{o['score']} {o['titulo']} ({o['empresa']})" for o in ofertas))
    if db.add_alerta(clave if not forzar else f"{clave}:{time.time()}", texto, tipo="resumen", datos=ofertas):
        log.info("Resumen del día: %d ofertas", n)
        return True
    return False


def recordatorios(db, cfg, ahora=None):
    """Candidaturas sin movimiento en X días: un aviso por cada una (se repite si sigues sin apuntar nada)."""
    dias = int(cfg.get("seguimiento_dias", 7) or 0)
    ahora = ahora or dt.datetime.now()
    if not dias or not 9 <= ahora.hour < 21:  # nada de avisos de noche
        return 0
    nuevos = 0
    for o in db.sin_respuesta(dias):
        if o["fase"] not in FASES_ACTIVAS:
            continue
        d = int((time.time() - o["ultimo_ts"]) // 86400)
        texto = TEXTOS[o["fase"]].format(d=d, titulo=o["titulo"] or "la oferta", empresa=o["empresa"] or "la empresa")
        if db.add_alerta(f"seguimiento:{o['id']}:{o['ultimo_ev']}", texto, tipo="seguimiento", oferta_id=o["id"]):
            nuevos += 1
    if nuevos:
        log.info("Recordatorios de candidaturas: %d", nuevos)
    return nuevos


def tareas(db, cfg):
    """Se llama en cada vuelta del programador; los recordatorios se miran como mucho una vez por hora."""
    resumen_del_dia(db, cfg)
    if time.time() - _ultima_revision["seguimiento"] >= 3600:
        _ultima_revision["seguimiento"] = time.time()
        recordatorios(db, cfg)
