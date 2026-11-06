"""Historial local de la flota en SQLite, para las preguntas de veedor.

El recolector (`transmilenio-veedor`) lee el feed cada minuto y guarda:

- lecturas: cada lectura y qué tan viejo venía el último reporte. Sirve para medir cuánto
  tiempo estuvo caído el feed.
- muestras y conteos: buses en vía por ruta, agregados por hora (suma para el promedio y
  máximo). Guardar cada foto serían ~1 M de filas al día; por hora son ~16 mil.
- viajes: cada viaje visto (el trip_id del horario oficial), con su bus, cuándo se vio por
  primera y última vez, y el último retraso reportado.

Un día completo ocupa entre 5 y 10 MB. Se abre una conexión por operación: el recolector escribe
y el MCP o el mapa leen al tiempo sin pisarse (modo WAL).
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .. import config
from ..dominio.modelos import Vehiculo

BOGOTA = dt.timezone(dt.timedelta(hours=-5), "America/Bogota")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS lecturas (
    leido INTEGER PRIMARY KEY,      -- epoch de la lectura
    ultimo_reporte INTEGER,         -- epoch del reporte más nuevo que traía el feed
    buses INTEGER,
    nueva INTEGER                   -- 1 si traía datos nuevos y se contó
);
CREATE TABLE IF NOT EXISTS muestras (
    fecha TEXT, hora INTEGER, n INTEGER,
    PRIMARY KEY (fecha, hora)
);
CREATE TABLE IF NOT EXISTS conteos (
    fecha TEXT, hora INTEGER, ruta_id TEXT, suma INTEGER, maximo INTEGER,
    PRIMARY KEY (fecha, hora, ruta_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS viajes (
    fecha TEXT,                     -- día de servicio del viaje (trip.start_date)
    viaje_id TEXT, ruta_id TEXT,
    salida TEXT,                    -- hora programada de salida, "HH:MM:SS"
    bus TEXT,
    visto_desde INTEGER, visto_hasta INTEGER,
    retraso_s INTEGER,
    PRIMARY KEY (fecha, viaje_id)
) WITHOUT ROWID;
"""


def ruta_por_defecto() -> Path:
    return Path(config.VEEDOR_DB) if config.VEEDOR_DB else config.carpeta_cache() / "historial.sqlite"


def fecha_hora(epoch: float) -> tuple[str, int]:
    d = dt.datetime.fromtimestamp(epoch, BOGOTA)
    return d.date().isoformat(), d.hour


def _fecha_servicio(v: Vehiculo) -> str:
    f = v.fecha_servicio
    if len(f) == 8 and f.isdigit():
        return f"{f[:4]}-{f[4:6]}-{f[6:]}"
    return fecha_hora(v.ts)[0]


