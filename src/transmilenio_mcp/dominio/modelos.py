from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Vehiculo:
    id: str
    numero: str  # el número pintado en el bus (vehicle.label), p. ej. "Z70-4428"
    placa: str
    ruta_id: str
    viaje_id: str
    lat: float
    lon: float
    parada_id: str  # la última parada a la que ya llegó, no la siguiente
    secuencia: int
    ts: int  # epoch del reporte de posición
    fecha_servicio: str = ""  # trip.start_date, "20261105"
    salida: str = ""  # trip.start_time, la hora programada de salida del viaje: "17:05:00"


@dataclass(frozen=True, slots=True)
class Parada:
    id: str
    nombre: str
    lat: float
    lon: float
    estacion_id: str | None  # si es un vagón o plataforma, la estación a la que pertenece
    es_estacion: bool


@dataclass(frozen=True, slots=True)
class Ruta:
    id: str
    codigo: str  # lo que se lee en el bus: B10, C25, 16-8
    nombre: str
    sistema: str


@dataclass(frozen=True, slots=True)
class Recorrido:
    """Secuencia de paradas de un trazado de una ruta, con el tiempo típico a cada una."""

    indice: int
    ruta_id: str
    paradas: tuple[str, ...]
    secuencias: tuple[int, ...]
    tiempos: tuple[int, ...]  # segundos desde la primera parada (mediana del horario)

    @property
    def clave(self) -> str:
        return f"{self.ruta_id}:{self.indice}"


@dataclass(frozen=True, slots=True)
class Resumen:
    origen: str
    destino: str
    sentido: str | None  # "Sur-Norte", "Circular"...
    rumbo: int | None  # grados, 0 = norte
    num_paradas: int
    duracion_min: int | None
    extremos: tuple[str, ...] | None = None  # nombre comercial de las zonales: ("Engativá", "Unicentro")
    pasa_por: str | None = None  # en circulares, el punto más lejano del origen
    k_lejos: int | None = None

    @property
    def circular(self) -> bool:
        return self.sentido == "Circular"

    def publico(self) -> dict:
        d = {
            "origen": self.origen,
            "destino": self.destino,
            "sentido": self.sentido,
            "rumbo": self.rumbo,
            "num_paradas": self.num_paradas,
            "duracion_min": self.duracion_min,
        }
        if self.extremos:
            d["extremos"] = list(self.extremos)
        if self.pasa_por:
            d["pasa_por"] = self.pasa_por
        return d
