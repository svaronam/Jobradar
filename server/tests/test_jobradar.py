import copy
import json
import os
import sys
import tempfile
import time
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from jobradar import config, cv, geo, linkedin, puntuar  # noqa: E402
from jobradar.db import DB  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def leer(n):
    with open(os.path.join(FIX, n), encoding="utf-8") as f:
        return f.read()


def cfg_prueba():
    c = copy.deepcopy(config.DEFAULT)
    c["data_dir"] = tempfile.mkdtemp()
    return c


class TestLinkedIn(unittest.TestCase):
    def test_lista(self):
        t = linkedin.parsear_lista(leer("lista.html"))
        self.assertEqual([x["job_id"] for x in t], ["4051234567", "4059876543", "4050000001"])
        self.assertEqual(t[0]["titulo"], "Backend Developer Java")
        self.assertEqual(t[0]["empresa"], "Ejemplo Tech")
        self.assertEqual(t[0]["lugar"], "España")
        self.assertEqual(t[0]["fecha_pub"], "2026-11-05")
        self.assertIn("40.000", t[0]["sueldo_txt"])
        self.assertEqual(t[0]["url"], "https://www.linkedin.com/jobs/view/4051234567/")
        self.assertEqual(t[1]["lugar"], "Santander, Cantabria, España")
        self.assertTrue(t[0]["logo_url"].startswith("https://media.licdn.com/"))
        self.assertEqual(t[1]["logo_url"], "")
        self.assertEqual(t[2]["titulo"], "Frontend Developer React")  # tarjeta con otro formato (enlace)

    def test_detalle(self):
        d = linkedin.parsear_detalle(leer("detalle.html"))
        self.assertEqual(d["titulo"], "Backend Developer Java")
        self.assertEqual(d["empresa"], "Ejemplo Tech")
        self.assertEqual(d["seniority"], "Intermedio")
        self.assertEqual(d["tipo_empleo"], "Jornada completa")
        self.assertEqual(d["sectores"], "Desarrollo de software")
        self.assertEqual(d["candidatos"], 201)
        self.assertIn("• Microservicios y APIs REST", d["descripcion"])
        self.assertIn("40.000", d["sueldo_txt"])

    def test_url(self):
        u = linkedin.url_busqueda("java spring", config.DEFAULT["modos"][0], 25, "r86400")
        self.assertIn("f_WT=2", u)
        self.assertIn("start=25", u)
        self.assertIn("geoId=105646813", u)
        z = linkedin.url_busqueda("java", config.DEFAULT["modos"][1], 0, "r86400")
        self.assertIn("f_WT=1%2C3", z)

    def test_migra_modos_v1(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "config.json"), "w") as f:
            json.dump({"modos": [{"nombre": n, "location": l, "f_WT": w} for n, l, w in config.MODOS_V1]}, f)
        self.assertEqual([m["nombre"] for m in config.cargar(d)["modos"]], ["remoto", "zona", "zona"])
        with open(os.path.join(d, "config.json"), "w") as f:
            json.dump({"palabras_clave": config.PALABRAS_V1, "excluir_titulo": config.EXCLUIR_V1}, f)
        c = config.cargar(d)
        self.assertEqual(c["palabras_clave"], config.DEFAULT["palabras_clave"])
        self.assertNotIn(".net", c["excluir_titulo"])


class TestGeo(unittest.TestCase):
    def test_distancias(self):
        self.assertLess(geo.km_desde("Limpias", "Laredo, Cantabria, España"), 10)
        self.assertTrue(35 <= geo.km_desde("Limpias", "Santander, Cantabria, España") <= 55)
        self.assertTrue(40 <= geo.km_desde("Limpias", "Bilbao, País Vasco, España") <= 65)
        self.assertTrue(geo.km_desde("Limpias", "Castro-Urdiales, Cantabria, España") < 30)
        self.assertTrue(geo.km_desde("Limpias", "Área metropolitana de Bilbao") < 65)
        self.assertGreater(geo.km_desde("Limpias", "Madrid, Comunidad de Madrid, España"), 300)
        self.assertIsNone(geo.km_desde("Limpias", "España"))


