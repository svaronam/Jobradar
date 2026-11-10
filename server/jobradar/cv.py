"""Tu CV base y su adaptación a cada oferta.

CV base: data/cv/base_es.json y base_en.json (estructurado) + el PDF que subiste (base_es.pdf / base_en.pdf).
Al subir un PDF nuevo se extrae su texto (pdftotext) y Gemini lo estructura.

Adaptación: Gemini reordena las viñetas y las habilidades según la oferta, reescribe el extracto del perfil
y puede reformular viñetas. Después, una guarda en Python comprueba cada texto nuevo:
  - no puede nombrar tecnologías que no estén ya en tu CV,
  - no puede meter cifras que no estuvieran en esa viñeta,
  - no puede atribuirte liderazgo, seniority o cargos que el CV no dice,
y si algo falla se queda la frase original. Empresas, fechas, puestos y formación no se tocan nunca.
Sin API key (o si Gemini falla) se adapta por reglas: solo reordena según las palabras de la oferta.
"""
import copy
import json
import logging
import os
import re
import subprocess
import time

from . import gemini, pdfcv, puntuar
from .util import norm

log = logging.getLogger("jobradar")
IDIOMAS = ("es", "en")
SECCIONES = ["educacion", "experiencia", "proyectos", "habilidades"]

# vocabulario técnico para la guarda: si una frase nueva nombra algo de aquí que tu CV no tiene, se descarta
VOCAB = [
    r"\bjava\b(?!\s*script)", r"spring", r"kotlin", r"python", r"\bsql\b", r"oracle", r"postgre", r"mysql", r"\bdb2\b",
    r"mongo", r"redis", r"kafka", r"rabbit", r"docker", r"kubernetes|\bk8s\b", r"openshift", r"\baws\b",
    r"azure", r"\bgcp\b|google cloud", r"jenkins", r"\bgit\b", r"github", r"gitlab", r"sonar", r"maven", r"gradle",
    r"tomcat", r"junit", r"mockito", r"hibernate", r"\bjpa\b", r"react", r"angular", r"\bvue\b", r"node",
    r"typescript", r"javascript", r"\.net\b", r"\bc#", r"\bphp\b", r"golang", r"\bscala\b", r"terraform", r"ansible",
    r"linux", r"graphql", r"\bsoap\b", r"cobol", r"hexagonal", r"\bddd\b", r"\bmvc\b", r"scrum", r"\bjira\b",
    r"tailscale", r"android", r"claude", r"gemini", r"elastic", r"airflow", r"\bspark\b", r"hadoop", r"quarkus",
    r"micronaut", r"webflux", r"cassandra", r"dynamo", r"lambda", r"\bs3\b", r"\bec2\b", r"selenium", r"cucumber",
    r"kibana", r"grafana", r"prometheus", r"splunk", r"\bsap\b", r"salesforce", r"power ?bi", r"tableau", r"\buml\b",
    r"bpmn", r"togaf", r"\bitil\b", r"kanban", r"safe\b", r"oauth", r"keycloak", r"openapi|swagger", r"postman",
    r"jmeter", r"camunda", r"mulesoft", r"\betl\b", r"datadog", r"new relic", r"dynatrace", r"helm", r"argo",
]
CARGOS = r"\blider|\blidere|\bliderando|\bled\b|\blead\b|\bmanag|\bgestione (un|el) equipo|\bsenior\b|\barquitect|" \
         r"\barchitect|\bjefe\b|\bresponsable de\b|\bhead of\b|\bmentor"


# ------------------------------------------------------------------ CV base

def ruta(cfg, idioma, ext="json"):
    return os.path.join(cfg["data_dir"], "cv", f"base_{idioma}.{ext}")


def base(cfg, idioma):
    p = ruta(cfg, idioma)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def info(cfg):
    out = {}
    for i in IDIOMAS:
        j, p = ruta(cfg, i), ruta(cfg, i, "pdf")
        out[i] = {"json": os.path.exists(j), "pdf": os.path.exists(p),
                  "actualizado": os.path.getmtime(j) if os.path.exists(j) else None,
                  "datos": base(cfg, i)}
    return out


