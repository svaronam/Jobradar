"""Cuándo toca la siguiente pasada. Dos modos, configurables desde la app (⚙ → Cuándo buscar):

- "horas":     a horas fijas (08:40, 13:40, 19:40...)
- "intervalo": cada N horas dentro de una franja (p. ej. cada 3 h de 08:00 a 22:00)

En los dos se pueden elegir los días de la semana. Todo se calcula desde el inicio de la última pasada, así que
cambiar la frecuencia se aplica al momento y, si la Pi estuvo apagada, recupera la pasada perdida al encenderse.
"""
import datetime as dt
import re

DEFECTO = {"modo": "horas", "cada_horas": 3, "desde": "08:00", "hasta": "22:00", "dias": [0, 1, 2, 3, 4, 5, 6]}
MIN_HORAS = 1          # menos que esto y LinkedIn empieza a limitar
RECUPERAR_HORAS = 3    # una hora fija perdida (Pi apagada) se recupera si no hace más de esto
DIAS = ["L", "M", "X", "J", "V", "S", "D"]


def _hm(txt):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", txt or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"Hora no válida: «{txt}» (usa HH:MM)")
    return int(m.group(1)), int(m.group(2))


def frecuencia(cfg):
    f = {**DEFECTO, **(cfg.get("frecuencia") or {})}
    f["horas"] = sorted({f"{h:02d}:{m:02d}" for h, m in map(_hm, cfg.get("horas_pasada") or ["08:40"])})
    return f


def validar(f, horas):
    """Devuelve (frecuencia, horas_pasada) limpias o lanza ValueError con un mensaje para la app."""
    modo = f.get("modo", "horas")
    if modo not in ("horas", "intervalo"):
        raise ValueError("Modo de búsqueda no válido")
    try:
        cada = round(float(f.get("cada_horas", 3)), 2)
    except (TypeError, ValueError):
        raise ValueError("«Cada cuántas horas» tiene que ser un número")
    if cada < MIN_HORAS:
        raise ValueError(f"Como mínimo cada {MIN_HORAS} h: con menos, LinkedIn empieza a bloquear las peticiones")
    if cada > 168:
        raise ValueError("Como máximo cada 168 h (una semana)")
    desde, hasta = _hm(f.get("desde", "08:00")), _hm(f.get("hasta", "22:00"))
    if desde >= hasta:
        raise ValueError("La franja tiene que empezar antes de terminar (no puede cruzar la medianoche)")
    dias = sorted({int(d) for d in (f.get("dias") or []) if 0 <= int(d) <= 6})
    if not dias:
        raise ValueError("Elige al menos un día")
    hs = sorted({"%02d:%02d" % _hm(h) for h in (horas or [])})
    if modo == "horas" and not hs:
        raise ValueError("Pon al menos una hora de búsqueda")
    limpio = {"modo": modo, "cada_horas": cada, "desde": "%02d:%02d" % desde, "hasta": "%02d:%02d" % hasta, "dias": dias}
    return limpio, hs or ["08:40"]


def _en(dia, hm):
    h, m = _hm(hm)
    return dt.datetime.combine(dia, dt.time(h, m))


def proxima(cfg, ultima, ahora=None):
    """datetime de la próxima pasada. 'ultima' = datetime de inicio de la última pasada o None.
    Si devuelve algo <= ahora, toca ya."""
    ahora = ahora or dt.datetime.now()
    f = frecuencia(cfg)
    if ultima is None:
        return ahora  # nunca se ha buscado: primera pasada en cuanto arranca
    dias = set(f["dias"])

    if f["modo"] == "horas":
        desde = max(ultima, ahora - dt.timedelta(hours=RECUPERAR_HORAS))
        for d in range(0, 9):
            dia = (desde + dt.timedelta(days=d)).date()
            if dia.weekday() not in dias:
                continue
            for h in f["horas"]:
                t = _en(dia, h)
                if t > desde:
                    return t
        return ahora + dt.timedelta(days=1)

    ini, fin = f["desde"], f["hasta"]

    def ajustar(t):
        """Lleva t al primer momento permitido (día elegido y dentro de la franja) a partir de t."""
        for _ in range(9):
            if t.weekday() in dias:
                if t < _en(t.date(), ini):
                    return _en(t.date(), ini)
                if t <= _en(t.date(), fin):
                    return t
            t = _en(t.date() + dt.timedelta(days=1), ini)
        return t

    t = ajustar(ultima + dt.timedelta(hours=f["cada_horas"]))
    if t < ahora:  # se pasó la hora (Pi apagada o frecuencia recién acortada): ya, si ahora se puede
        t = ajustar(ahora)
    return t


def pasadas_al_dia(cfg):
    f = frecuencia(cfg)
    if f["modo"] == "horas":
        return len(f["horas"])
    a, b = _hm(f["desde"]), _hm(f["hasta"])
    minutos = (b[0] * 60 + b[1]) - (a[0] * 60 + a[1])
    return int(minutos // (f["cada_horas"] * 60)) + 1


def describir(cfg):
    f = frecuencia(cfg)
    dias = "todos los días" if len(f["dias"]) == 7 else (
        "de lunes a viernes" if f["dias"] == [0, 1, 2, 3, 4] else " ".join(DIAS[d] for d in f["dias"]))
    if f["modo"] == "horas":
        return f"a las {', '.join(f['horas'])}, {dias}"
    cada = f["cada_horas"]
    cada_txt = f"{int(cada)} h" if cada == int(cada) else f"{cada:g} h"
    return f"cada {cada_txt} de {f['desde']} a {f['hasta']}, {dias}"
