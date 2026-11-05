"""Baremo de 0 a 100, explicado punto a punto, según tus prioridades.

| Criterio                         | Máx | Cómo                                                                 |
|----------------------------------|-----|----------------------------------------------------------------------|
| Modalidad y distancia a Limpias  |  30 | remoto 30 · híbrido 25→12 según km · presencial 18→5 según km         |
| Tipo de puesto                   |  20 | backend / Java / analista programador 20 · analista funcional 15 ...  |
| Encaje del stack                 |  25 | Java, Spring, Batch, SQL, microservicios, Python... (resta si el      |
|                                  |     | lenguaje principal es otro: .NET, PHP, Node...)                       |
| Experiencia pedida               |  10 | lo que piden frente a tus años                                        |
| Sueldo publicado                 |  10 | ≥ objetivo 10 · ≥ mínimo 7 · sin publicar 3 · por debajo del mínimo −15 |
| Frescura y competencia           |   5 | publicada hace < 24 h, pocos candidatos                               |

Fuera de tu zona sin ser remoto, empresa excluida o prácticas -> filtrada (se guarda, no se avisa).
Todos los números se cambian desde la app (⚙ → Baremo) o en config.json -> "pesos", sin tocar código.
"""
import copy
import datetime as dt
import re

from . import geo
from .util import norm

PESOS = {
    "remoto": 30,
    "hibrido": [[20, 25], [40, 22], [60, 18], [80, 12]],      # [hasta km, puntos]
    "presencial": [[20, 18], [40, 14], [60, 10], [80, 5]],
    "remoto_con_oficina": -25,
    "rol": {"backend": 20, "java": 20, "analista_programador": 20, "analista_funcional": 15, "fullstack": 12,
            "desarrollador": 14, "lider": 12, "data": 8, "otro": 4},
    "stack_max": 25,
    "lenguaje_ajeno": -15,
    "experiencia": {"encaja": 10, "algo_mas": 5, "mucho_mas": 0, "junior": 3, "sin_dato": 6,
                    "margen_encaja": 1, "margen_algo_mas": 3},  # años por encima de los tuyos que aún cuentan
    "sueldo": {"objetivo": 10, "minimo": 7, "sin_publicar": 3, "por_debajo": -15},
    "fresca_24h": 3, "pocos_candidatos": 2, "muchos_candidatos": -2,
    "temporal": -5,
}

# tecnología -> (regex, puntos). Son las de tu CV; lo que no tienes no suma.
STACK = [
    ("Java", r"\bjava\b(?!\s*script)", 6),
    ("Spring Boot", r"spring\s*boot", 5),
    ("Spring", r"\bspring\b(?!\s*(boot|batch))", 2),
    ("Spring Batch", r"spring\s*batch", 4),
    ("Batch", r"\bbatch\b|procesos? por lotes", 1),
    ("Hibernate/JPA", r"hibernate|\bjpa\b", 2),
    ("Microservicios", r"micro-?servic", 3),
    ("API REST", r"\bapi(s)?\s*rest|restful|rest\s*api", 2),
    ("SQL", r"\bsql\b|\boracle\b|postgre|mysql|\bdb2\b|pl/sql", 3),
    ("Python", r"\bpython\b", 3),
    ("JUnit/Mockito", r"junit|mockito|tests? unitari|unit test", 2),
    ("Docker", r"\bdocker\b", 1),
    ("Jenkins/CI", r"jenkins|ci/cd|integracion continua|continuous integration", 1),
    ("Git", r"\bgit\b|github|gitlab", 1),
    ("Maven", r"\bmaven\b", 1),
    ("AWS", r"\baws\b|amazon web services", 2),
    ("Sonar", r"sonar", 1),
    ("Hexagonal/DDD", r"hexagonal|\bddd\b|domain[- ]driven", 2),
    ("Scrum/Agile", r"scrum|agile|agil", 1),
    ("Cobol (migración)", r"\bcobol\b", 2),
    ("Análisis funcional", r"analisis funcional|toma de requisitos|requisitos funcionales|functional analysis|requirements gathering", 2),
    ("Sector energía", r"energ(ia|y)|utilities|electric", 1),
]
# tecnologías que suelen aparecer y no están en tu CV (solo se muestran, no restan salvo lenguaje principal)
AJENAS = [
    ("Kubernetes", r"kubernetes|\bk8s\b|openshift"), ("Kafka", r"\bkafka\b"), ("Angular", r"\bangular\b"),
    ("React", r"\breact\b"), ("Node.js", r"node\.?js|\bnode\b"), (".NET/C#", r"\.net\b|\bc#|csharp"),
    ("PHP", r"\bphp\b"), ("Go", r"\bgolang\b|\bgo\b(?= developer| lang)"), ("Scala", r"\bscala\b"),
    ("Kotlin", r"\bkotlin\b"), ("Azure", r"\bazure\b"), ("GCP", r"\bgcp\b|google cloud"),
    ("MongoDB", r"mongo"), ("Quarkus", r"quarkus"), ("Terraform", r"terraform"), ("RabbitMQ", r"rabbit"),
    ("Elasticsearch", r"elastic"), ("Redis", r"\bredis\b"), ("WebFlux/Reactive", r"webflux|reactiv"),
]
PESOS["stack"] = {nombre: pts for nombre, _, pts in STACK}