def _escribir(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def validar(cv):
    """Comprueba la forma mínima que necesita el generador. Lanza ValueError con un mensaje claro."""
    if not isinstance(cv, dict) or not cv.get("nombre"):
        raise ValueError("Falta el nombre")
    for k in ("experiencia", "habilidades"):
        if not isinstance(cv.get(k), list) or not cv[k]:
            raise ValueError(f"Falta la sección «{k}»")
    for ex in cv["experiencia"]:
        if not ex.get("puesto") or not isinstance(ex.get("logros"), list):
            raise ValueError("Cada experiencia necesita puesto y logros")
    for hb in cv["habilidades"]:
        if not hb.get("categoria") or not isinstance(hb.get("items"), list):
            raise ValueError("Cada grupo de habilidades necesita categoría e items")
    return cv


def guardar_json(cfg, idioma, cv):
    if idioma not in IDIOMAS:
        raise ValueError("Idioma no válido")
    cv = validar(cv)
    cv["idioma"] = idioma
    _escribir(ruta(cfg, idioma), cv)


CV_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "nombre": {"type": "STRING"}, "titular": {"type": "STRING"},
        "contacto": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "texto": {"type": "STRING"}, "url": {"type": "STRING"}}, "required": ["texto"]}},
        "portfolio": {"type": "OBJECT", "properties": {"etiqueta": {"type": "STRING"}, "texto": {"type": "STRING"},
                                                       "url": {"type": "STRING"}}},
        "perfil": {"type": "STRING"},
        "secciones": {"type": "OBJECT", "properties": {k: {"type": "STRING"} for k in SECCIONES}},
        "educacion": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            k: {"type": "STRING"} for k in ("centro", "lugar", "titulo", "fechas", "detalle")}, "required": ["centro"]}},
        "experiencia": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            **{k: {"type": "STRING"} for k in ("puesto", "empresa", "lugar", "fechas")},
            "logros": {"type": "ARRAY", "items": {"type": "STRING"}}}, "required": ["puesto", "logros"]}},
        "proyectos": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            **{k: {"type": "STRING"} for k in ("nombre", "stack", "fechas")},
            "logros": {"type": "ARRAY", "items": {"type": "STRING"}}}, "required": ["nombre", "logros"]}},
        "habilidades": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "categoria": {"type": "STRING"}, "items": {"type": "ARRAY", "items": {"type": "STRING"}}},
            "required": ["categoria", "items"]}},
    },
    "required": ["nombre", "perfil", "experiencia", "habilidades"],
}


def subir(cfg, idioma, pdf):
    """Guarda el PDF subido y lo convierte en CV estructurado con Gemini. Devuelve un mensaje para la app."""
    if idioma not in IDIOMAS:
        raise ValueError("Idioma no válido")
    if not pdf.startswith(b"%PDF"):
        raise ValueError("Eso no parece un PDF")
    pdf_path = ruta(cfg, idioma, "pdf")
    with open(pdf_path + ".tmp", "wb") as f:
        f.write(pdf)
    texto = subprocess.run(["pdftotext", "-layout", pdf_path + ".tmp", "-"], capture_output=True, text=True,
                           timeout=60).stdout
    if len(texto.strip()) < 200:
        os.remove(pdf_path + ".tmp")
        raise ValueError("No consigo leer texto del PDF (¿es una imagen escaneada?)")
    os.replace(pdf_path + ".tmp", pdf_path)
    if not cfg.get("gemini_api_key"):
        return ("PDF guardado. Para convertirlo en el CV que adapta el bot hace falta la API key de Gemini "
                "(Ajustes). Mientras tanto se usa el CV estructurado que ya había." if base(cfg, idioma) else
                "PDF guardado, pero sin API key de Gemini no puedo estructurarlo. Ponla en Ajustes y vuelve a subirlo.")
    prompt = f"""Convierte este CV (texto extraído de un PDF) en JSON con el esquema indicado.
Copia los textos LITERALMENTE, sin resumir, corregir, traducir ni añadir nada. Idioma del CV: {idioma}.
- "logros": una cadena por viñeta. Marca con **dobles asteriscos** las palabras que en el original van en negrita
  si se nota (tecnologías, cifras clave); si no lo sabes, marca las tecnologías.
- "secciones": los títulos de sección tal cual aparecen (Educación/Education, Experiencia, ...).
- "contacto": cada dato de la línea de contacto (teléfono, email, LinkedIn, GitHub) con url si es un enlace
  (mailto: para el email, https:// para webs). "portfolio" aparte si existe.
- En proyectos, "stack" es la lista de tecnologías que aparece junto al nombre.
- En habilidades, "items" separados por comas tal cual (no partas "SQL (MySQL, Oracle...)").

TEXTO DEL CV:
{texto[:12000]}"""
    datos = gemini.generar(cfg, prompt, schema=CV_SCHEMA, temperature=0)
    datos = validar(datos)
    datos.setdefault("secciones", {})
    datos["idioma"] = idioma
    _escribir(ruta(cfg, idioma), datos)
    return (f"CV en {'español' if idioma == 'es' else 'inglés'} actualizado: {len(datos['experiencia'])} experiencias, "
            f"{sum(len(e['logros']) for e in datos['experiencia'])} viñetas y {len(datos['habilidades'])} grupos de habilidades. "
            "Revísalo abajo por si algo no se leyó bien.")