class TestPuntuar(unittest.TestCase):
    def setUp(self):
        self.cfg = cfg_prueba()

    def oferta(self, **k):
        o = {"titulo": "Backend Developer Java", "empresa": "X", "lugar": "España", "modo": "remoto",
             "descripcion": "Java, Spring Boot, microservicios, APIs REST, PostgreSQL. 4 años de experiencia. 100% remoto.",
             "fecha_pub": "2000-01-01"}
        o.update(k)
        return puntuar.puntuar(o, self.cfg)

    def test_remoto_bueno(self):
        p = self.oferta(sueldo_txt="45.000 € - 50.000 €")
        self.assertGreaterEqual(p["score"], 85)
        self.assertEqual(p["nivel"], "prioritaria")
        self.assertEqual((p["sueldo_min"], p["sueldo_max"]), (45000, 50000))

    def test_hibrido_fuera_de_zona(self):
        p = self.oferta(modo="zona", lugar="Madrid, Comunidad de Madrid, España", descripcion="Java. Modelo híbrido.")
        self.assertEqual(p["nivel"], "filtrada")
        self.assertIn("km", p["filtro"])

    def test_hibrido_en_zona(self):
        p = self.oferta(modo="zona", lugar="Santander, Cantabria, España", descripcion="Java. Modelo híbrido.")
        self.assertFalse(p["filtro"])
        self.assertTrue(any("Híbrido" in c for c, _ in p["desglose"]))

    def test_remoto_que_pide_oficina(self):
        p = self.oferta(lugar="Madrid, España", descripcion="Java Spring. Tendrás que venir 2 días a la semana a nuestra oficina.")
        self.assertEqual(p["modalidad"], "hibrido")  # salió en remoto, pero la oferta pide oficina
        self.assertEqual(p["nivel"], "filtrada")
        self.assertIn("2 días a la semana", p["filtro"])  # el motivo cita la oferta

    def test_modalidad_por_texto(self):
        self.assertEqual(self.oferta(titulo="Desarrollador JAVA - REMOTO", modo="zona", lugar="Bilbao")["modalidad"], "remoto")
        p = self.oferta(titulo="Java Backend Developer - Hybrid", modo="remoto", lugar="Málaga, España")
        self.assertEqual(p["modalidad"], "hibrido")
        self.assertEqual(p["nivel"], "filtrada")
        nc = self.oferta(descripcion="Java, Spring Boot.")
        self.assertEqual(nc["modalidad"], "remoto_nc")
        self.assertIn(15, [x for _, x in nc["desglose"]])
        manual = self.oferta(descripcion="Java, Spring Boot.", modalidad_manual="hibrido", lugar="Madrid")
        self.assertEqual((manual["modalidad"], manual["nivel"]), ("hibrido", "filtrada"))
        self.assertEqual(self.oferta(descripcion="Java", tipo_lugar="remoto")["modalidad"], "remoto")
        self.assertEqual(self.oferta(modo="zona", lugar="Santander", descripcion="Java. Modelo híbrido")["modalidad"], "hibrido")
        self.assertEqual(self.oferta(modo="zona", lugar="Santander", descripcion="Java Spring")["modalidad"], "presencial")
        self.assertEqual(self.oferta(descripcion="Cloud híbrido y nube híbrida en AWS")["modalidad"], "remoto_nc")
        self.assertEqual(self.oferta(descripcion="Fully remote. Occasional visits to the office once a month.")["modalidad"],
                         "remoto")

    def test_fuera_de_sector(self):
        self.assertTrue(puntuar.prefiltro("Conductor/a AUTÓNOMO C+E con ADR en Cantabria", self.cfg))
        self.assertTrue(puntuar.prefiltro("Coordinador/a de Prensa y RRPP", self.cfg))
        self.assertFalse(puntuar.prefiltro("Analista Informático-a", self.cfg))
        self.assertFalse(puntuar.prefiltro("Jefe de proyecto IT", self.cfg))

    def test_sueldo_bajo_penaliza(self):
        a = self.oferta(sueldo_txt="28.000 €")["score"]
        b = self.oferta()["score"]
        self.assertLess(a, b)

    def test_cualquier_lenguaje(self):
        # el lenguaje da igual: una oferta remota de Node no se filtra ni se penaliza, solo no suma el extra de stack
        p = self.oferta(titulo="Backend Developer Node.js", descripcion="Node.js, TypeScript, MongoDB. 100% remoto.")
        self.assertFalse(p["filtro"])
        self.assertGreaterEqual(p["score"], 58)
        self.assertNotIn("Lenguaje principal distinto de Java/Python", [c for c, _ in p["desglose"]])
        self.assertEqual(puntuar.rol_de("Frontend Developer React")[0], "desarrollador")
        self.cfg["pesos"] = {"lenguaje_ajeno": -15}  # se puede volver a activar desde el baremo
        self.assertIn(-15, [x for _, x in self.oferta(titulo="Backend Developer Node.js", descripcion="Node.js")["desglose"]])

    def test_excluidos(self):
        self.assertFalse(puntuar.prefiltro("Frontend Developer", self.cfg))   # ya no se excluyen tecnologías
        self.assertFalse(puntuar.prefiltro("Desarrollador .NET", self.cfg))
        self.assertTrue(puntuar.prefiltro("Comercial de software", self.cfg))
        self.assertTrue(puntuar.prefiltro("QA Tester", self.cfg))
        self.assertFalse(puntuar.prefiltro("Aquatic backend Java", self.cfg))  # 'qa' no casa dentro de palabra
        self.cfg["excluir_empresas"] = ["Cárnica SL"]
        self.assertEqual(self.oferta(empresa="carnica sl")["nivel"], "filtrada")

    def test_pesos_parciales(self):
        self.cfg["pesos"] = {"sueldo": {"por_debajo": -1}}
        p = self.oferta(sueldo_txt="20.000 €")
        self.assertIn(-1, [x for _, x in p["desglose"]])


