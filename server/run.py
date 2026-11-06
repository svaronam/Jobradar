#!/usr/bin/env python3
"""JobRadar — busca en LinkedIn ofertas que encajan contigo, las puntúa y te adapta el CV a cada una.

  python3 run.py servir                    web/API + pasadas programadas (lo que usa systemd)
  python3 run.py pasada [--semana]         pasada manual (--semana: ofertas de los últimos 7 días)
  python3 run.py probar ["palabras"]       enseña lo que ve en LinkedIn y cómo lo puntuaría, sin guardar nada
  python3 run.py probar --rapida           lo mismo con la búsqueda del barrido rápido (palabras con OR)
  python3 run.py cv <id_oferta>            vuelve a generar el CV adaptado de una oferta
  python3 run.py modalidades               cómo ha clasificado cada oferta (remoto, híbrido...) y por qué, sin pedir nada
  python3 run.py logos                     pone el logo a las ofertas guardadas que no lo tienen
  python3 run.py demo                      mete ofertas de ejemplo para ver la web/app sin esperar
"""
import argparse
import logging
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from jobradar import config, cv, linkedin, puntuar, scan, util, web  # noqa: E402
from jobradar.db import DB  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="JobRadar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("servir")
    p = sub.add_parser("pasada")
    p.add_argument("--semana", action="store_true")
    pr = sub.add_parser("probar")
    pr.add_argument("palabras", nargs="?", default=None)
    pr.add_argument("--detalle", type=int, default=3, help="cuántas ofertas abrir para ver la descripción")
    pr.add_argument("--rapida", action="store_true", help="prueba el barrido rápido (todas las palabras con OR)")
    c = sub.add_parser("cv")
    c.add_argument("id", type=int)
    sub.add_parser("demo")
    sub.add_parser("logos")
    sub.add_parser("modalidades")
    a = ap.parse_args()

    cfg = config.cargar(BASE)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(os.path.join(cfg["data_dir"], "jobradar.log"), encoding="utf-8")])
    db = DB(os.path.join(cfg["data_dir"], "jobradar.db"))

    if a.cmd == "servir":
        web.servir(db, cfg)
    elif a.cmd == "pasada":
        print(scan.pasada(db, cfg, "r604800" if a.semana else None) or "Ya había una pasada en curso")
    elif a.cmd == "probar":
        probar(cfg, scan.palabras_or(cfg["palabras_clave"]) if a.rapida else a.palabras, a.detalle)
    elif a.cmd == "cv":
        print(cv.adaptar(db, cfg, a.id))
    elif a.cmd == "demo":
        demo(db, cfg)
    elif a.cmd == "modalidades":
        modalidades(db, cfg)
    elif a.cmd == "logos":
        n = scan.completar_logos(db, cfg, limite=500, salida=print)
        print(f"\n{n} ofertas con logo. Si salen todas sin logo, pásame data/debug/detalle_sin_logo.html")


def probar(cfg, palabras, n_detalle):
    """Lee LinkedIn sin guardar nada. Es la prueba de que el lector sigue funcionando."""
    palabras = palabras or cfg["palabras_clave"][0]
    resumen = []
    abiertas = 0
    for modo in cfg["modos"]:
        print(f"\n===== «{palabras}» · {modo['nombre']} · {modo['location']} =====")
        try:
            code, tarjetas = linkedin.buscar(palabras, modo, 0, "r604800", cfg["data_dir"] + "/debug")
        except util.Bloqueado as e:
            print(f"  BLOQUEADO por LinkedIn ({e}). Espera un rato antes de volver a probar.")
            return
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR: {type(e).__name__}: {e}")
            resumen.append((modo, "ERROR", 0))
            continue
        print(f"  HTTP {code} · {len(tarjetas)} ofertas")
        for t in tarjetas[:25]:
            pre = puntuar.prefiltro(t["titulo"], cfg)
            print(f"  {'·' if pre else ' '} {t['titulo'][:50]:50} {t['empresa'][:22]:22} {t['lugar'][:24]:24} "
                  f"{(t.get('tipo_lugar') or '-')[:10]:10} {t['fecha_pub']}"
                  + (f"  [{pre}]" if pre else ""))
        for t in [t for t in tarjetas if not puntuar.prefiltro(t["titulo"], cfg)][:max(0, n_detalle - abiertas)]:
            util.pausa(cfg)
            d = linkedin.detalle(t["job_id"], cfg["data_dir"] + "/debug", muestra="probar_" + modo["nombre"]) or {}
            abiertas += 1
            o = {**t, **{k: v for k, v in d.items() if v}, "modo": modo["nombre"]}
            p = puntuar.puntuar(o, cfg)
            print(f"\n  --> {p['score']} {p['nivel'].upper()} · {o.get('titulo')} · {o.get('empresa')}"
                  f"{' · FILTRADA: ' + p['filtro'] if p['filtro'] else ''}")
            print(f"      ETIQUETA DE LINKEDIN: {o.get('tipo_lugar') or 'no viene'}  ->  modalidad: {p['modalidad']}")
            print(f"      descripción: {len(d.get('descripcion', ''))} caracteres · nivel: {d.get('seniority') or '?'} · "
                  f"tipo: {d.get('tipo_empleo') or '?'} · candidatos: {d.get('candidatos')} · idioma: {p['idioma']}")
            for concepto, pts in p["desglose"]:
                print(f"      {pts:+4}  {concepto}")
            if p["encaje"]["falta"]:
                print(f"      pide y no está en tu CV: {', '.join(p['encaje']['falta'])}")
        resumen.append((modo, "OK", len(tarjetas)))
        util.pausa(cfg)
    print("\n===== RESUMEN =====")
    for modo, est, n in resumen:
        aviso = "   <-- 0: o no hay ofertas o el lector falla (mira data/debug/)" if est == "OK" and n == 0 else ""
        print(f"  {modo['nombre']:10} {modo['location'][:30]:30} {est:5} {n:3} ofertas{aviso}")


