"""Lectura de los tres feeds GTFS Realtime de TransMilenio."""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from google.transit import gtfs_realtime_pb2 as gtfs

from .. import config
from ..dominio.modelos import Vehiculo

_BOGOTA = dt.timezone(dt.timedelta(hours=-5))


def _salida_programada(start_time: str, ts: int) -> str:
    """La hora programada de salida del viaje, o "" si el feed no la trae de verdad.

    Desde el 10-nov-2026 el feed manda en start_time la misma hora del reporte de posición,
    que cambia en cada lectura; eso no es la salida programada.
    """
    if not start_time or not ts:
        return start_time
    try:
        h, m, s = (int(x) for x in start_time.split(":"))
    except ValueError:
        return ""
    reporte = dt.datetime.fromtimestamp(ts, _BOGOTA)
    diferencia = abs((h % 24) * 3600 + m * 60 + s - (reporte.hour * 3600 + reporte.minute * 60 + reporte.second))
    return "" if min(diferencia, 86400 - diferencia) <= 90 else start_time


@dataclass(frozen=True)
class Lectura:
    mensaje: gtfs.FeedMessage
    leido_en: float
    # True si la descarga más reciente falló y esto es la copia anterior.
    de_respaldo: bool = False


class FeedsRT:
    """Descarga con caché corta por feed.

    Un candado por feed: si TransMilenio tarda con las posiciones, las alertas no esperan.
    Si una descarga falla y hay copia anterior, se devuelve esa copia marcada como respaldo
    en lugar de tumbar la consulta.
    """

    def __init__(
        self,
        cliente: httpx.Client | None = None,
        base: str = config.RT_BASE,
        reloj: Callable[[], float] = time.time,
    ) -> None:
        self._http = cliente or httpx.Client(timeout=config.FEED_TIMEOUT_S, headers={"User-Agent": config.USER_AGENT})
        self._base = base
        self._reloj = reloj
        self._cache: dict[str, Lectura] = {}
        self._candados = {nombre: threading.Lock() for nombre in config.FEEDS}

    def leer(self, nombre: str) -> Lectura:
        with self._candados[nombre]:
            previa = self._cache.get(nombre)
            if previa and not previa.de_respaldo and self._reloj() - previa.leido_en < config.FEED_TTL_S:
                return previa
            try:
                r = self._http.get(self._base + config.FEEDS[nombre])
                r.raise_for_status()
                msg = gtfs.FeedMessage()
                msg.ParseFromString(r.content)
            except Exception:
                if previa is None:
                    raise
                previa = Lectura(previa.mensaje, previa.leido_en, de_respaldo=True)
                self._cache[nombre] = previa
                return previa
            lectura = Lectura(msg, self._reloj())
            self._cache[nombre] = lectura
            return lectura

    def vehiculos(self) -> tuple[list[Vehiculo], Lectura]:
        lectura = self.leer("posiciones")
        out = []
        for e in lectura.mensaje.entity:
            if not e.HasField("vehicle"):
                continue
            v = e.vehicle
            out.append(
                Vehiculo(
                    id=v.vehicle.id or e.id,
                    numero=v.vehicle.label,
                    placa=v.vehicle.license_plate,
                    ruta_id=v.trip.route_id,
                    viaje_id=v.trip.trip_id,
                    lat=v.position.latitude,
                    lon=v.position.longitude,
                    parada_id=v.stop_id,
                    secuencia=v.current_stop_sequence,
                    ts=v.timestamp,
                    fecha_servicio=v.trip.start_date,
                    salida=_salida_programada(v.trip.start_time, v.timestamp),
                )
            )
        return out, lectura

    def retrasos(self) -> dict[str, int]:
        """Retraso frente al horario (segundos, positivo = tarde) por viaje."""
        out = {}
        for e in self.leer("viajes").mensaje.entity:
            if e.HasField("trip_update") and e.trip_update.HasField("delay"):
                out[e.trip_update.trip.trip_id] = e.trip_update.delay
        return out

    def alertas(self) -> list[gtfs.Alert]:
        return [e.alert for e in self.leer("alertas").mensaje.entity if e.HasField("alert")]