class TestBaremo(unittest.TestCase):
    def test_editar_y_recalcular(self):
        cfg = cfg_prueba()
        db = DB(os.path.join(cfg["data_dir"], "t.db"))
        o = {"titulo": "Analista Programador Java", "empresa": "X", "lugar": "Santander, Cantabria, España",
             "modo": "hibrido", "descripcion": "Java y Spring. Salario 30.000 €", "fecha_pub": "2000-01-01"}
        p = puntuar.puntuar(o, cfg)
        oid = db.guardar({"uid": "x", **{k: v for k, v in o.items() if k != "modo"}, "modalidad": "hibrido",
                          "score": p["score"], "nivel": p["nivel"]})
        cfg["pesos"] = puntuar.validar_pesos({"sueldo": {"por_debajo": 0}, "hibrido": [[60, 30], [80, 20]],
                                              "stack": {"Java": 15}, "inventada": 3})
        self.assertNotIn("inventada", cfg["pesos"])
        r = puntuar.recalcular(db, cfg)
        nuevo = db.oferta(oid)
        self.assertEqual(r["revisadas"], 1)
        self.assertGreater(nuevo["score"], p["score"])
        self.assertTrue(any(c.startswith("Híbrido a ~44 km") and x == 30 for c, x in nuevo["desglose"]))
        self.assertEqual(puntuar.pesos(cfg)["sueldo"]["minimo"], puntuar.PESOS["sueldo"]["minimo"])  # lo no tocado sigue de serie

    def test_validaciones(self):
        with self.assertRaises(ValueError):
            puntuar.validar_niveles({"prioritaria": 50, "interesante": 60, "vigilar": 40})
        with self.assertRaises(ValueError):
            puntuar.validar_pesos({"remoto": "mucho"})
        self.assertEqual(puntuar.maximo(puntuar.PESOS), 100)


