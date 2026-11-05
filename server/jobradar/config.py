"""Configuración: valores por defecto < config.json (en la Pi) < data/ajustes.json (lo que cambias desde la app)."""
import copy
import json
import os

DEFAULT = {
    "host": "0.0.0.0",
    "puerto": 8796,
    "token": "",

    # Lo que se busca en LinkedIn. Cada palabra clave se cruza con cada modo.
    "palabras_clave": [
        "java spring",
        "desarrollador backend java",
        "backend developer java",
        "spring boot",
        "analista programador",
        "analista funcional",
        "python backend",
    ],
    "modos": [
        # remoto: toda España (aquí LinkedIn sí respeta el filtro)
        {"nombre": "remoto", "location": "España", "geoId": "105646813", "f_WT": "2", "paginas": 3},
        # tu zona: LinkedIn no distingue bien híbrido/presencial en zonas pequeñas, así que se pide todo lo que no es
        # remoto de una vez y la modalidad se saca del título y la descripción
        {"nombre": "zona", "location": "Cantabria, España", "f_WT": "1,3", "paginas": 1},
        {"nombre": "zona", "location": "Bilbao, País Vasco, España", "distance": "25", "f_WT": "1,3", "paginas": 1},
    ],
    # cuándo buscar: "horas" = a las horas_pasada · "intervalo" = cada cada_horas entre desde y hasta
    "frecuencia": {"modo": "horas", "cada_horas": 3, "desde": "08:00", "hasta": "22:00", "dias": [0, 1, 2, 3, 4, 5, 6]},
    "horas_pasada": ["08:40", "13:40", "19:40"],
    "pausa_min": 3.0,
    "pausa_max": 7.0,

    "perfil": {
        "origen": "Limpias",
        "zona_max_km": 80,
        "anios_experiencia": 5,
        "sueldo_minimo": 35000,
        "sueldo_objetivo": 45000,
    },
    # títulos que ni se abren (se guardan como filtrados para no volver a mirarlos)
    "excluir_titulo": ["frontend", "front-end", "front end", "qa ", "tester", "testing", "comercial", "ventas",
                       "salesforce", "sap ", "abap", ".net", "c#", "php", "android", "ios ", "becario", "becaria",
                       "prácticas", "practicas", "internship", "intern ", "profesor", "formador", "help desk",
                       "soporte técnico", "técnico de soporte", "microinformática", "data scientist", "diseñador"],
    "excluir_empresas": [],

    "gemini_api_key": "",
    "gemini_model": "gemini-3.8-flash",
    "gemini_fallback_models": ["gemini-3.5-flash", "gemini-2.5-flash"],
    "cv_desde_score": 55,

    "pesos": {},
    "niveles": {"prioritaria": 75, "interesante": 58, "vigilar": 40},
    "notificar_niveles": ["prioritaria", "interesante", "vigilar"],
}

# lo que se puede cambiar desde la app (se guarda en data/ajustes.json)
EDITABLES = {"palabras_clave", "horas_pasada", "frecuencia", "perfil", "excluir_titulo", "excluir_empresas", "gemini_api_key",
             "gemini_model", "cv_desde_score", "notificar_niveles", "pesos", "niveles"}


def _merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _leer(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


# los modos de la v1.0 (híbrido y presencial por separado): si el config.json de la Pi los tiene tal cual, se cambian
MODOS_V1 = [("remoto", "España", "2"), ("hibrido", "Cantabria, España", "3"), ("presencial", "Cantabria, España", "1"),
            ("hibrido", "Bilbao, País Vasco, España", "3"), ("presencial", "Bilbao, País Vasco, España", "1")]


def cargar(base_dir):
    data = os.path.join(base_dir, "data")
    os.makedirs(os.path.join(data, "cv"), exist_ok=True)
    os.makedirs(os.path.join(data, "cvs"), exist_ok=True)
    os.makedirs(os.path.join(data, "debug"), exist_ok=True)
    cfg = _merge(DEFAULT, _leer(os.path.join(base_dir, "config.json")))
    cfg = _merge(cfg, _leer(os.path.join(data, "ajustes.json")))
    if [(m.get("nombre"), m.get("location"), m.get("f_WT")) for m in cfg.get("modos") or []] == MODOS_V1:
        cfg["modos"] = copy.deepcopy(DEFAULT["modos"])
    if os.environ.get("JOBRADAR_PUERTO"):
        cfg["puerto"] = int(os.environ["JOBRADAR_PUERTO"])
    cfg["base_dir"] = base_dir
    cfg["data_dir"] = data
    return cfg


def guardar_ajustes(cfg, cambios):
    """Aplica en caliente y persiste en data/ajustes.json solo las claves editables."""
    path = os.path.join(cfg["data_dir"], "ajustes.json")
    actual = _leer(path)
    for k, v in cambios.items():
        if k not in EDITABLES:
            continue
        if k == "perfil" and isinstance(v, dict):
            actual["perfil"] = {**actual.get("perfil", {}), **v}
            cfg["perfil"] = {**cfg["perfil"], **v}
        else:
            actual[k] = v
            cfg[k] = v
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(actual, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)  # lleva la API key
    os.replace(tmp, path)


def publico(cfg):
    """Ajustes para la app, sin la API key completa."""
    out = {k: copy.deepcopy(cfg[k]) for k in EDITABLES if k in cfg}
    key = out.pop("gemini_api_key", "") or ""
    out["gemini_api_key_set"] = bool(key)
    out["gemini_api_key_hint"] = ("…" + key[-4:]) if key else ""
    return out
