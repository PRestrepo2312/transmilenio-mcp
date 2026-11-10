"""Tráfico del momento medido con la misma flota.

Bogotá no publica velocidades en tiempo real. Pero cada bus del feed es un sensor: si entre
dos lecturas avanzó por su recorrido, se sabe cuánto tardó de verdad y cuánto le daba el
horario para ese mismo trecho. El cociente (real / horario) es el factor de tráfico de los
tramos que recorrió. Los tramos son pares de paradas, así que las rutas que comparten
corredor (la Caracas, la 80) se informan unas a otras.
"""

from __future__ import annotations

import statistics
import threading
from collections import deque

from .. import config
from .modelos import Recorrido
from .texto import distancia_m


def avance(red, rec: Recorrido, k: int, lat: float, lon: float) -> float:
    """Qué fracción del tramo k -> k+1 lleva recorrida un punto (0 en la parada k, 1 en la k+1)."""
    if k + 1 >= len(rec.paradas):
        return 0.0
    a, b = red.paradas.get(rec.paradas[k]), red.paradas.get(rec.paradas[k + 1])
    if not (a and b):
        return 0.0
    largo = distancia_m(a.lat, a.lon, b.lat, b.lon)
    return min(1.0, distancia_m(a.lat, a.lon, lat, lon) / largo) if largo > 1 else 0.0


def posicion_horario(red, rec: Recorrido, k: int, lat: float, lon: float) -> float:
    """Segundos desde el inicio del recorrido que, según el horario, corresponden a ese punto."""
    if k + 1 >= len(rec.tiempos):
        return float(rec.tiempos[k])
    return rec.tiempos[k] + avance(red, rec, k, lat, lon) * (rec.tiempos[k + 1] - rec.tiempos[k])


class Trafico:
    def __init__(self) -> None:
        self._muestras: dict[tuple[str, str], deque[tuple[int, float]]] = {}
        self._candado = threading.Lock()

    def observar(
        self, red, rec: Recorrido, k1: int, p1: tuple[int, float, float], k2: int, p2: tuple[int, float, float]
    ) -> None:
        """Un bus pasó de (k1, p1) a (k2, p2) en el mismo recorrido; p = (ts, lat, lon)."""
        if k2 < k1:
            return
        real = p2[0] - p1[0]
        horario = posicion_horario(red, rec, k2, p2[1], p2[2]) - posicion_horario(red, rec, k1, p1[1], p1[2])
        if not (config.TRAFICO_MIN_S <= real <= config.TRAFICO_MAX_S) or horario < config.TRAFICO_MIN_S:
            return
        factor = min(config.TRAFICO_FACTOR_MAX, max(config.TRAFICO_FACTOR_MIN, real / horario))
        # Solo los tramos que de verdad recorrió: el primero si no estaba ya al final de él, el
        # último si ya iba entrando en él.
        desde = k1 + 1 if avance(red, rec, k1, p1[1], p1[2]) > 0.8 else k1
        hasta = k2 if avance(red, rec, k2, p2[1], p2[2]) > 0.2 else k2 - 1
        with self._candado:
            for k in range(desde, min(hasta + 1, len(rec.paradas) - 1)):
                clave = (rec.paradas[k], rec.paradas[k + 1])
                q = self._muestras.setdefault(clave, deque(maxlen=config.TRAFICO_MUESTRAS))
                q.append((p2[0], factor))

    def factor(self, a: str, b: str, ahora: float) -> float | None:
        """Mediana de lo medido en el tramo a -> b en los últimos minutos; None si no hay suficiente."""
        with self._candado:
            q = self._muestras.get((a, b))
            recientes = [f for ts, f in q if ahora - ts <= config.TRAFICO_VENTANA_S] if q else []
        if len(recientes) < config.TRAFICO_MIN_MUESTRAS:
            return None
        return statistics.median(recientes)

    def ritmo(self, rec: Recorrido, ahora: float) -> dict | None:
        """Cómo va un recorrido frente a su horario, con lo medido en sus tramos.

        Solo si hay medida en al menos un tercio del tiempo de horario del recorrido.
        """
        con = medido = total = 0.0
        for k in range(len(rec.paradas) - 1):
            base = rec.tiempos[k + 1] - rec.tiempos[k]
            if base <= 0:
                continue
            total += base
            f = self.factor(rec.paradas[k], rec.paradas[k + 1], ahora)
            if f is not None:
                con += base
                medido += base * f
        if not total or con / total < 1 / 3:
            return None
        factor = medido / con
        pct = round(100 * (factor - 1))
        if abs(pct) < 5:
            texto = "al ritmo del horario"
        elif pct > 0:
            texto = f"{pct} % más lento que el horario"
        else:
            texto = f"{-pct} % más rápido que el horario"
        return {"factor": round(factor, 2), "texto": texto, "cobertura_pct": round(100 * con / total)}

    def tramos_medidos(self, ahora: float) -> int:
        with self._candado:
            return sum(
                1
                for q in self._muestras.values()
                if sum(1 for ts, _ in q if ahora - ts <= config.TRAFICO_VENTANA_S) >= config.TRAFICO_MIN_MUESTRAS
            )