class TestPlanificador(unittest.TestCase):
    def test_horas_fijas(self):
        from jobradar import planificador as pl
        import datetime as dt
        cfg = {"horas_pasada": ["08:40", "13:40", "19:40"], "frecuencia": {"modo": "horas"}}
        ahora = dt.datetime(2026, 11, 5, 10, 0)  # jueves
        self.assertEqual(pl.proxima(cfg, dt.datetime(2026, 11, 5, 8, 40), ahora), dt.datetime(2026, 11, 5, 13, 40))
        # última ayer por la noche y la Pi encendida a las 10: recupera la de las 08:40 (dentro de 3 h)
        self.assertLessEqual(pl.proxima(cfg, dt.datetime(2026, 11, 4, 19, 40), ahora), ahora)
        # solo laborables: viernes 19:40 -> lunes 08:40
        cfg["frecuencia"]["dias"] = [0, 1, 2, 3, 4]
        self.assertEqual(pl.proxima(cfg, dt.datetime(2026, 11, 6, 19, 40), dt.datetime(2026, 11, 6, 20, 0)),
                         dt.datetime(2026, 11, 9, 8, 40))

    def test_intervalo(self):
        from jobradar import planificador as pl
        import datetime as dt
        cfg = {"frecuencia": {"modo": "intervalo", "cada_horas": 3, "desde": "08:00", "hasta": "22:00"}}
        ult = dt.datetime(2026, 11, 5, 9, 0)
        self.assertEqual(pl.proxima(cfg, ult, dt.datetime(2026, 11, 5, 9, 30)), dt.datetime(2026, 11, 5, 12, 0))
        # pasada a las 21:00 -> la siguiente sería a las 00:00, fuera de la franja -> mañana 08:00
        self.assertEqual(pl.proxima(cfg, dt.datetime(2026, 11, 5, 21, 0), dt.datetime(2026, 11, 5, 21, 5)),
                         dt.datetime(2026, 11, 6, 8, 0))
        # se acorta la frecuencia y ya toca: ahora mismo
        ahora = dt.datetime(2026, 11, 5, 15, 0)
        self.assertEqual(pl.proxima(cfg, dt.datetime(2026, 11, 5, 10, 0), ahora), ahora)
        self.assertEqual(pl.pasadas_al_dia(cfg), 5)
        self.assertEqual(pl.describir(cfg), "cada 3 h de 08:00 a 22:00 + rápido cada 15 min, todos los días")
        self.assertEqual(pl.proxima(cfg, None, ahora), ahora)  # nunca buscó: ya

    def test_barrido_rapido(self):
        from jobradar import planificador as pl, scan
        import datetime as dt
        cfg = {"horas_pasada": ["08:40", "13:40", "19:40"],
               "frecuencia": {"modo": "horas", "rapida_min": 15, "desde": "08:00", "hasta": "22:00"}}
        ult = dt.datetime(2026, 11, 5, 10, 0)
        self.assertEqual(pl.proxima_rapida(cfg, ult, dt.datetime(2026, 11, 5, 10, 5)), dt.datetime(2026, 11, 5, 10, 15))
        # fuera de la franja: mañana a las 08:00
        self.assertEqual(pl.proxima_rapida(cfg, dt.datetime(2026, 11, 5, 21, 55), dt.datetime(2026, 11, 5, 21, 56)),
                         dt.datetime(2026, 11, 6, 8, 0))
        cfg["frecuencia"]["rapida_min"] = 0
        self.assertIsNone(pl.proxima_rapida(cfg, ult))
        self.assertEqual(scan.palabras_or(["programador", "software engineer", " "]), 'programador OR "software engineer"')
        with self.assertRaises(ValueError):
            pl.validar({"modo": "horas", "rapida_min": 2, "dias": [0]}, ["09:00"])
        self.assertEqual(pl.validar({"modo": "horas", "rapida_min": 0, "dias": [0]}, ["09:00"])[0]["rapida_min"], 0)

    def test_pasada_rapida_y_tipo(self):
        from jobradar import scan, util, linkedin
        cfg = cfg_prueba()
        cfg["pausa_min"] = cfg["pausa_max"] = 0
        db = DB(os.path.join(cfg["data_dir"], "t.db"))
        urls = []
        lista = leer("lista.html")
        util.get, orig = (lambda url, **k: (urls.append(url) or (200, "" if "jobPosting" in url else lista))), util.get
        linkedin.util.get = util.get
        try:
            db.guardar({"uid": "previa", "nivel": "baja"})  # ya hubo una pasada completa antes
            r = scan.pasada(db, cfg, rapida=True)
        finally:
            util.get = linkedin.util.get = orig
        self.assertEqual(r["tipo"], "rapida")
        listados = [u for u in urls if "seeMoreJobPostings" in u]
        self.assertEqual(len(listados), len(cfg["modos"]))  # una por modo
        self.assertIn("OR", linkedin.urllib.parse.unquote_plus(listados[0]))
        self.assertIsNotNone(db.ultima_pasada_inicio("rapida"))
        self.assertIsNone(db.ultima_pasada_inicio("completa"))

    def test_validar(self):
        from jobradar import planificador as pl
        with self.assertRaises(ValueError):
            pl.validar({"modo": "intervalo", "cada_horas": 0.5}, [])
        with self.assertRaises(ValueError):
            pl.validar({"modo": "intervalo", "cada_horas": 2, "desde": "22:00", "hasta": "08:00"}, [])
        with self.assertRaises(ValueError):
            pl.validar({"modo": "horas", "dias": []}, ["09:00"])
        f, h = pl.validar({"modo": "horas", "dias": [4, 0, 0]}, ["9:05", "13:40", "09:05"])
        self.assertEqual((f["dias"], h), ([0, 4], ["09:05", "13:40"]))


