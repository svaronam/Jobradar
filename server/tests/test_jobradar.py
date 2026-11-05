import copy
import json
import os
import sys
import tempfile
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
             "descripcion": "Java, Spring Boot, microservicios, APIs REST, PostgreSQL. 4 años de experiencia.",
             "fecha_pub": "2000-01-01"}
        o.update(k)
        return puntuar.puntuar(o, self.cfg)

    def test_remoto_bueno(self):
        p = self.oferta(sueldo_txt="45.000 € - 50.000 €")
        self.assertGreaterEqual(p["score"], 85)
        self.assertEqual(p["nivel"], "prioritaria")
        self.assertEqual((p["sueldo_min"], p["sueldo_max"]), (45000, 50000))

    def test_hibrido_fuera_de_zona(self):
        p = self.oferta(modo="hibrido", lugar="Madrid, Comunidad de Madrid, España")
        self.assertEqual(p["nivel"], "filtrada")
        self.assertIn("km", p["filtro"])

    def test_hibrido_en_zona(self):
        p = self.oferta(modo="hibrido", lugar="Santander, Cantabria, España")
        self.assertFalse(p["filtro"])
        self.assertTrue(any("Híbrido" in c for c, _ in p["desglose"]))

    def test_remoto_que_pide_oficina(self):
        p = self.oferta(lugar="Madrid, España", descripcion="Java Spring. Tendrás que venir 2 días a la semana a nuestra oficina.")
        self.assertEqual(p["modalidad"], "remoto?")
        self.assertEqual(p["nivel"], "filtrada")

    def test_modalidad_por_texto(self):
        self.assertEqual(self.oferta(titulo="Desarrollador JAVA - REMOTO", modo="zona", lugar="Bilbao")["modalidad"], "remoto")
        p = self.oferta(titulo="Java Backend Developer - Hybrid", modo="remoto", lugar="Málaga, España")
        self.assertEqual(p["modalidad"], "remoto?")
        self.assertEqual(self.oferta(modo="zona", lugar="Santander", descripcion="Java. Modelo híbrido")["modalidad"], "hibrido")
        self.assertEqual(self.oferta(modo="zona", lugar="Santander", descripcion="Java Spring")["modalidad"], "presencial")

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
        p = self.oferta(titulo="Backend Developer Node.js", descripcion="Node.js, TypeScript, MongoDB")
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
        self.assertIn(["Híbrido a ~44 km", 30], nuevo["desglose"])
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
        self.assertEqual(pl.describir(cfg), "cada 3 h de 08:00 a 22:00, todos los días")
        self.assertEqual(pl.proxima(cfg, None, ahora), ahora)  # nunca buscó: ya

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