ETIQ = {"hibrido": "Híbrido", "presencial": "Presencial", "remoto": "Remoto"}
LENGUAJE_AJENO = r"\.net\b|\bc#|\bphp\b|node\.?js|\bgolang\b|\bruby\b|\bscala\b|\bsalesforce\b|\babap\b"


def contiene(termino, texto):
    """¿Aparece el término como palabra suelta? ("qa" no casa con "aqua"; ".net" y "c#" funcionan)."""
    t = norm(termino)
    return bool(t) and re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", norm(texto)) is not None


def rol_de(titulo):
    t = norm(titulo)
    if re.search(r"analista programador|programador analista|analyst programmer", t):
        return "analista_programador", "Analista programador"
    if re.search(r"back[- ]?end", t):
        return "backend", "Backend"
    if re.search(r"\bjava\b|spring", t):
        return "java", "Desarrollo Java"
    if re.search(r"full[- ]?stack", t):
        return "fullstack", "Full stack"
    if re.search(r"analista funcional|analista de negocio|business analyst|functional analyst|analista de sistemas|analista tecnico|analista it|\banalista\b", t):
        return "analista_funcional", "Analista"
    if re.search(r"tech lead|team lead|lider tecnico|arquitect|architect|jefe de proyecto|responsable", t):
        return "lider", "Liderazgo / arquitectura"
    if re.search(r"data engineer|ingeniero de datos|etl|big data", t):
        return "data", "Datos"
    if re.search(r"desarrollador|developer|programador|ingenier[oa] (de )?software|software engineer|devops", t):
        return "desarrollador", "Desarrollo (genérico)"
    return "otro", "Otro"


def modalidad_real(modo, desc):
    """El listado dice remoto/híbrido/presencial por el filtro; la descripción a veces lo contradice."""
    d = norm(desc)
    if modo == "remoto":
        if re.search(r"\d\s*(dias?|days?)\b[^.\n]{0,45}(oficina|office|presencial|on-?site|instalaciones)", d) \
                or re.search(r"(modelo|formato|modalidad|regimen)\s*(de trabajo\s*)?hibrid|hybrid\s*(model|work|role|position)"
                             r"|presencialidad|(acudir|ir|venir|desplazarte) a (la|nuestra|nuestras) oficina", d):
            return "remoto?"
    return modo