class TestSueldo(unittest.TestCase):
    def test_formatos(self):
        s = puntuar.sueldo
        self.assertEqual(s("35.000 € - 42.000 €"), (35000, 42000))
        self.assertEqual(s("35-42K"), (35000, 42000))
        self.assertEqual(s("€40,000/año"), (40000, 40000))
        self.assertEqual(s("40.000,00 €/año - 48.000,00 €/año"), (40000, 48000))
        self.assertEqual(s("2.800 €/mes"), (33600, 33600))
        self.assertEqual(s("Hasta 45k€"), (45000, 45000))
        self.assertEqual(s(""), (None, None))
        self.assertEqual(s("Equipo de 300 personas"), (None, None))

    def test_en_texto(self):
        txt, a, b = puntuar.sueldo_en_texto("Somos 500 empleados.\nSalario: 38.000 - 44.000 € brutos anuales.")
        self.assertEqual((a, b), (38000, 44000))

    def test_anios_idioma(self):
        self.assertEqual(puntuar.anios_pedidos("Al menos 3 años de experiencia en Java"), 3)
        self.assertEqual(puntuar.anios_pedidos("5+ years of experience with Spring"), 5)
        self.assertEqual(puntuar.idioma("We are looking for a developer with experience in the cloud and you"), "en")
        self.assertEqual(puntuar.idioma("Buscamos un desarrollador con experiencia en la nube para el equipo"), "es")


class TestCV(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(BASE, "data", "cv", "base_es.json"), encoding="utf-8") as f:
            self.cv = json.load(f)

    def test_guarda_rechaza_invenciones(self):
        exp0 = self.cv["experiencia"][0]["logros"]
        r = {
            "titular": "Back-End Developer | Java · Spring Boot · Kafka",  # Kafka no está en el CV
            "perfil": "Desarrollador backend con **5 años** en **Java** y **Spring Boot** para Iberdrola.",
            "experiencia": [{"indice": 0, "logros": [
                {"indice": 1, "texto": "Desarrollo de **microservicios** y **APIs REST** con **Spring Boot** sobre **SQL** para Ventas de Iberdrola."},
                {"indice": 0, "texto": "Lideré un equipo Scrum de 8 personas."},           # cargo + cifra inventados
                {"indice": 3, "texto": "Pruebas con **JUnit**, **Mockito** y **Cypress**."},   # tecnología nueva... (Cypress no está en VOCAB)
                {"indice": 2, "texto": "Procesos batch con Spring Batch y Kubernetes."},     # Kubernetes no está
                {"indice": 99, "texto": "índice imposible"},
            ]}],
            "habilidades": [{"indice": 1, "items": ["microservicios", "Spring Boot", "Kafka"]}, {"indice": 0, "items": ["Python", "Java"]}],
            "orden_secciones": ["experiencia", "habilidades", "proyectos", "educacion"],
        }
        out, rev = cv._aplicar(self.cv, r)
        self.assertEqual(out["titular"], self.cv["titular"])  # titular con Kafka -> se queda el original
        self.assertIn("5 años", out["perfil"])
        logros = out["experiencia"][0]["logros"]
        self.assertEqual(len(logros), len(exp0))  # nunca se pierde una viñeta
        self.assertTrue(logros[0].startswith("Desarrollo de **microservicios** y **APIs REST**"))
        self.assertEqual(logros[1], exp0[0])  # la de "Lideré" se revierte
        self.assertEqual(logros[3], exp0[2])  # la de Kubernetes se revierte
        self.assertTrue(any("Kubernetes".lower() in x.lower() or "kubernetes" in x for x in rev))
        # habilidades: Kafka no entra, no se pierde ningún item, certificaciones al final
        back = out["habilidades"][0]
        self.assertEqual(back["categoria"], "Backend")
        self.assertEqual(back["items"][:2], ["microservicios", "Spring Boot"])
        self.assertNotIn("Kafka", back["items"])
        self.assertEqual(sorted(back["items"]), sorted(self.cv["habilidades"][1]["items"]))
        self.assertEqual(out["habilidades"][1]["items"], ["Python", "Java", "SQL (MySQL, Oracle, PostgreSQL e IBM DB2)"])
        self.assertIn("Certific", out["habilidades"][-1]["categoria"])
        self.assertEqual(out["orden"][0], "experiencia")
        # lo intocable sigue igual
        self.assertEqual(out["educacion"], self.cv["educacion"])
        self.assertEqual([e["fechas"] for e in out["experiencia"]], [e["fechas"] for e in self.cv["experiencia"]])

    def test_reglas_sin_ia(self):
        o = {"titulo": "Batch developer", "descripcion": "Spring Batch, Cobol, procesos por lotes"}
        out = cv._adaptar_reglas(self.cv, o)
        self.assertIn("Spring Batch", out["experiencia"][1]["logros"][0])
        self.assertEqual(len(out["experiencia"][0]["logros"]), len(self.cv["experiencia"][0]["logros"]))

    def test_pdf_una_pagina(self):
        from jobradar import pdfcv
        datos = pdfcv.generar(self.cv)
        self.assertTrue(datos.startswith(b"%PDF"))
        self.assertEqual(datos.count(b"/Type /Page\n") + datos.count(b"/Type /Page "), 1)


