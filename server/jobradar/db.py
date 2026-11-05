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
"""
JSON_COLS = ("desglose", "encaje", "cv_cambios")
LISTA_COLS = ("id, uid, titulo, empresa, lugar, km, modalidad, fecha_pub, url, sueldo_txt, sueldo_min, sueldo_max, "
              "candidatos, seniority, tipo_empleo, anios_pedidos, idioma, rol, score, nivel, desglose, encaje, filtro, "
              "estado, cv_estado, cv_idioma, cv_archivo, cv_cambios, cv_error, creado")


class DB:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        with self._c() as c:
            c.executescript(ESQUEMA)

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

    def listar(self, nivel=None, estado=None, q=None, modalidad=None, filtradas=False, desde_id=None,
               solo_listas=False, solo_aviso=False, limite=300):
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
        sql += " ORDER BY id ASC" if desde_id is not None else " ORDER BY (estado='nueva') DESC, score DESC, id DESC"
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
                "tipo_empleo, candidatos, score, nivel FROM ofertas WHERE estado != 'descartada'")]

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

    def ultima_pasada_inicio(self):
        with self._c() as c:
            r = c.execute("SELECT inicio FROM pasadas ORDER BY id DESC LIMIT 1").fetchone()
            return r["inicio"] if r else None

    def ultima_pasada_ok(self):
        with self._c() as c:
            r = c.execute("SELECT fin FROM pasadas WHERE (error IS NULL OR error='') AND tarjetas>0 "
                          "ORDER BY id DESC LIMIT 1").fetchone()
            return r["fin"] if r else None

    def add_alerta(self, clave, texto):
        with self.lock, self._c() as c:
            return c.execute("INSERT OR IGNORE INTO alertas (clave, texto, ts) VALUES (?,?,?)",
                             (clave, texto, time.time())).rowcount > 0

    def alertas_desde(self, desde):
        with self._c() as c:
            return [dict(r) for r in c.execute("SELECT * FROM alertas WHERE id>? ORDER BY id LIMIT 20", (desde,))]

    def alertas_recientes(self, horas=72):
        with self._c() as c:
            return [dict(r) for r in c.execute("SELECT * FROM alertas WHERE ts>? ORDER BY id DESC",
                                               (time.time() - horas * 3600,))]

    def max_alerta(self):
        with self._c() as c:
            return c.execute("SELECT COALESCE(MAX(id),0) m FROM alertas").fetchone()["m"]