def sueldo(txt):
    """(min, max) anual en euros, o (None, None). Entiende '35.000 € - 42.000 €', '35-42K', '€40,000/año', '2.800 €/mes'."""
    t = norm(txt).replace(" ", " ")
    if not t:
        return None, None
    mensual = bool(re.search(r"/\s*mes|al mes|mensual|per month|/mo\b|/month", t))
    valores = []
    for m in re.finditer(r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*(k|mil)?", t):
        num, k = m.group(1), m.group(2)
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", num):
            v = float(re.sub(r"[.,]", "", num))
        else:
            v = float(num.replace(",", "."))
        if k:
            v *= 1000
        valores.append(v)
    # "35-42K": el primer número hereda la k del segundo
    if len(valores) >= 2 and valores[0] < 1000 <= valores[1] and re.search(r"\d\s*[-–a]\s*\d+(?:[.,]\d+)?\s*k", t):
        valores[0] *= 1000
    if mensual:
        valores = [v * 12 for v in valores if 800 <= v <= 12000]
    valores = [v for v in valores if 12000 <= v <= 250000]
    if not valores:
        return None, None
    return int(min(valores)), int(max(valores))


_SAL_CONTEXTO = r"(salario|sueldo|retribucion|remuneracion|banda salarial|rango salarial|salary|compensation|brutos?|€|eur\b|k€)"


def sueldo_en_texto(desc):
    """Busca el sueldo en la descripción, solo en líneas que hablan de dinero."""
    for linea in (desc or "").split("\n"):
        n = norm(linea)
        if re.search(_SAL_CONTEXTO, n) and re.search(r"\d", n) and not re.search(r"facturacion|millones|empleados|clientes", n):
            a, b = sueldo(linea)
            if a:
                return linea.strip()[:160], a, b
    return "", None, None


def anios_pedidos(desc):
    d = norm(desc)
    pats = [r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:anos|years?)\s*(?:de|of)?\s*(?:experiencia|experience)",
            r"(?:experiencia|experience)[^.\n]{0,40}?(?:minima|minimum|al menos|at least|de|of)?\s*(\d{1,2})\s*\+?\s*(?:anos|years?)"]
    vals = []
    for p in pats:
        vals += [int(x) for x in re.findall(p, d)]
    vals = [v for v in vals if 0 < v <= 20]
    return min(vals) if vals else None


def idioma(desc):
    d = " " + norm(desc) + " "
    es = sum(d.count(f" {w} ") for w in ("de", "la", "que", "el", "en", "y", "para", "con", "los", "experiencia", "las"))
    en = sum(d.count(f" {w} ") for w in ("the", "and", "with", "for", "you", "we", "experience", "our", "to", "of"))
    return "en" if en > es * 1.2 else "es"


def _tramo(tabla, km):
    for lim, pts in sorted(tabla, key=lambda t: t[0]):
        if km <= lim:
            return pts
    return None


def pesos(cfg):
    """Baremo efectivo: el de serie con lo que hayas cambiado encima (clave a clave dentro de cada grupo)."""
    P = copy.deepcopy(PESOS)
    for k, v in (cfg.get("pesos") or {}).items():
        if isinstance(v, dict) and isinstance(P.get(k), dict):
            P[k] = {**P[k], **v}
        elif k in P:
            P[k] = v
    return P


def maximo(P):
    """Puntos máximos que puede sacar una oferta con este baremo (para avisar si los niveles no cuadran)."""
    mejor_modo = max([P["remoto"]] + [p for _, p in P["hibrido"]] + [p for _, p in P["presencial"]] or [0])
    return (mejor_modo + max(P["rol"].values() or [0]) + min(P["stack_max"], sum(max(0, x) for x in P["stack"].values()))
            + max(0, *[v for k, v in P["experiencia"].items() if not k.startswith("margen")])
            + max(0, *P["sueldo"].values()) + max(0, P["fresca_24h"]) + max(0, P["pocos_candidatos"]))