class TestLogos(unittest.TestCase):
    def test_logo_una_vez_por_empresa(self):
        from jobradar import scan, util
        cfg = cfg_prueba()
        db = DB(os.path.join(cfg["data_dir"], "t.db"))
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
        bajadas = []
        orig = util.bajar
        util.bajar = lambda url, **k: bajadas.append(url) or png
        try:
            a = db.guardar({"uid": "a", "empresa": "Sopra Steria", "nivel": "vigilar"})
            b = db.guardar({"uid": "b", "empresa": "Sopra Steria", "nivel": "vigilar"})
            scan.guardar_logo(db, cfg, a, "Sopra Steria", "https://media.licdn.com/x.png")
            scan.guardar_logo(db, cfg, b, "Sopra Steria", "https://media.licdn.com/y.png")
        finally:
            util.bajar = orig
        self.assertEqual(len(bajadas), 1)
        self.assertEqual(db.oferta(a)["logo"], db.oferta(b)["logo"])
        self.assertTrue(db.oferta(a)["logo"].endswith(".png"))
        self.assertTrue(os.path.exists(os.path.join(cfg["data_dir"], "logos", db.oferta(a)["logo"])))

    def test_migracion_columnas(self):
        import sqlite3
        p = os.path.join(tempfile.mkdtemp(), "v1.db")
        c = sqlite3.connect(p)
        from jobradar import db as dbmod
        c.executescript(dbmod.ESQUEMA)  # tabla de la v1.0, sin las columnas de logo
        c.commit(); c.close()
        db = DB(p)
        db.guardar({"uid": "z", "empresa": "X", "logo": "a.png"})
        self.assertEqual(db.logo_de_empresa("X"), "a.png")


class TestOrden(unittest.TestCase):
    def test_ordenes(self):
        db = DB(os.path.join(tempfile.mkdtemp(), "t.db"))
        db.guardar({"uid": "a", "titulo": "A", "nivel": "vigilar", "score": 50, "modalidad": "hibrido", "km": 44,
                    "sueldo_max": 40000, "candidatos": 300, "fecha_pub": "2026-11-01"})
        db.guardar({"uid": "b", "titulo": "B", "nivel": "prioritaria", "score": 90, "modalidad": "remoto",
                    "candidatos": 10, "fecha_pub": "2026-11-03"})
        db.guardar({"uid": "c", "titulo": "C", "nivel": "interesante", "score": 70, "modalidad": "presencial", "km": 8,
                    "sueldo_max": 55000, "fecha_pub": "2026-11-05"})
        t = lambda o: [x["titulo"] for x in db.listar(orden=o)]  # noqa: E731
        self.assertEqual(t("puntuacion"), ["B", "C", "A"])
        self.assertEqual(t("sueldo"), ["C", "A", "B"])        # sin sueldo al final
        self.assertEqual(t("distancia"), ["B", "C", "A"])     # remoto = 0 km
        self.assertEqual(t("recientes"), ["C", "B", "A"])
        self.assertEqual(t("candidatos"), ["B", "A", "C"])    # sin dato al final
        self.assertEqual(t("inventado"), ["B", "C", "A"])     # orden desconocido -> puntuación


