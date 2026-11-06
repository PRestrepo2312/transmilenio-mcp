from __future__ import annotations

import math
import re
import unicodedata

# La gente escribe "calle 72", "cll 72" o "cl 72"; el GTFS mezcla las tres.
_ABREV = {
    "calle": "cl",
    "cll": "cl",
    "carrera": "kr",
    "cra": "kr",
    "kra": "kr",
    "cr": "kr",
    "avenida": "av",
    "diagonal": "dg",
    "transversal": "tv",
}
_VACIAS = {"estacion", "parada", "paradero", "de", "la", "el", "las", "los", "del"}

# Sectores de 45° desde el norte, en sentido horario.
_RUMBOS = ["Norte", "Nororiente", "Oriente", "Suroriente", "Sur", "Suroccidente", "Occidente", "Noroccidente"]


def normalizar(texto: str | None) -> str:
    s = unicodedata.normalize("NFKD", texto or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(_ABREV.get(t, t) for t in s.split() if t not in _VACIAS)


def codigo_ruta(texto: str | None) -> str:
    return normalizar(texto).replace(" ", "")


def distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(a))


def rumbo(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dy = lat2 - lat1
    dx = (lon2 - lon1) * math.cos(math.radians(lat1))
    return (math.degrees(math.atan2(dx, dy)) + 360) % 360


def sentido(grados: float) -> str:
    """180° -> "Norte-Sur": de dónde viene y hacia dónde va."""
    hacia = _RUMBOS[int((grados + 22.5) // 45) % 8]
    desde = _RUMBOS[int((grados + 180 + 22.5) // 45) % 8]
    return f"{desde}-{hacia}"