def puntuar(o, cfg, ahora=None):
    """o: dict con titulo, empresa, lugar, modo, descripcion, sueldo_txt, seniority, tipo_empleo, candidatos, fecha_pub.
    Devuelve dict con score, nivel, desglose, filtro (motivo o ''), km, modalidad, rol, sueldo_min/max, encaje."""
    P = pesos(cfg)
    per = cfg["perfil"]
    titulo, desc = o.get("titulo", ""), o.get("descripcion", "")
    ntit, ntodo = norm(titulo), norm(titulo + "\n" + desc)
    des, filtro = [], ""

    # --- filtros duros
    for ex in cfg.get("excluir_empresas") or []:
        if ex and norm(ex) in norm(o.get("empresa", "")):
            filtro = f"Empresa excluida ({ex})"
    pre = prefiltro(titulo, cfg)
    filtro = filtro or pre
    tipo = norm(o.get("tipo_empleo", ""))
    if re.search(r"practicas|internship|beca", tipo):
        filtro = filtro or "Prácticas"

    # --- modalidad y distancia
    modo = modalidad_real(o.get("modo", ""), desc)
    km = geo.km_desde(per.get("origen", "Limpias"), o.get("lugar", ""))
    if modo == "remoto":
        des.append(["Remoto (toda España)", P["remoto"]])
    elif modo == "remoto?":
        des.append(["Sale como remoto pero la descripción pide ir a la oficina", P["remoto"] + P["remoto_con_oficina"]])
        if km is not None and km > per["zona_max_km"]:
            filtro = filtro or f"Pide oficina y está a ~{km} km"
    else:
        if km is None and geo.en_region(o.get("lugar", "")):
            km = 50  # "Cantabria, España" sin ciudad
        pts = _tramo(P.get(modo) or P["presencial"], km) if km is not None else None
        if km is None:
            filtro = filtro or f"{ETIQ.get(modo, modo)} en ubicación no reconocida ({o.get('lugar') or '?'})"
        elif km > per["zona_max_km"] or pts is None:
            filtro = filtro or f"{ETIQ.get(modo, modo)} a ~{km} km de {per.get('origen', 'Limpias')}"
        else:
            des.append([f"{ETIQ.get(modo, modo)} a ~{km} km", pts])

    # --- tipo de puesto
    rol, rol_txt = rol_de(titulo)
    des.append([f"Puesto: {rol_txt}", P["rol"].get(rol, 4)])

    # --- stack
    tiene, suma = [], 0
    for nombre, rx, pts in STACK:
        if re.search(rx, ntodo):
            tiene.append(nombre)
            suma += P["stack"].get(nombre, pts)
    falta = [n for n, rx in AJENAS if re.search(rx, ntodo)]
    des.append([f"Stack: {', '.join(tiene[:6]) or 'nada de tu stack'}", min(P["stack_max"], suma)])
    ajeno_tit = re.search(LENGUAJE_AJENO, ntit)
    java_py = re.search(r"\bjava\b(?!\s*script)|\bpython\b", ntodo)
    if ajeno_tit or (not java_py and len(re.findall(LENGUAJE_AJENO, ntodo)) >= 2):
        des.append(["Lenguaje principal distinto de Java/Python", P["lenguaje_ajeno"]])

    # --- experiencia
    E = P["experiencia"]
    pide = anios_pedidos(desc)
    yo = int(per.get("anios_experiencia", 5))
    sen = norm(o.get("seniority", ""))
    if re.search(r"\bjunior\b|\bjr\b|trainee|sin experiencia|entry level|recien titulad", ntit + " " + sen):
        des.append(["Puesto junior", E["junior"]])
    elif pide is None:
        des.append(["Experiencia no indicada", E["sin_dato"]])
    elif pide <= yo + E["margen_encaja"]:
        des.append([f"Piden {pide} años (tienes {yo}+)", E["encaja"]])
    elif pide <= yo + E["margen_algo_mas"]:
        des.append([f"Piden {pide} años", E["algo_mas"]])
    else:
        des.append([f"Piden {pide} años", E["mucho_mas"]])

    # --- sueldo
    S = P["sueldo"]
    s_txt = o.get("sueldo_txt") or ""
    smin, smax = sueldo(s_txt)
    if not smin:
        s_txt, smin, smax = sueldo_en_texto(desc)
    if smax:
        rango = f"{smin // 1000}–{smax // 1000}k" if smin != smax else f"{smax // 1000}k"
        if smax >= per["sueldo_objetivo"]:
            des.append([f"Sueldo {rango} (≥ objetivo)", S["objetivo"]])
        elif smax >= per["sueldo_minimo"]:
            des.append([f"Sueldo {rango} (≥ mínimo)", S["minimo"]])
        else:
            des.append([f"Sueldo {rango} (< tu mínimo de {per['sueldo_minimo'] // 1000}k)", S["por_debajo"]])
    else:
        des.append(["Sueldo sin publicar", S["sin_publicar"]])

    # --- frescura y competencia
    ahora = ahora or dt.datetime.now()
    try:
        f = dt.datetime.fromisoformat((o.get("fecha_pub") or "")[:10])
        if (ahora - f).days <= 1:
            des.append(["Publicada hace menos de 24 h", P["fresca_24h"]])
    except ValueError:
        pass
    cand = o.get("candidatos")
    if cand is not None and cand < 25:
        des.append([f"{cand} candidatos", P["pocos_candidatos"]])
    elif cand is not None and cand > 200:
        des.append(["Más de 200 candidatos", P["muchos_candidatos"]])
    if re.search(r"temporal|temporary|contract", tipo) and not re.search(r"indefinid|full", tipo):
        des.append(["Contrato temporal", P["temporal"]])

    score = max(0, min(100, sum(p for _, p in des)))
    N = cfg.get("niveles") or {}
    if filtro:
        nivel = "filtrada"
    elif score >= N.get("prioritaria", 75):
        nivel = "prioritaria"
    elif score >= N.get("interesante", 58):
        nivel = "interesante"
    elif score >= N.get("vigilar", 40):
        nivel = "vigilar"
    else:
        nivel = "baja"
    return {"score": score, "nivel": nivel, "desglose": des, "filtro": filtro, "km": km, "modalidad": modo,
            "rol": rol, "sueldo_min": smin, "sueldo_max": smax, "sueldo_txt": s_txt or o.get("sueldo_txt") or "",
            "anios_pedidos": pide, "encaje": {"tiene": tiene, "falta": falta}, "idioma": idioma(desc or titulo)}


