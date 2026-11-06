"""Lector de la búsqueda pública de empleo de LinkedIn (la que ve cualquiera sin iniciar sesión).

- Listado: /jobs-guest/jobs/api/seeMoreJobPostings/search  -> trozos de HTML con 25 tarjetas por página
- Detalle: /jobs-guest/jobs/api/jobPosting/<id>             -> descripción, nivel, tipo de empleo, candidatos

No se usa tu cuenta ni cookies. El HTML de LinkedIn cambia de vez en cuando: por eso cada campo tiene
varios selectores de reserva, y si un día no sale nada se guarda el HTML en data/debug/ y salta una alerta.
"""
import os
import re
import urllib.parse

from bs4 import BeautifulSoup

from . import util

BASE = "https://www.linkedin.com"
LISTA = BASE + "/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETALLE = BASE + "/jobs-guest/jobs/api/jobPosting/{id}"
POR_PAGINA = 10  # la búsqueda pública devuelve 10 ofertas por página


def url_busqueda(palabras, modo, start=0, tpr="r86400"):
    q = {"keywords": palabras, "location": modo["location"], "f_TPR": tpr, "start": str(start)}
    for k in ("geoId", "f_WT", "distance"):
        if modo.get(k):
            q[k] = modo[k]
    return LISTA + "?" + urllib.parse.urlencode(q)


def url_oferta(job_id):
    return f"{BASE}/jobs/view/{job_id}/"


def _txt(n):
    return re.sub(r"\s+", " ", n.get_text(" ")).strip() if n else ""


def _uno(raiz, *selectores):
    for s in selectores:
        n = raiz.select_one(s)
        if n and _txt(n):
            return n
    return None


def _id_de(card):
    for attr in ("data-entity-urn", "data-job-id"):
        v = card.get(attr) or ""
        m = re.search(r"(\d{6,})", v)
        if m:
            return m.group(1)
    for sub in card.select("[data-entity-urn], [data-job-id]"):
        m = re.search(r"(\d{6,})", sub.get("data-entity-urn") or sub.get("data-job-id") or "")
        if m:
            return m.group(1)
    a = card if card.name == "a" and "/jobs/view/" in card.get("href", "") else card.select_one("a[href*='/jobs/view/']")
    if a:
        m = re.search(r"/jobs/view/(?:[^/?]*-)?(\d{6,})", a.get("href", ""))
        if m:
            return m.group(1)
    return None


def _logo(raiz):
    """URL del logo de la empresa (LinkedIn la pone en data-delayed-url para cargarla después)."""
    for img in raiz.select("img"):
        for attr in ("data-delayed-url", "data-ghost-url", "src"):
            u = (img.get(attr) or "").strip()
            if u.startswith("https://") and "licdn.com" in u and "ghost" not in u:
                return u
    return ""


