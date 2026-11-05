"""Pinta el CV en PDF con el mismo estilo que tu CV original (una página, A4, serif, versalitas).

Usa Charis SIL (la versión libre de Bitstream Charter, la letra de tu CV) si está instalada
(`sudo apt install fonts-sil-charis`); si no, Times. Si no cabe en una página, reduce la letra poco a poco.
"""
import glob
import io
import os
import re
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TINTA = HexColor("#111111")
GRIS = HexColor("#333333")
_FUENTE = None


def _fuente():
    """('Familia', normal, negrita, cursiva, negrita cursiva) registrada en reportlab."""
    global _FUENTE
    if _FUENTE:
        return _FUENTE
    for patrones in (
        ("Charis-Regular.ttf", "Charis-Bold.ttf", "Charis-Italic.ttf", "Charis-BoldItalic.ttf"),
        ("CharisSIL-Regular.ttf", "CharisSIL-Bold.ttf", "CharisSIL-Italic.ttf", "CharisSIL-BoldItalic.ttf"),
        ("CharisSIL-R.ttf", "CharisSIL-B.ttf", "CharisSIL-I.ttf", "CharisSIL-BI.ttf"),
    ):
        rutas = []
        for p in patrones:
            g = glob.glob(f"/usr/share/fonts/**/{p}", recursive=True)
            if not g:
                break
            rutas.append(g[0])
        if len(rutas) == 4:
            nombres = ("CVR", "CVB", "CVI", "CVBI")
            for n, r in zip(nombres, rutas):
                pdfmetrics.registerFont(TTFont(n, r))
            pdfmetrics.registerFontFamily("CV", normal="CVR", bold="CVB", italic="CVI", boldItalic="CVBI")
            _FUENTE = nombres
            return _FUENTE
    _FUENTE = ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic")
    return _FUENTE


def md(texto):
    """Escapa y convierte **negrita** en <b>."""
    t = escape(texto or "")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)


def versalitas(texto, tam, negrita=True, cada_palabra=True):
    """Imitación de \\textsc: mayúsculas pequeñas con la primera letra (de cada palabra o del todo) más grande."""
    F = _fuente()
    fn = F[1] if negrita else F[0]
    partes = []
    for i, palabra in enumerate((texto or "").split(" ")):
        if not palabra:
            continue
        cab, resto = (palabra[0], palabra[1:]) if (cada_palabra or i == 0) else ("", palabra)
        s = f'<font name="{fn}" size="{tam:.2f}">{escape(cab.upper())}</font>' if cab else ""
        if resto:
            s += f'<font name="{fn}" size="{tam * 0.78:.2f}">{escape(resto.upper())}</font>'
        partes.append(s)
    return " ".join(partes)


def _estilos(k):
    F = _fuente()
    return {
        "nombre": ParagraphStyle("n", fontName=F[1], fontSize=21 * k, leading=24 * k, alignment=TA_CENTER, textColor=TINTA),
        "titular": ParagraphStyle("t", fontName=F[1], fontSize=10.5 * k, leading=13 * k, alignment=TA_CENTER, textColor=TINTA),
        "contacto": ParagraphStyle("c", fontName=F[0], fontSize=9.6 * k, leading=12 * k, alignment=TA_CENTER, textColor=TINTA),
        "perfil": ParagraphStyle("p", fontName=F[0], fontSize=10.4 * k, leading=13.4 * k, textColor=TINTA),
        "seccion": ParagraphStyle("s", fontName=F[0], fontSize=11.5 * k, leading=13 * k, textColor=TINTA),
        "izq": ParagraphStyle("i", fontName=F[1], fontSize=10.6 * k, leading=12.8 * k, textColor=TINTA),
        "der": ParagraphStyle("d", fontName=F[0], fontSize=10.6 * k, leading=12.8 * k, alignment=TA_RIGHT, textColor=TINTA),
        "izq2": ParagraphStyle("i2", fontName=F[2], fontSize=9.6 * k, leading=11.6 * k, textColor=GRIS),
        "der2": ParagraphStyle("d2", fontName=F[2], fontSize=9.6 * k, leading=11.6 * k, alignment=TA_RIGHT, textColor=GRIS),
        "vin": ParagraphStyle("v", fontName=F[0], fontSize=9.9 * k, leading=12.3 * k, leftIndent=22 * k,
                              bulletIndent=11 * k, textColor=TINTA, spaceAfter=0.6 * k),
        "hab": ParagraphStyle("h", fontName=F[0], fontSize=9.9 * k, leading=12.4 * k, leftIndent=6 * k, textColor=TINTA),
    }