def modalidades(db, cfg):
    """Lee la etiqueta de LinkedIn de las guardadas que no la tienen, repuntúa y enseña qué es cada una y por qué."""
    if cfg.get("leer_etiqueta_linkedin"):
        print("Leyendo la etiqueta de modalidad de LinkedIn en las ofertas guardadas…")
        print(scan.completar_tipos(db, cfg, limite=200, salida=print))
    print("Repuntuando:", puntuar.recalcular(db, cfg))
    filas = [o for o in db.para_recalcular() if o.get("descripcion")]
    cuenta = {}
    for o in sorted(filas, key=lambda x: (x["modalidad"] or "", -x["score"])):
        m, motivo = puntuar.detectar_modalidad("remoto", o["descripcion"], o["titulo"], o.get("tipo_lugar") or "",
                                               o.get("modalidad_manual") or "")
        cuenta[m] = cuenta.get(m, 0) + 1
        print(f"{puntuar.ETIQ_MOD.get(m, m):22} {o['score']:3} {('FILTRADA ' if o['nivel'] == 'filtrada' else '')}"
              f"{o['titulo'][:40]:40} {o['empresa'][:18]:18} {motivo[:80]}")
    print("\nResumen:", ", ".join(f"{puntuar.ETIQ_MOD.get(k, k)} {v}" for k, v in cuenta.items()))
    print("Si alguna está mal clasificada, corrígela en la app (Detalle → ¿La modalidad está mal?) y pásame el texto.")


DEMO = [
    ("Backend Developer Java / Spring Boot (100% remoto)", "Ejemplo Tech S.L.", "España", "remoto",
     "Buscamos Backend Developer con al menos 4 años de experiencia en Java 17, Spring Boot y microservicios. "
     "Valorable Spring Batch, Docker, AWS y Kafka. APIs REST, PostgreSQL, JUnit y Mockito.\n"
     "Salario: 42.000 - 50.000 € brutos/año. 100% remoto desde España.", "Mid-Senior level", "Jornada completa", 18),
    ("Analista Programador Java", "Consultora Cantábrica", "Santander, Cantabria, España", "hibrido",
     "Para proyecto del sector energético buscamos analista programador Java con Spring, Hibernate/JPA y Oracle. "
     "Experiencia mínima de 3 años. Modelo híbrido: 2 días en oficina en Santander.\nRetribución: 34.000 €.",
     "Intermedio", "Jornada completa", 41),
    ("Senior Software Engineer (Java)", "Global Payments Co", "Bilbao, País Vasco, España", "hibrido",
     "We are looking for a Senior Software Engineer with 6+ years of experience in Java, Spring Boot, Kubernetes "
     "and Kafka. You will design event-driven microservices. Hybrid: 3 days per week in our Bilbao office.",
     "Mid-Senior level", "Full-time", 230),
    ("Desarrollador .NET C#", "Software Norte", "Torrelavega, Cantabria, España", "presencial",
     "Desarrollo de aplicaciones con .NET 8, C#, SQL Server y Angular. 2 años de experiencia.",
     "Intermedio", "Jornada completa", 12),
    ("Java Developer", "Remote First Inc", "Madrid, Comunidad de Madrid, España", "remoto",
     "Java developer with Spring. Remote but you'll need to come 2 days a week to our Madrid office.",
     "Mid-Senior level", "Full-time", 60),
]


def demo(db, cfg):
    import time as _t
    for i, (tit, emp, lug, modo, desc, sen, tipo, cand) in enumerate(DEMO):
        o = {"titulo": tit, "empresa": emp, "lugar": lug, "modo": modo, "descripcion": desc, "seniority": sen,
             "tipo_empleo": tipo, "candidatos": cand, "fecha_pub": _t.strftime("%Y-%m-%d"), "sueldo_txt": ""}
        p = puntuar.puntuar(o, cfg)
        oid = db.guardar({"uid": f"demo:{i}", "firma": scan.firma(tit, emp), "titulo": tit, "empresa": emp, "lugar": lug,
                          "fecha_pub": o["fecha_pub"], "url": "https://www.linkedin.com/jobs/", "descripcion": desc,
                          "candidatos": cand, "seniority": sen, "tipo_empleo": tipo, "busqueda": "demo",
                          "km": p["km"], "modalidad": p["modalidad"], "rol": p["rol"], "score": p["score"], "nivel": p["nivel"],
                          "desglose": p["desglose"], "encaje": p["encaje"], "filtro": p["filtro"], "idioma": p["idioma"],
                          "sueldo_txt": p["sueldo_txt"], "sueldo_min": p["sueldo_min"], "sueldo_max": p["sueldo_max"],
                          "anios_pedidos": p["anios_pedidos"], "listo": 1})
        print(f"{p['score']:3} {p['nivel']:11} {tit[:50]:50} {p['filtro']}")
        if oid and not p["filtro"] and p["score"] >= int(cfg.get("cv_desde_score", 55)):
            try:
                print("     CV:", cv.adaptar(db, cfg, oid))
            except Exception as e:  # noqa: BLE001
                print("     CV: error", e)
    print("Ofertas de ejemplo guardadas (uid demo:*). Para empezar limpio borra data/jobradar.db")


if __name__ == "__main__":
    main()
