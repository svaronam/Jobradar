import contextlib
import json
import sqlite3
import threading
import time

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ofertas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uid TEXT UNIQUE NOT NULL,          -- li:<job_id>
  firma TEXT,                        -- titulo|empresa normalizados (la misma oferta publicada varias veces)
  titulo TEXT, empresa TEXT, lugar TEXT, km INTEGER, modalidad TEXT, fecha_pub TEXT, url TEXT,
  sueldo_txt TEXT, sueldo_min INTEGER, sueldo_max INTEGER, candidatos INTEGER,
  seniority TEXT, tipo_empleo TEXT, funcion TEXT, sectores TEXT, anios_pedidos INTEGER,
  descripcion TEXT, idioma TEXT, rol TEXT,
  score INTEGER, nivel TEXT, desglose TEXT, encaje TEXT, filtro TEXT,
  busqueda TEXT,
  estado TEXT DEFAULT 'nueva',       -- nueva · vista · favorita · aplicada · descartada
  aviso INTEGER DEFAULT 1,           -- 0 = no notificar (primera pasada)
  listo INTEGER DEFAULT 0,           -- 1 = ya tiene su CV (o no lo necesita): se puede notificar
  cv_estado TEXT DEFAULT '',         -- '' · pendiente · ok · error
  cv_idioma TEXT, cv_archivo TEXT, cv_cambios TEXT, cv_error TEXT, cv_ts REAL,
  creado REAL
);
CREATE INDEX IF NOT EXISTS ix_of_score ON ofertas(score);
CREATE INDEX IF NOT EXISTS ix_of_firma ON ofertas(firma);
CREATE TABLE IF NOT EXISTS pasadas (
  id INTEGER PRIMARY KEY AUTOINCREMENT, inicio REAL, fin REAL, peticiones INTEGER, tarjetas INTEGER,
  nuevas INTEGER, filtradas INTEGER, cvs INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS alertas (
  id INTEGER PRIMARY KEY AUTOINCREMENT, clave TEXT UNIQUE, texto TEXT, ts REAL
);
-- historial de cada candidatura: aplicada, entrevista, prueba, oferta, rechazada, retirada, o una nota suelta
CREATE TABLE IF NOT EXISTS eventos (
  id INTEGER PRIMARY KEY AUTOINCREMENT, oferta_id INTEGER NOT NULL, ts REAL, fase TEXT, nota TEXT
);
CREATE INDEX IF NOT EXISTS ix_ev_oferta ON eventos(oferta_id);
"""
FASES = ["aplicada", "entrevista", "prueba", "oferta", "rechazada", "retirada"]
FASES_ACTIVAS = ["aplicada", "entrevista", "prueba"]  # las que esperan respuesta: llevan recordatorio
JSON_COLS = ("desglose", "encaje", "cv_cambios")
COLS_NUEVAS = {"logo_url": "TEXT", "logo": "TEXT",  # logo: archivo en data/logos/
               "fase": "TEXT", "fase_ts": "REAL",     # fase de la candidatura y desde cuándo
               "tipo_lugar": "TEXT",                  # modalidad que trae la ficha de LinkedIn, si la trae
               "modalidad_manual": "TEXT"}            # corrección a mano desde la app
LISTA_COLS = ("id, uid, titulo, empresa, lugar, km, modalidad, fecha_pub, url, sueldo_txt, sueldo_min, sueldo_max, "
              "candidatos, seniority, tipo_empleo, anios_pedidos, idioma, rol, score, nivel, desglose, encaje, filtro, "
              "estado, cv_estado, cv_idioma, cv_archivo, cv_cambios, cv_error, creado, logo, fase, fase_ts, modalidad_manual")


class DB:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        with self._c() as c:
            c.executescript(ESQUEMA)
            tiene = {r["name"] for r in c.execute("PRAGMA table_info(ofertas)")}
            for col, tipo in COLS_NUEVAS.items():  # migración desde la v1.0
                if col not in tiene:
                    c.execute(f"ALTER TABLE ofertas ADD COLUMN {col} {tipo}")
            if "tipo" not in {r["name"] for r in c.execute("PRAGMA table_info(pasadas)")}:
                c.execute("ALTER TABLE pasadas ADD COLUMN tipo TEXT DEFAULT 'completa'")
            tiene_al = {r["name"] for r in c.execute("PRAGMA table_info(alertas)")}
            for col, tipo in {"tipo": "TEXT", "oferta_id": "INTEGER", "datos": "TEXT"}.items():
                if col not in tiene_al:  # tipo: NULL = estado del radar · resumen · seguimiento
                    c.execute(f"ALTER TABLE alertas ADD COLUMN {col} {tipo}")

    @contextlib.contextmanager
    def _c(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def _dict(r):
        d = dict(r)
        for k in JSON_COLS:
            if k in d and d[k]:
                try:
                    d[k] = json.loads(d[k])
                except ValueError:
                    pass
        return d

    # ------------------------------------------------------------------ ofertas
    def existe(self, uid):
        with self._c() as c:
            return c.execute("SELECT 1 FROM ofertas WHERE uid=?", (uid,)).fetchone() is not None

    def duplicada(self, firma, dias=30):
        with self._c() as c:
            r = c.execute("SELECT id FROM ofertas WHERE firma=? AND creado>? LIMIT 1",
                          (firma, time.time() - dias * 86400)).fetchone()
            return r["id"] if r else None

    def guardar(self, o):
        o = dict(o)
        for k in JSON_COLS:
            if k in o and not isinstance(o[k], str):
                o[k] = json.dumps(o[k], ensure_ascii=False)
        o.setdefault("creado", time.time())
        cols = [k for k in o if k != "id"]
        with self.lock, self._c() as c:
            cur = c.execute(f"INSERT OR IGNORE INTO ofertas ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                            [o[k] for k in cols])
            return cur.lastrowid if cur.rowcount else None

    def actualizar(self, oid, **campos):
        for k in JSON_COLS:
            if k in campos and not isinstance(campos[k], str) and campos[k] is not None:
                campos[k] = json.dumps(campos[k], ensure_ascii=False)
        if not campos:
            return
        with self.lock, self._c() as c:
            c.execute(f"UPDATE ofertas SET {', '.join(k + '=?' for k in campos)} WHERE id=?", [*campos.values(), oid])

    def oferta(self, oid):
        with self._c() as c:
            r = c.execute("SELECT * FROM ofertas WHERE id=?", (oid,)).fetchone()
            return self._dict(r) if r else None

    ORDENES = {
        # las nuevas primero y, dentro, por puntuación (lo de siempre)
        "puntuacion": "(estado='nueva') DESC, score DESC, id DESC",
        # sin sueldo publicado al final
        "sueldo": "(sueldo_max IS NULL) ASC, sueldo_max DESC, sueldo_min DESC, score DESC",
        # remoto cuenta como 0 km; sin ubicación reconocida al final
        "distancia": "CASE WHEN modalidad LIKE 'remoto%' THEN 0 WHEN km IS NULL THEN 99999 ELSE km END ASC, score DESC",
        "recientes": "COALESCE(fecha_pub, '') DESC, id DESC",
        # menos competencia primero; sin dato al final
        "candidatos": "(candidatos IS NULL) ASC, candidatos ASC, score DESC",
    }

    def listar(self, nivel=None, estado=None, q=None, modalidad=None, filtradas=False, desde_id=None,
               solo_listas=False, solo_aviso=False, limite=300, orden="puntuacion"):
        w, a = [], []
        if nivel:
            ns = nivel.split(",")
            w.append(f"nivel IN ({','.join('?' * len(ns))})")
            a += ns
        elif not filtradas:
            w.append("nivel != 'filtrada'")
        if estado:
            es = estado.split(",")
            w.append(f"estado IN ({','.join('?' * len(es))})")
            a += es
        elif desde_id is None:
            w.append("estado != 'descartada'")
        if modalidad:
            w.append("modalidad LIKE ?")
            a.append(modalidad + "%")
        if q:
            w.append("(titulo LIKE ? OR empresa LIKE ? OR lugar LIKE ? OR descripcion LIKE ?)")
            a += [f"%{q}%"] * 4
        if desde_id is not None:
            w.append("id > ?")
            a.append(desde_id)
        if solo_listas:
            w.append("listo = 1")
        if solo_aviso:
            w.append("aviso = 1")
        sql = f"SELECT {LISTA_COLS} FROM ofertas"
        if w:
            sql += " WHERE " + " AND ".join(w)
        sql += " ORDER BY " + ("id ASC" if desde_id is not None else self.ORDENES.get(orden, self.ORDENES["puntuacion"]))
        sql += " LIMIT ?"
        a.append(limite)
        with self._c() as c:
            return [self._dict(r) for r in c.execute(sql, a)]

    def max_id(self, solo_listas=True):
        """Mayor id hasta el que la app puede avanzar sin perderse nada: no pasa de la primera oferta sin CV aún."""
        with self._c() as c:
            if solo_listas:
                r = c.execute("SELECT MIN(id) m FROM ofertas WHERE listo=0").fetchone()
                if r["m"] is not None:
                    return r["m"] - 1
            return c.execute("SELECT COALESCE(MAX(id),0) m FROM ofertas").fetchone()["m"]

    def para_recalcular(self):
        with self._c() as c:
            return [self._dict(r) for r in c.execute(
                "SELECT id, titulo, empresa, lugar, modalidad, busqueda, fecha_pub, descripcion, sueldo_txt, seniority, "
                "tipo_empleo, candidatos, score, nivel, desglose, filtro, tipo_lugar, modalidad_manual "
                "FROM ofertas WHERE estado != 'descartada'")]

    def para_recalcular_una(self, oid):
        with self._c() as c:
            r = c.execute("SELECT id, titulo, empresa, lugar, modalidad, busqueda, fecha_pub, descripcion, sueldo_txt, "
                          "seniority, tipo_empleo, candidatos, score, nivel, desglose, filtro, tipo_lugar, modalidad_manual "
                          "FROM ofertas WHERE id=?", (oid,)).fetchone()
            return self._dict(r) if r else None

    def logo_de_empresa(self, empresa):
        """Logo ya descargado para esa empresa (no se baja dos veces el mismo)."""
        with self._c() as c:
            r = c.execute("SELECT logo FROM ofertas WHERE empresa=? AND logo IS NOT NULL AND logo!='' LIMIT 1",
                          (empresa,)).fetchone()
            return r["logo"] if r else None

    def faltan_logos(self, limite=80):
        """Ofertas visibles sin logo, primero las mejores."""
        with self._c() as c:
            return [dict(r) for r in c.execute(
                "SELECT id, uid, empresa, logo_url FROM ofertas WHERE (logo IS NULL OR logo='') AND nivel!='filtrada' "
                "AND estado!='descartada' ORDER BY score DESC LIMIT ?", (limite,))]

    def faltan_tipos(self, limite=80):
        """Ofertas visibles que aún no se han mirado para leer la etiqueta de modalidad de LinkedIn."""
        with self._c() as c:
            return [dict(r) for r in c.execute(
                "SELECT id, uid, empresa, logo FROM ofertas WHERE tipo_lugar IS NULL AND uid LIKE 'li:%' "
                "AND estado!='descartada' AND (nivel!='filtrada' OR COALESCE(descripcion,'')!='') "
                "ORDER BY score DESC LIMIT ?", (limite,))]

    def sin_logo(self, uid):
        """id de una oferta ya guardada que aún no tiene logo (para completarlo al volver a verla)."""
        with self._c() as c:
            r = c.execute("SELECT id FROM ofertas WHERE uid=? AND (logo IS NULL OR logo='')", (uid,)).fetchone()
            return r["id"] if r else None

    def pendientes_cv(self):
        with self._c() as c:
            return [r["id"] for r in c.execute("SELECT id FROM ofertas WHERE cv_estado='pendiente' ORDER BY score DESC")]

    def contar(self):
        with self._c() as c:
            out = {r["nivel"]: r["n"] for r in c.execute(
                "SELECT nivel, COUNT(*) n FROM ofertas WHERE estado!='descartada' GROUP BY nivel")}
            out["nuevas"] = c.execute("SELECT COUNT(*) n FROM ofertas WHERE estado='nueva' AND nivel!='filtrada'").fetchone()["n"]
            for e in ("favorita", "aplicada", "descartada"):
                out[e] = c.execute("SELECT COUNT(*) n FROM ofertas WHERE estado=?", (e,)).fetchone()["n"]
            out["total"] = c.execute("SELECT COUNT(*) n FROM ofertas").fetchone()["n"]
            return out

    def vacia(self):
        with self._c() as c:
            return c.execute("SELECT COUNT(*) n FROM ofertas").fetchone()["n"] == 0

    # ------------------------------------------------------------------ pasadas y alertas
    def add_pasada(self, p):
        with self.lock, self._c() as c:
            cols = list(p)
            return c.execute(f"INSERT INTO pasadas ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                             [p[k] for k in cols]).lastrowid

    def pasadas(self, n=10):
        with self._c() as c:
            return [dict(r) for r in c.execute("SELECT * FROM pasadas ORDER BY id DESC LIMIT ?", (n,))]

    def ultima_pasada_inicio(self, tipo=None):
        """Inicio de la última pasada; tipo 'completa' o 'rapida' (None = cualquiera)."""
        with self._c() as c:
            if tipo == "completa":
                r = c.execute("SELECT inicio FROM pasadas WHERE COALESCE(tipo,'completa')='completa' "
                              "ORDER BY id DESC LIMIT 1").fetchone()
            elif tipo:
                r = c.execute("SELECT inicio FROM pasadas WHERE tipo=? ORDER BY id DESC LIMIT 1", (tipo,)).fetchone()
            else:
                r = c.execute("SELECT inicio FROM pasadas ORDER BY id DESC LIMIT 1").fetchone()
            return r["inicio"] if r else None

    def ultima_pasada_ok(self):
        with self._c() as c:
            r = c.execute("SELECT fin FROM pasadas WHERE (error IS NULL OR error='') AND tarjetas>0 "
                          "ORDER BY id DESC LIMIT 1").fetchone()
            return r["fin"] if r else None

    def add_alerta(self, clave, texto, tipo=None, oferta_id=None, datos=None):
        with self.lock, self._c() as c:
            return c.execute("INSERT OR IGNORE INTO alertas (clave, texto, ts, tipo, oferta_id, datos) VALUES (?,?,?,?,?,?)",
                             (clave, texto, time.time(), tipo, oferta_id,
                              json.dumps(datos, ensure_ascii=False) if datos is not None else None)).rowcount > 0

    @staticmethod
    def _alerta(r):
        d = dict(r)
        if d.get("datos"):
            try:
                d["datos"] = json.loads(d["datos"])
            except ValueError:
                pass
        return d

    def alertas_desde(self, desde):
        with self._c() as c:
            return [self._alerta(r) for r in c.execute("SELECT * FROM alertas WHERE id>? ORDER BY id LIMIT 20", (desde,))]

    def alertas_recientes(self, horas=72, tipo=None):
        """tipo None = solo las de estado del radar (las que salen como aviso en el panel)."""
        with self._c() as c:
            sql = "SELECT * FROM alertas WHERE ts>? AND " + ("tipo IS NULL" if tipo is None else "tipo=?")
            args = [time.time() - horas * 3600] + ([] if tipo is None else [tipo])
            return [self._alerta(r) for r in c.execute(sql + " ORDER BY id DESC", args)]

    # ------------------------------------------------------------------ candidaturas
    def add_evento(self, oid, fase=None, nota=None, ts=None):
        """Apunta un paso (o una nota) en la candidatura. Con fase, la oferta pasa a esa fase."""
        ts = ts or time.time()
        with self.lock, self._c() as c:
            eid = c.execute("INSERT INTO eventos (oferta_id, ts, fase, nota) VALUES (?,?,?,?)",
                            (oid, ts, fase, (nota or "").strip() or None)).lastrowid
            if fase:
                c.execute("UPDATE ofertas SET fase=?, fase_ts=? WHERE id=?", (fase, ts, oid))
                if fase == "aplicada":
                    c.execute("UPDATE ofertas SET estado='aplicada' WHERE id=?", (oid,))
            return eid

    def borrar_evento(self, eid):
        with self.lock, self._c() as c:
            r = c.execute("SELECT oferta_id FROM eventos WHERE id=?", (eid,)).fetchone()
            if not r:
                return
            c.execute("DELETE FROM eventos WHERE id=?", (eid,))
            # la fase vuelve a ser la del último paso que quede
            u = c.execute("SELECT fase, ts FROM eventos WHERE oferta_id=? AND fase IS NOT NULL ORDER BY ts DESC, id DESC "
                          "LIMIT 1", (r["oferta_id"],)).fetchone()
            c.execute("UPDATE ofertas SET fase=?, fase_ts=? WHERE id=?",
                      (u["fase"] if u else None, u["ts"] if u else None, r["oferta_id"]))

    def eventos(self, oid):
        with self._c() as c:
            return [dict(r) for r in c.execute("SELECT * FROM eventos WHERE oferta_id=? ORDER BY ts, id", (oid,))]

    def quitar_candidatura(self, oid):
        """Desmarcar «Aplicada» por error: se borra el seguimiento de esa oferta."""
        with self.lock, self._c() as c:
            c.execute("DELETE FROM eventos WHERE oferta_id=?", (oid,))
            c.execute("UPDATE ofertas SET fase=NULL, fase_ts=NULL WHERE id=?", (oid,))

    def candidaturas(self):
        """Todas las ofertas con candidatura, con su primer y último movimiento."""
        with self._c() as c:
            filas = c.execute(f"""SELECT {LISTA_COLS},
                (SELECT MIN(ts) FROM eventos e WHERE e.oferta_id=o.id AND e.fase='aplicada') AS aplicada_ts,
                (SELECT MAX(ts) FROM eventos e WHERE e.oferta_id=o.id) AS ultimo_ts,
                (SELECT COUNT(*) FROM eventos e WHERE e.oferta_id=o.id AND e.nota IS NOT NULL) AS n_notas
                FROM ofertas o WHERE fase IS NOT NULL ORDER BY ultimo_ts DESC""").fetchall()
            return [self._dict(r) for r in filas]

    def sin_respuesta(self, dias):
        """Candidaturas en fase activa sin ningún movimiento desde hace 'dias'. Devuelve (oferta, id último evento)."""
        with self._c() as c:
            filas = c.execute(f"""SELECT o.id, o.titulo, o.empresa, o.fase,
                (SELECT MAX(ts) FROM eventos e WHERE e.oferta_id=o.id) AS ultimo_ts,
                (SELECT MAX(id) FROM eventos e WHERE e.oferta_id=o.id) AS ultimo_ev
                FROM ofertas o WHERE fase IN ({','.join('?' * len(FASES_ACTIVAS))})""", FASES_ACTIVAS).fetchall()
            limite = time.time() - dias * 86400
            return [dict(r) for r in filas if r["ultimo_ts"] and r["ultimo_ts"] <= limite]

    def resumen_candidaturas(self, dias):
        with self._c() as c:
            activas = c.execute(f"SELECT COUNT(*) n FROM ofertas WHERE fase IN ({','.join('?' * len(FASES_ACTIVAS))})",
                                FASES_ACTIVAS).fetchone()["n"]
            total = c.execute("SELECT COUNT(*) n FROM ofertas WHERE fase IS NOT NULL").fetchone()["n"]
        return {"activas": activas, "total": total, "pendientes": len(self.sin_respuesta(dias)) if dias else 0}

    def mejores_sin_abrir(self, desde_ts, n, niveles):
        with self._c() as c:
            return [dict(r) for r in c.execute(
                f"SELECT id, titulo, empresa, score, nivel, modalidad, sueldo_min, sueldo_max FROM ofertas "
                f"WHERE creado>=? AND estado='nueva' AND nivel IN ({','.join('?' * len(niveles))}) "
                f"ORDER BY score DESC LIMIT ?", [desde_ts, *niveles, n])]

    def max_alerta(self):
        with self._c() as c:
            return c.execute("SELECT COALESCE(MAX(id),0) m FROM alertas").fetchone()["m"]