def _fila(izq, der, e1, e2, ancho, rep=0.66):
    t = Table([[Paragraph(izq, e1), Paragraph(der, e2)]], colWidths=[ancho * rep, ancho * (1 - rep)])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _historia(cv, k, ancho):
    E = _estilos(k)
    sec = cv.get("secciones") or {}
    h = [Paragraph(versalitas(cv["nombre"], 21 * k), E["nombre"]),
         Paragraph(versalitas(cv.get("titular", ""), 10.5 * k), E["titular"])]
    cont = []
    for c in cv.get("contacto") or []:
        t = escape(c["texto"])
        cont.append(f'<a href="{escape(c["url"])}"><u>{t}</u></a>' if c.get("url") else t)
    h.append(Paragraph(" | ".join(cont), E["contacto"]))
    pf = cv.get("portfolio")
    if pf:
        h.append(Paragraph(f'<b>{escape(pf.get("etiqueta", "Portfolio"))}:</b> '
                           f'<a href="{escape(pf.get("url", ""))}"><u>{escape(pf["texto"])}</u></a>', E["contacto"]))
    h += [Spacer(1, 11 * k), Paragraph(md(cv.get("perfil")), E["perfil"])]

    def seccion(titulo):
        return [Spacer(1, 8 * k), Paragraph(versalitas(titulo, 11.5 * k, negrita=False, cada_palabra=False), E["seccion"]),
                HRFlowable(width="100%", thickness=0.6, color=TINTA, spaceBefore=1.5 * k, spaceAfter=3.5 * k)]

    def vinetas(lista):
        return [Paragraph(md(v), E["vin"], bulletText="•") for v in lista]

    # el orden de las secciones lo puede cambiar la adaptación (p. ej. proyectos antes que educación)
    orden = cv.get("orden") or ["educacion", "experiencia", "proyectos", "habilidades"]
    for s in orden:
        if s == "educacion" and cv.get("educacion"):
            h += seccion(sec.get("educacion", "Educación"))
            for ed in cv["educacion"]:
                bloque = [_fila(md(ed["centro"]), md(ed.get("lugar", "")), E["izq"], E["der"], ancho),
                          _fila(md(ed.get("titulo", "")), md(ed.get("fechas", "")), E["izq2"], E["der2"], ancho)]
                if ed.get("detalle"):
                    bloque.append(Paragraph(md(ed["detalle"]), E["izq2"]))
                h.append(KeepTogether(bloque))
        elif s == "experiencia" and cv.get("experiencia"):
            h += seccion(sec.get("experiencia", "Experiencia"))
            for i, ex in enumerate(cv["experiencia"]):
                if i:
                    h.append(Spacer(1, 4 * k))
                h.append(KeepTogether([
                    _fila(md(ex["puesto"]), md(ex.get("fechas", "")), E["izq"], E["der"], ancho),
                    _fila(md(ex.get("empresa", "")), md(ex.get("lugar", "")), E["izq2"], E["der2"], ancho),
                    Spacer(1, 1.5 * k), *vinetas(ex.get("logros") or [])]))
        elif s == "proyectos" and cv.get("proyectos"):
            h += seccion(sec.get("proyectos", "Proyectos"))
            for pr in cv["proyectos"]:
                izq = md(pr["nombre"]) + (f' | <i>{escape(pr["stack"])}</i>' if pr.get("stack") else "")
                h.append(KeepTogether([_fila(izq, md(pr.get("fechas", "")), E["izq"], E["der"], ancho, 0.8),
                                       Spacer(1, 1.5 * k), *vinetas(pr.get("logros") or [])]))
        elif s == "habilidades" and cv.get("habilidades"):
            h += seccion(sec.get("habilidades", "Habilidades"))
            for hb in cv["habilidades"]:
                h.append(Paragraph(f'<b>{escape(hb["categoria"])}</b>: {escape(", ".join(hb["items"]))}.', E["hab"]))
    return h


class _Contador:
    def __init__(self):
        self.paginas = 0

    def __call__(self, canvas, doc):
        self.paginas += 1


def generar(cv, ruta=None, titulo_pdf=None):
    """Devuelve los bytes del PDF (y lo escribe en 'ruta' si se da). Siempre una página si es posible."""
    margen_h, margen_v = 50, 36
    ancho = A4[0] - 2 * margen_h
    datos = None
    for k in (1.0, 0.97, 0.94, 0.91, 0.88, 0.85, 0.82):
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=margen_h, rightMargin=margen_h, topMargin=margen_v,
                                bottomMargin=margen_v, title=titulo_pdf or f"CV {cv.get('nombre', '')}",
                                author=cv.get("nombre", ""))
        cont = _Contador()
        doc.build(_historia(cv, k, ancho), onFirstPage=cont, onLaterPages=cont)
        datos = buf.getvalue()
        if cont.paginas <= 1:
            break
    if ruta:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "wb") as f:
            f.write(datos)
    return datos