# ------------------------------------------------------------------ guarda

def _sin_md(t):
    return re.sub(r"\*\*", "", t or "")


def terminos(texto):
    n = norm(_sin_md(texto))
    return {rx for rx in VOCAB if re.search(rx, n)}


def _cifras(texto):
    return set(re.findall(r"\d+", _sin_md(texto)))


def texto_cv(cv):
    """Todo el texto del CV en una cadena (para saber qué tecnologías y cifras 'existen')."""
    return json.dumps(cv, ensure_ascii=False)


def _nombre_rx(rx):
    return re.sub(r"\\b|\(\?!.*?\)|[\\()?^$]", "", rx).split("|")[0].replace(" ?", " ").strip()


def problema(nuevo, original, todo_base, cifras_ref=None):
    """'' si la frase nueva es aceptable; si no, el motivo. cifras_ref: de dónde pueden salir las cifras."""
    if not nuevo or not nuevo.strip():
        return "vacía"
    extra = terminos(nuevo) - terminos(todo_base)
    if extra:
        return "nombra tecnologías que no están en tu CV (" + ", ".join(sorted(_nombre_rx(x) for x in extra))[:80] + ")"
    cif = _cifras(nuevo) - _cifras(original if cifras_ref is None else cifras_ref)
    if cif:
        return "añade cifras que no estaban (" + ", ".join(sorted(cif)) + ")"
    if re.search(CARGOS, norm(_sin_md(nuevo))) and not re.search(CARGOS, norm(_sin_md(original))):
        return "atribuye un cargo o liderazgo que no figura"
    if len(_sin_md(nuevo)) > max(360, len(_sin_md(original)) * 1.6):
        return "demasiado larga"
    return ""


# ------------------------------------------------------------------ adaptación

ADAPT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "titular": {"type": "STRING"},
        "perfil": {"type": "STRING"},
        "orden_secciones": {"type": "ARRAY", "items": {"type": "STRING", "enum": SECCIONES}},
        "experiencia": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "indice": {"type": "INTEGER"},
            "logros": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                "indice": {"type": "INTEGER"}, "texto": {"type": "STRING"}}, "required": ["indice", "texto"]}}},
            "required": ["indice", "logros"]}},
        "proyectos": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "indice": {"type": "INTEGER"},
            "logros": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                "indice": {"type": "INTEGER"}, "texto": {"type": "STRING"}}, "required": ["indice", "texto"]}}},
            "required": ["indice", "logros"]}},
        "habilidades": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "indice": {"type": "INTEGER"}, "items": {"type": "ARRAY", "items": {"type": "STRING"}}},
            "required": ["indice", "items"]}},
        "requisitos": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "requisito": {"type": "STRING"}, "cumple": {"type": "STRING", "enum": ["si", "parcial", "no"]},
            "evidencia": {"type": "STRING"}}, "required": ["requisito", "cumple"]}},
        "cambios": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["perfil", "experiencia", "habilidades", "requisitos", "cambios"],
}