class TestTipoLugar(unittest.TestCase):
    def test_ficha(self):
        from bs4 import BeautifulSoup
        ld = '<script type="application/ld+json">{"@type":"JobPosting","jobLocationType":"TELECOMMUTE"}</script>'
        self.assertEqual(linkedin.tipo_lugar(BeautifulSoup(ld, "html.parser")), "remoto")
        cab = '<section class="top-card-layout"><span class="topcard__flavor">Madrid</span><span>Híbrido</span></section>'
        self.assertEqual(linkedin.tipo_lugar(BeautifulSoup(cab, "html.parser")), "hibrido")
        self.assertEqual(linkedin.tipo_lugar(BeautifulSoup(leer("detalle.html"), "html.parser")), "")
        chip = '<section class="top-card-layout"><button><span>✓ En remoto</span></button><span>Jornada completa</span></section>'
        self.assertEqual(linkedin.tipo_lugar(BeautifulSoup(chip, "html.parser")), "remoto")
        crit = ('<ul><li class="description__job-criteria-item"><h3>Tipo de lugar de trabajo</h3>'
                '<span>Presencial</span></li></ul>')
        self.assertEqual(linkedin.tipo_lugar(BeautifulSoup(crit, "html.parser")), "presencial")
        self.assertEqual(linkedin._lugar_y_tipo("Madrid, Comunidad de Madrid, España (Híbrido)", BeautifulSoup("", "html.parser")),
                         {"lugar": "Madrid, Comunidad de Madrid, España", "tipo_lugar": "hibrido"})
        self.assertEqual(linkedin._lugar_y_tipo("Castro-Urdiales, Cantabria", BeautifulSoup("", "html.parser"))["tipo_lugar"], "")

    def test_beneficio_no_es_remoto(self):
        from jobradar import puntuar as pu
        d = ("What we offer:\n• Hybrid working model in our Malaga office (3 days per week on-site).\n"
             "• Gym, lunch and support for transport.\n• Up to 10 days per year working remotely from abroad.")
        self.assertEqual(pu.detectar_modalidad("remoto", d, "Backend .NET Software Engineer")[0], "hibrido")
        self.assertEqual(pu.detectar_modalidad("remoto", "Trabajo en remoto. 1 día al mes en la oficina.", "Java")[0], "remoto")
        self.assertEqual(pu.detectar_modalidad("remoto", "Working remotely with 2 days per week in the office", "Java")[0],
                         "hibrido")  # remoto débil + días de oficina = híbrido
        self.assertEqual(pu.detectar_modalidad("remoto", "100% remoto, con 1 día a la semana en oficina", "Java")[0], "remoto?")

    def test_etiqueta_manda(self):
        from jobradar import puntuar as pu
        # la ficha dice Presencial aunque salió en la búsqueda de remoto y la descripción no dice nada
        m, motivo = pu.detectar_modalidad("remoto", "Java Spring", "Desarrollador/a Java Sr", "presencial")
        self.assertEqual((m, motivo), ("presencial", "LinkedIn: «Presencial»"))
        self.assertEqual(pu.detectar_modalidad("remoto", "modelo híbrido", "Java", "remoto")[0], "remoto")
        cfg = cfg_prueba()
        p = pu.puntuar({"titulo": "Desarrollador Java", "lugar": "Santander, Cantabria, España", "modo": "zona",
                        "descripcion": "Java", "tipo_lugar": "presencial"}, cfg)
        self.assertFalse(p["filtro"])
        self.assertIn(p["nivel"], ("vigilar", "interesante", "prioritaria"))  # presencial en tu zona: te llega


