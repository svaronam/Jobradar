import gzip
import logging
import random
import re
import time
import unicodedata
import urllib.error
import urllib.request

log = logging.getLogger("jobradar")

UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
]


class Bloqueado(Exception):
    """LinkedIn devuelve 429/999: estamos pidiendo demasiado. Se para la pasada y se espera."""


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


def pausa(cfg):
    time.sleep(random.uniform(float(cfg.get("pausa_min", 3)), float(cfg.get("pausa_max", 7))))


def get(url, timeout=25, intentos=2):
    """GET como un navegador normal. Devuelve (código, texto)."""
    ultimo = None
    for i in range(intentos):
        req = urllib.request.Request(url, headers={
            "User-Agent": random.choice(UAS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
            "Accept-Encoding": "gzip",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    b = gzip.decompress(b)
                return r.status, b.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 999):
                raise Bloqueado(f"HTTP {e.code}")
            if e.code in (400, 404, 410):
                return e.code, ""
            ultimo = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            ultimo = e
        time.sleep(4 * (i + 1))
    raise ConnectionError(str(ultimo))


def texto_html(nodo):
    """Texto legible de un nodo de BeautifulSoup conservando saltos de párrafo y viñetas."""
    if nodo is None:
        return ""
    for br in nodo.find_all("br"):
        br.replace_with("\n")
    for li in nodo.find_all("li"):
        li.insert_before("\n• ")
    for p in nodo.find_all(["p", "div", "h1", "h2", "h3", "h4", "ul", "ol"]):
        p.insert_after("\n")
    t = nodo.get_text("")
    t = re.sub(r"[ \t ]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()