def _indexado(cv):
    """El CV con índices visibles para que el modelo diga 'viñeta 2 de la experiencia 0'."""
    return {
        "titular": cv.get("titular", ""), "perfil": cv.get("perfil", ""),
        "experiencia": [{"indice": i, "puesto": e["puesto"], "empresa": e.get("empresa", ""), "fechas": e.get("fechas", ""),
                         "logros": [{"indice": j, "texto": t} for j, t in enumerate(e["logros"])]}
                        for i, e in enumerate(cv["experiencia"])],
        "proyectos": [{"indice": i, "nombre": p["nombre"], "logros": [{"indice": j, "texto": t} for j, t in enumerate(p["logros"])]}
                      for i, p in enumerate(cv.get("proyectos") or [])],
        "habilidades": [{"indice": i, "categoria": h["categoria"], "items": h["items"]} for i, h in enumerate(cv["habilidades"])],
        "educacion": cv.get("educacion", []),
    }


def _prompt(cv, o, idioma):
    lengua = "español" if idioma == "es" else "inglés"
    return f"""Eres un experto en selección IT. Adapta este CV a la oferta para que el reclutador vea enseguida el encaje.

REGLAS ESTRICTAS (si las rompes, el cambio se descarta automáticamente):
1. NO inventes nada: ni tecnologías, ni herramientas, ni cifras, ni cargos, ni responsabilidades, ni años de experiencia.
   Solo puedes usar lo que ya dice el CV. Si la oferta pide algo que el CV no tiene, NO lo añadas: apúntalo en
   "requisitos" con cumple="no".
2. "experiencia" y "proyectos": para cada entrada, devuelve TODAS sus viñetas (por su índice) en el orden que mejor
   encaje con la oferta (lo más relevante primero). Puedes reformular una viñeta para poner delante lo que pide la
   oferta, con los mismos hechos, en {lengua}, sin alargarla. Marca con **negrita** las palabras clave que pide la oferta
   y aparecen en la viñeta (máximo 4 por viñeta). Si no hace falta cambiarla, devuélvela igual.
3. "habilidades": todos los grupos (por índice) en el orden más útil, y dentro de cada grupo los MISMOS items
   reordenados (copiados literalmente). No añadas ni quites items.
4. "perfil": reescribe el extracto (3-4 líneas, {lengua}, en primera persona como el original) orientado a este puesto,
   usando solo hechos del CV. Puedes destacar con **negrita** 2-4 cosas.
5. "titular": la línea bajo el nombre, p. ej. "Back-End Developer | Java · Spring Boot". Solo con lo que ya hay en el CV.
6. "orden_secciones": las 4 secciones ({', '.join(SECCIONES)}) en el orden más conveniente para esta oferta.
7. Si la oferta pide un lenguaje o herramientas que el CV no tiene (p. ej. .NET, PHP, React), NO los menciones como
   propios: pon delante lo transferible que sí está en el CV (diseño de APIs REST y microservicios, SQL, procesos batch,
   testing, arquitectura hexagonal/DDD, Scrum, Git/CI, análisis) para que se vea que encaja igual.
8. "requisitos": los 5-10 requisitos principales de la oferta y si el CV los cumple (si/parcial/no), con la evidencia
   del CV en pocas palabras.
9. "cambios": 3-6 frases cortas en español explicando qué has cambiado y por qué.

OFERTA
Puesto: {o.get('titulo')}
Empresa: {o.get('empresa')}
Ubicación: {o.get('lugar')} ({o.get('modalidad')})
Descripción:
{(o.get('descripcion') or '')[:7000]}

CV (JSON con índices):
{json.dumps(_indexado(cv), ensure_ascii=False)}"""