class TestCandidaturas(unittest.TestCase):
    def setUp(self):
        self.cfg = cfg_prueba()
        self.db = DB(os.path.join(self.cfg["data_dir"], "t.db"))
        self.oid = self.db.guardar({"uid": "a", "titulo": "Backend Java", "empresa": "Fever", "nivel": "prioritaria",
                                    "score": 90, "estado": "nueva"})

    def test_fases_y_recordatorio(self):
        from jobradar import seguimiento
        import datetime as dt
        db, oid = self.db, self.oid
        hace8 = time.time() - 8 * 86400
        db.add_evento(oid, "aplicada", ts=hace8)
        o = db.oferta(oid)
        self.assertEqual((o["fase"], o["estado"]), ("aplicada", "aplicada"))
        a_las_10 = dt.datetime.now().replace(hour=10)
        self.assertEqual(seguimiento.recordatorios(db, self.cfg, a_las_10), 1)
        self.assertEqual(seguimiento.recordatorios(db, self.cfg, a_las_10), 0)  # no se repite
        al = db.alertas_desde(0)[-1]
        self.assertEqual((al["tipo"], al["oferta_id"]), ("seguimiento", oid))
        self.assertIn("Fever", al["texto"])
        self.assertEqual(db.alertas_recientes(), [])  # no sale como aviso de estado en el panel
        # apuntar algo reinicia la cuenta
        db.add_evento(oid, "entrevista", "Con la responsable técnica")
        self.assertEqual(seguimiento.recordatorios(db, self.cfg, a_las_10), 0)
        self.assertEqual(seguimiento.recordatorios(db, self.cfg, a_las_10.replace(hour=23)), 0)  # de noche, nada
        c = db.candidaturas()[0]
        self.assertEqual((c["fase"], c["n_notas"]), ("entrevista", 1))
        self.assertAlmostEqual(c["aplicada_ts"], hace8, delta=1)
        # borrar el último paso vuelve a la fase anterior
        ult = db.eventos(oid)[-1]["id"]
        db.borrar_evento(ult)
        self.assertEqual(db.oferta(oid)["fase"], "aplicada")
        db.add_evento(oid, "rechazada")
        self.assertEqual(db.sin_respuesta(0), [])  # cerrada: ya no recuerda

    def test_resumen_del_dia(self):
        from jobradar import seguimiento
        import datetime as dt
        db = self.db
        db.guardar({"uid": "b", "titulo": "Otra", "empresa": "X", "nivel": "interesante", "score": 60, "estado": "nueva"})
        db.guardar({"uid": "c", "titulo": "Vista", "empresa": "Y", "nivel": "prioritaria", "score": 95, "estado": "vista"})
        h = dt.datetime.now().replace(hour=20, minute=5)
        self.assertFalse(seguimiento.resumen_del_dia(db, self.cfg, h.replace(hour=12)))  # aún no es la hora
        self.assertTrue(seguimiento.resumen_del_dia(db, self.cfg, h))
        self.assertFalse(seguimiento.resumen_del_dia(db, self.cfg, h))  # una vez al día
        al = db.alertas_desde(0)[-1]
        self.assertEqual(al["tipo"], "resumen")
        self.assertEqual([o["titulo"] for o in al["datos"]], ["Backend Java", "Otra"])  # la vista no entra
        with self.assertRaises(ValueError):
            seguimiento.validar_resumen({"hora": "25:00"})


class TestDB(unittest.TestCase):
    def test_avisos_no_se_saltan_ofertas_sin_cv(self):
        db = DB(os.path.join(tempfile.mkdtemp(), "t.db"))
        a = db.guardar({"uid": "a", "nivel": "prioritaria", "score": 90, "listo": 1})
        b = db.guardar({"uid": "b", "nivel": "prioritaria", "score": 90, "listo": 0, "cv_estado": "pendiente"})
        db.guardar({"uid": "c", "nivel": "interesante", "score": 60, "listo": 1})
        self.assertEqual(db.max_id(), a)  # no puede avanzar más allá de b hasta que tenga su CV
        db.actualizar(b, listo=1, cv_estado="ok")
        self.assertEqual(db.max_id(), 3)
        self.assertIsNone(db.guardar({"uid": "a"}))  # duplicada


if __name__ == "__main__":
    unittest.main()
