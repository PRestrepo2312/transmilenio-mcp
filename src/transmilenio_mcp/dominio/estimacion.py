"""Cuánto le falta a un bus para llegar a una parada.

TransMilenio reporta la posición, no la hora prevista en las siguientes paradas. La
estimación: qué parte del tramo actual ya recorrió el bus (por distancia en línea recta)
más el tiempo de los tramos que le quedan. Cada tramo vale lo que da el horario oficial,
corregido por el tráfico que la flota midió ahí en los últimos minutos, si lo hay.
"""

from __future__ import annotations

from .. import config
from .modelos import Recorrido, Vehiculo
from .red import Red
from .trafico import Trafico, avance


def segundos_hasta(
    red: Red, v: Vehiculo, rec: Recorrido, k: int, j: int, trafico: Trafico | None = None, ahora: float | None = None
) -> float:
    """Desde el momento del reporte del bus hasta la parada j (j > k)."""

    def tramo(i: int) -> float:
        base = rec.tiempos[i + 1] - rec.tiempos[i]
        if trafico is not None:
            f = trafico.factor(rec.paradas[i], rec.paradas[i + 1], ahora if ahora is not None else v.ts)
            if f is not None:
                return base * f
        return base

    falta = (1 - avance(red, rec, k, v.lat, v.lon)) * tramo(k)
    return falta + sum(tramo(i) for i in range(k + 1, j))


def segundos_desde_ref(
    red: Red, v: Vehiculo, rec: Recorrido, k: int, j: int, ref: float, trafico: Trafico | None = None
) -> int:
    """Positivo: falta eso. Negativo: según el cálculo ya debió haber llegado."""
    return int(v.ts + segundos_hasta(red, v, rec, k, j, trafico, ref) - ref)


def llegada_creible(en_s: int) -> bool:
    return en_s >= -config.ETA_PASADA_TOLERANCIA_S


def reporte_vigente(v: Vehiculo, ref: float) -> bool:
    return ref - v.ts <= config.BUS_VIEJO_S