def _aplicar(cv, r):
    """Mezcla la respuesta del modelo con el CV base pasando cada texto por la guarda. Devuelve (cv, revertidos)."""
    out = copy.deepcopy(cv)
    todo = texto_cv(cv)
    revertidos = []

    t = (r.get("titular") or "").strip()
    if t:
        mal = problema(t, cv.get("titular", ""), todo) if len(t) <= 80 else "demasiado largo"
        if mal:
            revertidos.append(f"Titular: {mal}")
        else:
            out["titular"] = t
    p = (r.get("perfil") or "").strip()
    if p:
        # en el perfil vale cualquier cifra que ya esté en el CV (años, nº de servicios...)
        mal = problema(p, cv.get("perfil", ""), todo, cifras_ref=todo) or (
            "" if len(_sin_md(p)) <= 650 else "demasiado largo")
        if mal:
            revertidos.append(f"Perfil: {mal}")
        else:
            out["perfil"] = p

    for clave in ("experiencia", "proyectos"):
        orig = cv.get(clave) or []
        por_indice = {e.get("indice"): e for e in (r.get(clave) or []) if isinstance(e, dict)}
        for i, entrada in enumerate(orig):
            res = por_indice.get(i)
            if not res:
                continue
            nuevas, usados = [], set()
            for lg in res.get("logros") or []:
                j = lg.get("indice")
                if not isinstance(j, int) or j in usados or not 0 <= j < len(entrada["logros"]):
                    continue
                usados.add(j)
                original = entrada["logros"][j]
                mal = problema(lg.get("texto", ""), original, todo)
                if mal:
                    revertidos.append(f"{entrada.get('puesto') or entrada.get('nombre')} · viñeta {j + 1}: {mal}")
                    nuevas.append(original)
                else:
                    nuevas.append(lg["texto"].strip())
            nuevas += [t for j, t in enumerate(entrada["logros"]) if j not in usados]  # nunca se pierde una viñeta
            out[clave][i]["logros"] = nuevas

    orig_h = cv["habilidades"]
    orden, usados = [], set()
    for h in r.get("habilidades") or []:
        i = h.get("indice")
        if not isinstance(i, int) or i in usados or not 0 <= i < len(orig_h):
            continue
        usados.add(i)
        base_items = orig_h[i]["items"]
        mapa = {norm(x): x for x in base_items}
        items, vistos = [], set()
        for x in h.get("items") or []:
            k = norm(x)
            if k in mapa and k not in vistos:
                items.append(mapa[k])
                vistos.add(k)
        items += [x for x in base_items if norm(x) not in vistos]
        orden.append({"categoria": orig_h[i]["categoria"], "items": items})
    orden += [orig_h[i] for i in range(len(orig_h)) if i not in usados]
    # certificaciones siempre al final
    orden.sort(key=lambda h: 1 if re.search(r"certific", norm(h["categoria"])) else 0)
    out["habilidades"] = orden

    sec = [s for s in (r.get("orden_secciones") or []) if s in SECCIONES]
    if sorted(set(sec)) == sorted(SECCIONES) and len(sec) == 4:
        out["orden"] = sec
    return out, revertidos


def _adaptar_reglas(cv, o):
    """Sin IA: ordena viñetas, grupos e items por cuántas cosas de la oferta mencionan."""
    texto = norm((o.get("titulo") or "") + "\n" + (o.get("descripcion") or ""))
    claves = [rx for _, rx, _ in puntuar.STACK if re.search(rx, texto)] + [rx for rx in VOCAB if re.search(rx, texto)]

    def peso(t):
        n = norm(_sin_md(t))
        return sum(1 for rx in claves if re.search(rx, n))

    out = copy.deepcopy(cv)
    for clave in ("experiencia", "proyectos"):
        for e in out.get(clave) or []:
            e["logros"] = sorted(e["logros"], key=lambda t: -peso(t))  # sort estable: empates en el orden original
    for h in out["habilidades"]:
        h["items"] = sorted(h["items"], key=lambda t: -peso(t))
    out["habilidades"] = sorted(out["habilidades"],
                                key=lambda h: (1 if re.search(r"certific", norm(h["categoria"])) else 0,
                                               -sum(peso(x) for x in h["items"])))
    return out