def prefiltro(titulo, cfg):
    """Antes de abrir el detalle: descarta por título para no pedir de más a LinkedIn."""
    for ex in cfg.get("excluir_titulo") or []:
        if contiene(ex, titulo):
            return f"Título excluido («{ex.strip()}»)"
    return ""


def recalcular(db, cfg):
    """Vuelve a puntuar todas las ofertas guardadas con el baremo actual. Devuelve cuántas cambian de nivel."""
    cambian, total = 0, 0
    for o in db.para_recalcular():
        if o["nivel"] == "filtrada" and not o.get("descripcion"):
            continue  # descartada por título o duplicada: no hay datos para puntuarla
        modo = "remoto" if (o.get("modalidad") or "").startswith("remoto") else o.get("modalidad")
        p = puntuar({**o, "modo": modo}, cfg)
        total += 1
        if p["score"] != o["score"] or p["nivel"] != o["nivel"]:
            cambian += o["nivel"] != p["nivel"]
            db.actualizar(o["id"], score=p["score"], nivel=p["nivel"], desglose=p["desglose"], filtro=p["filtro"],
                          km=p["km"], modalidad=p["modalidad"], encaje=p["encaje"])
    return {"revisadas": total, "cambian_nivel": cambian}


NIVELES_DEFECTO = {"prioritaria": 75, "interesante": 58, "vigilar": 40}


def validar_pesos(nuevos):
    """Se queda solo con claves conocidas y números enteros. Lanza ValueError si algo no cuadra."""
    def num(v, donde):
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            raise ValueError(f"«{donde}» tiene que ser un número")
    out = {}
    for k, base in PESOS.items():
        if k not in nuevos:
            continue
        v = nuevos[k]
        if isinstance(base, dict):
            if not isinstance(v, dict):
                raise ValueError(f"«{k}» mal formado")
            out[k] = {kk: num(vv, f"{k}.{kk}") for kk, vv in v.items() if kk in base}
        elif isinstance(base, list):
            tramos = [[num(t[0], f"{k} km"), num(t[1], f"{k} puntos")] for t in v if isinstance(t, (list, tuple)) and len(t) == 2]
            if not tramos:
                raise ValueError(f"«{k}» necesita al menos un tramo")
            out[k] = sorted(tramos)
        else:
            out[k] = num(v, k)
    return out


def validar_niveles(n):
    out = {k: int(n.get(k, d)) for k, d in NIVELES_DEFECTO.items()}
    if not out["prioritaria"] > out["interesante"] > out["vigilar"] >= 0:
        raise ValueError("Los niveles tienen que ir de mayor a menor: prioritaria > interesante > a vigilar")
    return out
