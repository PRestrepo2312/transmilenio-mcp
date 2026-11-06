"""Recorta un índice real y feeds reales a unas pocas rutas, para probar sin internet.

    python tests/crear_fixtures.py <indice.json.gz> <carpeta con positions.pb, tripupdates.pb, alerts.pb>

Los fixtures del repo salieron de los datos del 5-nov-2026 a las 7:11 p. m.; la programación
(servicios y viajes por hora) es la del GTFS del 6-nov-2026, con los mismos route_id.
"""

import gzip
import json
import sys
from pathlib import Path

from google.transit import gtfs_realtime_pb2 as gtfs

CODIGOS = {"C25", "B10", "H75", "H13", "D24", "A60", "L18", "16-8", "GA567"}
DESTINO = Path(__file__).parent / "fixtures"


def main(indice_gz: str, carpeta_pb: str) -> None:
    with gzip.open(indice_gz, "rt", encoding="utf-8") as f:
        ind = json.load(f)
    rutas = {rid: r for rid, r in ind["rutas"].items() if r[0] in CODIGOS}
    patrones = [p for p in ind["patrones"] if p["r"] in rutas]
    usadas = {s for p in patrones for s in p["p"]}
    estaciones = {ind["paradas"][s][3] for s in usadas if s in ind["paradas"] and ind["paradas"][s][3]}
    vagones = {s for s, v in ind["paradas"].items() if v[3] in estaciones}
    paradas = {s: v for s, v in ind["paradas"].items() if s in usadas | estaciones | vagones}
    programacion = {r: v for r, v in ind.get("programacion", {}).items() if r in rutas}
    ind.update(rutas=rutas, patrones=patrones, paradas=paradas, programacion=programacion)
    DESTINO.mkdir(exist_ok=True)
    with gzip.open(DESTINO / "indice.json.gz", "wt", encoding="utf-8") as f:
        json.dump(ind, f, ensure_ascii=False, separators=(",", ":"))

    for nombre in ("positions.pb", "tripupdates.pb", "alerts.pb"):
        msg = gtfs.FeedMessage()
        msg.ParseFromString((Path(carpeta_pb) / nombre).read_bytes())
        recorte = gtfs.FeedMessage()
        recorte.header.CopyFrom(msg.header)
        for e in msg.entity:
            if e.HasField("vehicle"):
                guardar = e.vehicle.trip.route_id in rutas
            elif e.HasField("trip_update"):
                guardar = e.trip_update.trip.route_id in rutas
            else:
                guardar = len(recorte.entity) < 40  # alertas: con unas cuantas basta
            if guardar:
                recorte.entity.append(e)
        (DESTINO / nombre).write_bytes(recorte.SerializeToString())
        print(nombre, len(recorte.entity))
    print("rutas", len(rutas), "patrones", len(patrones), "paradas", len(paradas))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