def _nombre_archivo(cv, o, idioma):
    emp = re.sub(r"[^A-Za-z0-9]+", "_", norm(o.get("empresa") or "oferta")).strip("_")[:30] or "oferta"
    nom = re.sub(r"[^A-Za-z0-9]+", "_", norm(cv.get("nombre", "CV"))).strip("_").title()
    return f"CV_{nom}_{emp}_{o['id']}_{idioma}.pdf"


def marcar_portfolio(cv, oid):
    """El enlace al portfolio del CV lleva ?cv=<oferta>: si alguien entra desde ese PDF, el aviso de visita dice
    a qué empresa se lo mandaste. El texto que se ve en el CV no cambia."""
    pf = dict(cv.get("portfolio") or {})
    url = pf.get("url") or ""
    if not url or "cv=" in url:
        return cv
    pf["url"] = url + ("&" if "?" in url else "?") + f"cv={oid}"
    return {**cv, "portfolio": pf}


def adaptar(db, cfg, oid, idioma=None):
    o = db.oferta(oid)
    if not o:
        raise ValueError("No existe esa oferta")
    idioma = idioma or o.get("idioma") or "es"
    cv = base(cfg, idioma)
    nota = []
    if not cv and idioma == "en":
        cv, idioma = base(cfg, "es"), "es"
        nota.append("La oferta está en inglés pero no tienes CV en inglés: va el de español.")
    if not cv:
        raise ValueError("Primero sube tu CV en la página principal")

    requisitos, revertidos, cambios = [], [], []
    if cfg.get("gemini_api_key"):
        try:
            r = gemini.generar(cfg, _prompt(cv, o, idioma), schema=ADAPT_SCHEMA, temperature=0.3)
            adaptado, revertidos = _aplicar(cv, r)
            requisitos = [q for q in (r.get("requisitos") or []) if isinstance(q, dict)][:12]
            cambios = [c for c in (r.get("cambios") or []) if isinstance(c, str)][:8]
        except Exception as e:  # noqa: BLE001
            log.warning("Gemini no pudo adaptar el CV de %s: %s", oid, e)
            adaptado = _adaptar_reglas(cv, o)
            nota.append(f"Gemini no respondió ({str(e)[:90]}): CV adaptado solo reordenando por palabras clave.")
    else:
        adaptado = _adaptar_reglas(cv, o)
        nota.append("Sin API key de Gemini: CV adaptado solo reordenando por palabras clave.")

    nombre = _nombre_archivo(cv, o, idioma)
    adaptado = marcar_portfolio(adaptado, oid)
    pdfcv.generar(adaptado, os.path.join(cfg["data_dir"], "cvs", nombre),
                  f"CV {cv.get('nombre', '')} · {o.get('titulo', '')} · {o.get('empresa', '')}")
    with open(os.path.join(cfg["data_dir"], "cvs", nombre[:-4] + ".json"), "w", encoding="utf-8") as f:
        json.dump(adaptado, f, ensure_ascii=False, indent=2)
    db.actualizar(oid, cv_estado="ok", cv_idioma=idioma, cv_archivo=nombre, cv_error="", cv_ts=time.time(), listo=1,
                  cv_cambios={"cambios": nota + cambios, "requisitos": requisitos, "revertidos": revertidos})
    return nombre


def procesar_pendientes(db, cfg, max_n=40):
    hechos = 0
    for oid in db.pendientes_cv()[:max_n]:
        try:
            adaptar(db, cfg, oid)
            hechos += 1
        except Exception as e:  # noqa: BLE001
            log.warning("CV de la oferta %s: %s", oid, e)
            db.actualizar(oid, cv_estado="error", cv_error=str(e)[:300], listo=1)
        time.sleep(4)  # margen para el límite por minuto de Gemini
    for oid in db.pendientes_cv()[max_n:]:  # el resto, sin CV pero que no bloqueen los avisos
        db.actualizar(oid, cv_estado="", listo=1)
    return hechos
