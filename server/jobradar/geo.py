"""Distancia aproximada por carretera desde Limpias, sin servicios externos (tabla interna de pueblos y ciudades).

LinkedIn escribe la ubicación como "Santander, Cantabria, España", "Bilbao, País Vasco, España",
"Gran Bilbao", "Cantabria, España"... Se busca de la parte más concreta a la más general.
"""
import math
import re

from .util import norm

ORIGENES = {"limpias": (43.3628, -3.4186), "laredo": (43.4092, -3.4161), "santander": (43.4623, -3.8100)}
FACTOR_CARRETERA = 1.3  # línea recta -> carretera (costa y valles), aproximado

SITIOS = {
    # Cantabria
    "limpias": (43.3628, -3.4186), "laredo": (43.4092, -3.4161), "colindres": (43.3961, -3.4517),
    "ampuero": (43.3433, -3.4161), "santona": (43.4428, -3.4572), "castro urdiales": (43.3822, -3.2200),
    "castro-urdiales": (43.3822, -3.2200), "noja": (43.4886, -3.5253), "argonos": (43.4570, -3.4930),
    "barcena de cicero": (43.4219, -3.5103), "gama": (43.4170, -3.5270), "guriezo": (43.3500, -3.3300),
    "liendo": (43.3920, -3.3770), "rasines": (43.3000, -3.4300), "ramales de la victoria": (43.2580, -3.4650),
    "voto": (43.3500, -3.5100), "hazas de cesto": (43.4000, -3.5800), "beranga": (43.4000, -3.5800),
    "entrambasaguas": (43.3730, -3.6830), "solares": (43.3880, -3.7370), "medio cudeyo": (43.3880, -3.7370),
    "lierganes": (43.3430, -3.7450), "santander": (43.4623, -3.8100), "pctcan": (43.4500, -3.8300),
    "camargo": (43.4210, -3.8340), "maliano": (43.4210, -3.8340), "muriedas": (43.4290, -3.8580),
    "el astillero": (43.4010, -3.8200), "astillero": (43.4010, -3.8200), "santa cruz de bezana": (43.4440, -3.9030),
    "bezana": (43.4440, -3.9030), "pielagos": (43.3560, -3.9520), "renedo": (43.3560, -3.9520),
    "torrelavega": (43.3497, -4.0478), "polanco": (43.3800, -4.0140), "suances": (43.4330, -4.0430),
    "santillana del mar": (43.3890, -4.1070), "los corrales de buelna": (43.2610, -4.0640),
    "corrales de buelna": (43.2610, -4.0640), "cabezon de la sal": (43.3080, -4.2350), "comillas": (43.3860, -4.2910),
    "san vicente de la barquera": (43.3850, -4.3990), "reinosa": (42.9990, -4.1370), "potes": (43.1540, -4.6230),
    "villacarriedo": (43.2290, -3.8100), "cantabria": (43.4623, -3.8100),
    # Bizkaia
    "bilbao": (43.2630, -2.9350), "bilbo": (43.2630, -2.9350), "gran bilbao": (43.2630, -2.9350),
    "barakaldo": (43.2970, -2.9890), "baracaldo": (43.2970, -2.9890), "getxo": (43.3560, -3.0120),
    "leioa": (43.3280, -2.9870), "erandio": (43.3050, -2.9730), "derio": (43.2920, -2.8800),
    "zamudio": (43.2830, -2.8640), "sondika": (43.2990, -2.9260), "loiu": (43.3140, -2.9420),
    "basauri": (43.2370, -2.8860), "galdakao": (43.2300, -2.8420), "etxebarri": (43.2470, -2.8920),
    "portugalete": (43.3190, -3.0200), "santurtzi": (43.3290, -3.0330), "santurce": (43.3290, -3.0330),
    "sestao": (43.3090, -3.0060), "durango": (43.1700, -2.6300), "mungia": (43.3550, -2.8460),
    "bermeo": (43.4210, -2.7230), "gernika": (43.3170, -2.6780), "guernica": (43.3170, -2.6780),
    "amorebieta": (43.2190, -2.7340), "balmaseda": (43.1940, -3.1950), "zalla": (43.2140, -3.1340),
    "muskiz": (43.3220, -3.1120), "abanto": (43.3200, -3.0750), "ortuella": (43.3110, -3.0570),
    "arrigorriaga": (43.2050, -2.8870), "berango": (43.3650, -2.9950), "sopela": (43.3790, -2.9820),
    "plentzia": (43.4040, -2.9460), "karrantza": (43.2300, -3.3600), "lekeitio": (43.3640, -2.5050),
    "ermua": (43.1870, -2.5020), "igorre": (43.1650, -2.7760), "bizkaia": (43.2630, -2.9350),
    "vizcaya": (43.2630, -2.9350), "biscay": (43.2630, -2.9350),
    # fuera de la zona (para poder decir "a 160 km" en vez de "desconocida")
    "vitoria": (42.846, -2.672), "vitoria-gasteiz": (42.846, -2.672), "alava": (42.846, -2.672), "araba": (42.846, -2.672),
    "donostia": (43.318, -1.981), "san sebastian": (43.318, -1.981), "gipuzkoa": (43.318, -1.981),
    "guipuzcoa": (43.318, -1.981), "burgos": (42.344, -3.697), "miranda de ebro": (42.685, -2.947),
    "oviedo": (43.361, -5.849), "gijon": (43.532, -5.661), "aviles": (43.556, -5.925), "asturias": (43.361, -5.849),
    "leon": (42.599, -5.567), "palencia": (42.010, -4.528), "valladolid": (41.652, -4.724), "logrono": (42.465, -2.445),
    "la rioja": (42.465, -2.445), "pamplona": (42.812, -1.646), "navarra": (42.812, -1.646),
    "zaragoza": (41.649, -0.889), "madrid": (40.417, -3.704), "barcelona": (41.388, 2.170), "valencia": (39.470, -0.376),
    "sevilla": (37.389, -5.984), "malaga": (36.721, -4.421), "a coruna": (43.362, -8.411), "vigo": (42.240, -8.721),
}
REGION_ZONA = ("cantabria", "bizkaia", "vizcaya", "biscay", "bilbao", "pais vasco")


def _hav(a, b):
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _sitio(texto):
    """Devuelve (clave, coords) del sitio más concreto que aparezca en el texto."""
    t = norm(texto)
    t = re.sub(r"\b(area metropolitana de|area de|greater|metropolitan area|y alrededores)\b", " ", t)
    partes = [p.strip() for p in re.split(r"[,;/()|·]", t) if p.strip()]
    for p in partes:  # primero la parte entera ("castro urdiales")
        if p in SITIOS:
            return p, SITIOS[p]
    for p in partes:  # luego contenida ("ayuntamiento de torrelavega")
        for k in sorted(SITIOS, key=len, reverse=True):
            if re.search(r"\b" + re.escape(k) + r"\b", p):
                return k, SITIOS[k]
    return None, None


def km_desde(origen, texto):
    """km aproximados por carretera o None si no se reconoce el sitio."""
    o = ORIGENES.get(norm(origen)) or SITIOS.get(norm(origen)) or ORIGENES["limpias"]
    clave, c = _sitio(texto)
    if not c:
        return None
    return int(round(_hav(o, c) * FACTOR_CARRETERA))


def en_region(texto):
    t = norm(texto)
    return any(r in t for r in REGION_ZONA)
