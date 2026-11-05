"""Cliente mínimo de la API de Gemini (sin dependencias), igual que el de OpoTest."""
import json
import time
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiError(Exception):
    pass


def _post(model, key, body, timeout=120):
    req = urllib.request.Request(
        API.format(model=model), data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def generar(cfg, prompt, schema=None, temperature=0.4, system=None, max_tokens=8192):
    """Devuelve el texto (o el JSON ya parseado si se pasa schema)."""
    key = (cfg.get("gemini_api_key") or "").strip()
    if not key:
        raise GeminiError("Falta la API key de Gemini (Ajustes).")
    gen = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if schema:
        gen["responseMimeType"] = "application/json"
        gen["responseSchema"] = schema
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    modelos = [cfg.get("gemini_model") or "gemini-3.8-flash"] + list(cfg.get("gemini_fallback_models") or [])
    ultimo = None
    for modelo in modelos:
        for intento in range(3):
            try:
                res = _post(modelo, key, body)
                cands = res.get("candidates") or []
                if not cands:
                    raise GeminiError("Respuesta vacía de Gemini: %s" % json.dumps(res)[:300])
                texto = "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", [])).strip()
                return _json(texto) if schema else texto
            except urllib.error.HTTPError as e:
                detalle = e.read().decode("utf-8", "ignore")[:400]
                ultimo = GeminiError(f"{modelo}: HTTP {e.code} {detalle}")
                if e.code in (429, 500, 503):
                    time.sleep(8 * (intento + 1))
                    continue
                if e.code in (400, 404):  # modelo que ya no existe -> el siguiente
                    break
                raise ultimo
            except (urllib.error.URLError, TimeoutError) as e:
                ultimo = GeminiError(f"{modelo}: sin conexión ({e})")
                time.sleep(5)
            except ValueError as e:
                ultimo = GeminiError(f"{modelo}: JSON no válido ({e})")
                break
    raise ultimo or GeminiError("No se pudo contactar con Gemini")


def _json(t):
    t = t.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("\n") + 1:] if "\n" in t else t
    inicio = min([i for i in (t.find("{"), t.find("[")) if i >= 0] or [0])
    return json.loads(t[inicio:])