def parsear_lista(html):
    """Tarjetas de un trozo del listado. Devuelve lista de dicts."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".base-card, .base-search-card, .job-search-card")
    if not cards:
        cards = [li for li in soup.select("li") if li.select_one("a[href*='/jobs/view/']")]
    # si una tarjeta queda dentro de otra, nos quedamos con la de fuera
    cards = [c for c in cards if not any(p in cards for p in c.parents)]
    out, vistos = [], set()
    for c in cards:
        jid = _id_de(c)
        if not jid or jid in vistos:
            continue
        vistos.add(jid)
        tit = _uno(c, ".base-search-card__title", "h3", ".job-search-card__title")
        emp = _uno(c, ".base-search-card__subtitle a", ".base-search-card__subtitle", "h4")
        lug = _uno(c, ".job-search-card__location", ".base-search-card__metadata span")
        sal = _uno(c, ".job-search-card__salary-info", ".base-search-card__salary-info")
        t = c.select_one("time")
        out.append({
            "job_id": jid,
            "titulo": _txt(tit),
            "empresa": _txt(emp),
            "lugar": _txt(lug),
            "fecha_pub": (t.get("datetime") if t else "") or "",
            "sueldo_txt": _txt(sal),
            "url": url_oferta(jid),
            "logo_url": _logo(c),
        })
    return out


CRITERIOS = {
    "seniority": ("nivel", "seniority", "antiguedad", "experiencia"),
    "tipo_empleo": ("tipo de empleo", "employment", "jornada", "tipo de contrato"),
    "funcion": ("funcion", "function"),
    "sectores": ("sector", "industr"),
}


def parsear_detalle(html):
    soup = BeautifulSoup(html, "html.parser")
    desc = _uno(soup, ".show-more-less-html__markup", ".description__text", "section.description", ".decorated-job-posting__details")
    d = {
        "titulo": _txt(_uno(soup, ".top-card-layout__title", ".topcard__title", "h2")),
        "empresa": _txt(_uno(soup, ".topcard__org-name-link", ".topcard__flavor a", ".top-card-layout__second-subline a")),
        "lugar": _txt(_uno(soup, ".topcard__flavor--bullet", ".top-card-layout__second-subline .topcard__flavor:nth-of-type(2)")),
        "descripcion": util.texto_html(desc) if desc else "",
        "candidatos_txt": _txt(_uno(soup, ".num-applicants__caption", "figcaption.num-applicants__caption", ".topcard__flavor--metadata")),
        "sueldo_txt": _txt(_uno(soup, ".compensation__salary", ".salary", ".compensation__salary-range")),
        "logo_url": _logo(soup.select_one(".top-card-layout") or soup),
    }
    for item in soup.select(".description__job-criteria-item, ul.description__job-criteria-list li"):
        h = util.norm(_txt(item.select_one("h3") or item.select_one(".description__job-criteria-subheader")))
        v = _txt(item.select_one("span") or item.select_one(".description__job-criteria-text"))
        for campo, claves in CRITERIOS.items():
            if any(k in h for k in claves) and campo not in d:
                d[campo] = v
                break
    d["candidatos"] = candidatos(d["candidatos_txt"])
    d["tipo_lugar"] = tipo_lugar(soup)
    return d


TIPOS = {"en remoto": "remoto", "remoto": "remoto", "remote": "remoto", "hibrido": "hibrido", "hybrid": "hibrido",
         "presencial": "presencial", "on-site": "presencial", "onsite": "presencial", "in situ": "presencial"}


def tipo_lugar(soup):
    """Modalidad que pone LinkedIn en la ficha, si la trae: JSON-LD (TELECOMMUTE) o una etiqueta suelta en la cabecera."""
    import json
    for sc in soup.select('script[type="application/ld+json"]'):
        try:
            datos = json.loads(sc.string or "{}")
        except ValueError:
            continue
        for x in datos if isinstance(datos, list) else [datos]:
            if isinstance(x, dict) and "TELECOMMUTE" in json.dumps(x.get("jobLocationType", "")):
                return "remoto"
    cab = soup.select_one(".top-card-layout") or soup.select_one(".topcard") or soup
    for n in cab.select("span, li, div"):
        if n.find(True):
            continue
        t = util.norm(n.get_text(" "))
        if t in TIPOS:
            return TIPOS[t]
    return ""


def candidatos(txt):
    t = util.norm(txt)
    if not t or not re.search(r"solicit|applicant|candidat", t):
        return None
    m = re.search(r"(\d[\d.,]*)", t)
    if not m:
        return None
    n = int(re.sub(r"[.,]", "", m.group(1)))
    if re.search(r"mas de|over|more than", t):
        n += 1
    return n


def buscar(palabras, modo, start, tpr, debug_dir=None):
    """Una página del listado. Devuelve (código HTTP, tarjetas)."""
    code, html = util.get(url_busqueda(palabras, modo, start, tpr))
    if code != 200:
        return code, []
    tarjetas = parsear_lista(html)
    if debug_dir and not tarjetas and html.strip():
        # HTML con contenido pero sin tarjetas: casi seguro que LinkedIn ha cambiado el formato
        with open(os.path.join(debug_dir, "lista_vacia.html"), "w", encoding="utf-8") as f:
            f.write(html)
    return code, tarjetas


def detalle(job_id, debug_dir=None, muestra=""):
    code, html = util.get(DETALLE.format(id=job_id))
    if code != 200:
        return None
    d = parsear_detalle(html)
    if debug_dir and not d["descripcion"]:
        with open(os.path.join(debug_dir, f"detalle_{job_id}.html"), "w", encoding="utf-8") as f:
            f.write(html)
    if debug_dir and not d["logo_url"] and not os.path.exists(os.path.join(debug_dir, "detalle_sin_logo.html")):
        with open(os.path.join(debug_dir, "detalle_sin_logo.html"), "w", encoding="utf-8") as f:
            f.write(html)  # para ver dónde pone LinkedIn el logo si algún día cambia
    if debug_dir and muestra and not os.path.exists(os.path.join(debug_dir, f"detalle_{muestra}.html")):
        with open(os.path.join(debug_dir, f"detalle_{muestra}.html"), "w", encoding="utf-8") as f:
            f.write(html)  # una ficha de muestra por modo, para revisar qué trae LinkedIn
    return d