class Historial:
    def __init__(self, ruta: Path | str | None = None) -> None:
        self.ruta = Path(ruta) if ruta else ruta_por_defecto()
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self._conexion() as c:
            c.executescript(ESQUEMA)

    @contextmanager
    def _conexion(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.ruta, timeout=30)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            with c:  # transacción: commit al salir, rollback si algo falla
                yield c
        finally:
            c.close()

    # ------------------------------------------------------------ escritura

    def registrar(self, leido: float, vehiculos: list[Vehiculo], retrasos: dict[str, int] | None = None) -> bool:
        """Guarda una lectura del feed. Devuelve False si no traía nada nuevo (feed detenido)."""
        ultimo = max((v.ts for v in vehiculos), default=0)
        retrasos = retrasos or {}
        with self._conexion() as c:
            previo = c.execute("SELECT MAX(ultimo_reporte) FROM lecturas WHERE nueva = 1").fetchone()[0] or 0
            nueva = ultimo > previo
            c.execute(
                "INSERT OR REPLACE INTO lecturas VALUES (?, ?, ?, ?)", (int(leido), ultimo, len(vehiculos), int(nueva))
            )
            if not nueva:
                return False

            # Solo cuentan los buses que reportaron hace poco: los demás pueden estar varados,
            # en el patio o sin GPS.
            vigentes = [v for v in vehiculos if v.ruta_id and ultimo - v.ts <= config.BUS_VIEJO_S]
            fecha, hora = fecha_hora(ultimo)
            c.execute(
                "INSERT INTO muestras VALUES (?, ?, 1) ON CONFLICT (fecha, hora) DO UPDATE SET n = n + 1",
                (fecha, hora),
            )
            por_ruta = Counter(v.ruta_id for v in vigentes)
            c.executemany(
                """INSERT INTO conteos VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (fecha, hora, ruta_id) DO UPDATE SET
                       suma = suma + excluded.suma, maximo = MAX(maximo, excluded.maximo)""",
                [(fecha, hora, r, n, n) for r, n in por_ruta.items()],
            )
            c.executemany(
                """INSERT INTO viajes VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (fecha, viaje_id) DO UPDATE SET
                       bus = excluded.bus,
                       visto_hasta = MAX(visto_hasta, excluded.visto_hasta),
                       retraso_s = COALESCE(excluded.retraso_s, retraso_s)""",
                [
                    (
                        _fecha_servicio(v),
                        v.viaje_id,
                        v.ruta_id,
                        v.salida,
                        v.numero,
                        v.ts,
                        v.ts,
                        retrasos.get(v.viaje_id),
                    )
                    for v in vigentes
                    if v.viaje_id
                ],
            )
            return True

    # ------------------------------------------------------------ lectura

    def fechas(self) -> list[str]:
        with self._conexion() as c:
            return [f for (f,) in c.execute("SELECT DISTINCT fecha FROM muestras ORDER BY fecha")]

    def cobertura(self, fechas: Iterable[str]) -> dict[tuple[str, int], int]:
        """Fotos guardadas por (fecha, hora)."""
        fechas = list(fechas)
        if not fechas:
            return {}
        marcas = ",".join("?" * len(fechas))
        with self._conexion() as c:
            filas = c.execute(f"SELECT fecha, hora, n FROM muestras WHERE fecha IN ({marcas})", fechas)
            return {(f, h): n for f, h, n in filas}

    def conteos(
        self, fechas: Iterable[str], rutas: Iterable[str] | None = None
    ) -> list[tuple[str, int, str, int, int]]:
        """(fecha, hora, ruta_id, suma de buses en las fotos, máximo en una foto)."""
        fechas = list(fechas)
        if not fechas:
            return []
        sql = f"SELECT fecha, hora, ruta_id, suma, maximo FROM conteos WHERE fecha IN ({','.join('?' * len(fechas))})"
        args: list = fechas
        if rutas is not None:
            rutas = list(rutas)
            sql += f" AND ruta_id IN ({','.join('?' * len(rutas))})"
            args = fechas + rutas
        with self._conexion() as c:
            return c.execute(sql, args).fetchall()

    def viajes(
        self, fechas: Iterable[str], rutas: Iterable[str] | None = None
    ) -> list[tuple[str, str, int, int, float | None]]:
        """(fecha, ruta_id, hora de salida, viajes vistos, retraso promedio en segundos)."""
        fechas = list(fechas)
        if not fechas:
            return []
        sql = f"""SELECT fecha, ruta_id, CAST(substr(salida, 1, 2) AS INTEGER) % 24 AS h,
                         COUNT(*), AVG(retraso_s)
                  FROM viajes WHERE fecha IN ({",".join("?" * len(fechas))}) AND salida != ''"""
        args: list = fechas
        if rutas is not None:
            rutas = list(rutas)
            sql += f" AND ruta_id IN ({','.join('?' * len(rutas))})"
            args = fechas + rutas
        sql += " GROUP BY fecha, ruta_id, h"
        with self._conexion() as c:
            return c.execute(sql, args).fetchall()

    def lecturas(self, desde: float) -> list[tuple[int, int, int]]:
        """(leído, último reporte, buses) desde un instante, en orden."""
        with self._conexion() as c:
            return c.execute(
                "SELECT leido, ultimo_reporte, buses FROM lecturas WHERE leido >= ? ORDER BY leido", (int(desde),)
            ).fetchall()
