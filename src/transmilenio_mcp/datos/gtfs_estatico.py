"""GTFS estático de TransMilenio reducido a un índice de ~0,4 MB.

El zip oficial pesa ~180 MB (stop_times.txt son ~580 MB descomprimido). Para responder en
tiempo real basta con rutas, paradas y, por cada recorrido, la secuencia de paradas con el
tiempo típico desde la primera. Para el veedor se guarda además la programación: cuántos
viajes salen por hora y cuántos buses deberían estar en vía, por ruta y tipo de día.

    transmilenio-indice              descarga el GTFS más reciente y construye
    transmilenio-indice gtfs.zip     construye desde un zip local
    transmilenio-indice -o x.json.gz
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import json
import re
import statistics
import tempfile
import time
import urllib.parse
import zipfile
from collections import defaultdict
from pathlib import Path

import httpx

from .. import config
from ..config import log

VERSION = 2
MUESTRAS_POR_RECORRIDO = 8
LICENCIA = "CC BY-SA 4.0, derivado del GTFS de TransMilenio S.A."

_FECHA_EN_NOMBRE = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")


# ---------------------------------------------------------------- descarga


def listar_bucket(cliente: httpx.Client) -> list[dict]:
    url = f"https://storage.googleapis.com/storage/v1/b/{config.GTFS_BUCKET}/o"
    items, token = [], None
    while True:
        params = {"fields": "items(name,updated,size),nextPageToken", "maxResults": "1000"}
        if token:
            params["pageToken"] = token
        r = cliente.get(url, params=params, timeout=60)
        r.raise_for_status()
        datos = r.json()
        items += datos.get("items", [])
        token = datos.get("nextPageToken")
        if not token:
            return items


def elegir_mas_reciente(items: list[dict]) -> dict:
    """El zip con la fecha más nueva en el nombre; `updated` solo desempata.

    Los nombres vienen en varios formatos (GTFS_20261105.zip, GTFS-2026-04-29.zip,
    "2026-03-20 04:00:29_Static.zip"). `updated` sola no sirve: cambia si alguien
    vuelve a subir un archivo viejo.
    """
    zips = [i for i in items if i["name"].lower().endswith(".zip")]
    if not zips:
        raise RuntimeError("El bucket público de GTFS de TransMilenio no tiene archivos .zip")

    def clave(i: dict) -> tuple[str, str]:
        m = _FECHA_EN_NOMBRE.search(i["name"])
        return ("".join(m.groups()) if m else "", i.get("updated", ""))

    return max(zips, key=clave)


def descargar(destino: Path) -> dict:
    with httpx.Client(follow_redirects=True, headers={"User-Agent": config.USER_AGENT}) as c:
        info = elegir_mas_reciente(listar_bucket(c))
        url = f"https://storage.googleapis.com/{config.GTFS_BUCKET}/{urllib.parse.quote(info['name'])}"
        log(f"Descargando GTFS oficial {info['name']} ({int(info.get('size', 0)) / 1e6:.0f} MB)...")
        with c.stream("GET", url, timeout=600) as r:
            r.raise_for_status()
            with open(destino, "wb") as f:
                for trozo in r.iter_bytes(1 << 20):
                    f.write(trozo)
    return info


# ---------------------------------------------------------------- construcción


def _segundos(hhmmss: str) -> int:
    h, m, s = hhmmss.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def _calendario(filas_cal, filas_fechas) -> dict[str, dict]:
    """service_id -> días de la semana (lunes primero), vigencia y excepciones (festivos)."""
    dias = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    servicios = {
        c["service_id"]: {
            "dias": "".join(c[d].strip() or "0" for d in dias),
            "desde": c["start_date"],
            "hasta": c["end_date"],
            "mas": [],
            "menos": [],
        }
        for c in filas_cal
    }
    for e in filas_fechas:
        s = servicios.setdefault(e["service_id"], {"dias": "0000000", "desde": "", "hasta": "", "mas": [], "menos": []})
        s["mas" if e["exception_type"].strip() == "1" else "menos"].append(e["date"])
    return servicios


def _programar(prog: dict, ruta_id: str, servicio: str, ini: int, fin: int) -> None:
    """Suma un viaje: sale en la hora de `ini` y está en vía en cada HH:30 entre `ini` y `fin`."""
    salidas, en_via = prog[ruta_id].setdefault(servicio, [[0] * 24, [0] * 24])
    salidas[(ini // 3600) % 24] += 1
    h = max(0, -(-(ini - 1800) // 3600))  # primera hora h con h:30 >= ini
    while h * 3600 + 1800 < fin:
        en_via[h % 24] += 1
        h += 1


def construir(zip_path: Path, info_gtfs: dict | None = None) -> dict:
    t0 = time.time()
    z = zipfile.ZipFile(zip_path)

    def filas(nombre: str):
        return csv.DictReader(io.TextIOWrapper(z.open(nombre), "utf-8-sig"))

    agencias = {a["agency_id"]: a["agency_name"] for a in filas("agency.txt")}
    rutas = {
        r["route_id"]: [
            (r.get("route_short_name") or "").strip(),
            (r.get("route_long_name") or "").strip(),
            r.get("agency_id") or "",
            (r.get("route_color") or "").strip(),
        ]
        for r in filas("routes.txt")
    }
    paradas = {}
    for s in filas("stops.txt"):
        try:
            lat, lon = round(float(s["stop_lat"]), 6), round(float(s["stop_lon"]), 6)
        except (TypeError, ValueError):
            continue
        paradas[s["stop_id"]] = [
            " ".join((s.get("stop_name") or "").split()),
            lat,
            lon,
            s.get("parent_station") or "",
            int(s.get("location_type") or 0),
        ]

    nombres = set(z.namelist())
    servicios = _calendario(
        filas("calendar.txt") if "calendar.txt" in nombres else [],
        filas("calendar_dates.txt") if "calendar_dates.txt" in nombres else [],
    )
    frecuencias: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    if "frequencies.txt" in nombres:
        for fr in filas("frequencies.txt"):
            frecuencias[fr["trip_id"]].append(
                (_segundos(fr["start_time"]), _segundos(fr["end_time"]), max(1, int(fr["headway_secs"])))
            )

    # Muestra de viajes por (ruta, trazado), repartida a lo largo del archivo.
    viajes_por_clave: dict[tuple[str, str], list[str]] = defaultdict(list)
    servicio_viaje: dict[str, tuple[str, str]] = {}
    for t in filas("trips.txt"):
        viajes_por_clave[(t["route_id"], t.get("shape_id") or "")].append(t["trip_id"])
        servicio_viaje[t["trip_id"]] = (t["route_id"], t.get("service_id") or "")
    muestra: dict[str, tuple[str, str]] = {}
    for clave, viajes in viajes_por_clave.items():
        paso = max(1, len(viajes) // MUESTRAS_POR_RECORRIDO)
        for v in viajes[::paso][:MUESTRAS_POR_RECORRIDO]:
            muestra[v] = clave

    # stop_times.txt no viene ordenado (~9,5 M filas): una sola pasada que guarda la muestra
    # y, de todos los viajes, la primera y la última hora (como texto "HH:MM:SS", que con el
    # cero a la izquierda se compara bien sin convertir 9,5 M veces).
    paradas_viaje: dict[str, list[tuple[int, str, int]]] = defaultdict(list)
    extremos: dict[str, list[str]] = {}
    lector = csv.reader(io.TextIOWrapper(z.open("stop_times.txt"), "utf-8-sig"))
    cab = next(lector)
    i_trip, i_arr, i_stop, i_seq = (cab.index(c) for c in ("trip_id", "arrival_time", "stop_id", "stop_sequence"))
    for fila in lector:
        viaje, hora = fila[i_trip], fila[i_arr].strip()
        if not hora:
            continue
        if len(hora) == 7:
            hora = "0" + hora
        if viaje in muestra:
            paradas_viaje[viaje].append((int(fila[i_seq]), fila[i_stop], _segundos(hora)))
        e = extremos.get(viaje)
        if e is None:
            extremos[viaje] = [hora, hora]
        elif hora < e[0]:
            e[0] = hora
        elif hora > e[1]:
            e[1] = hora

    programacion: dict[str, dict[str, list]] = defaultdict(dict)
    for viaje, (ini_txt, fin_txt) in extremos.items():
        if viaje not in servicio_viaje:
            continue
        ruta_id, servicio = servicio_viaje[viaje]
        ini, fin = _segundos(ini_txt), _segundos(fin_txt)
        if viaje in frecuencias:
            # Viaje plantilla (TransMiCable): sale cada headway dentro de cada ventana.
            for desde, hasta, cada in frecuencias[viaje]:
                for salida in range(desde, hasta, cada):
                    _programar(programacion, ruta_id, servicio, salida, salida + fin - ini)
        else:
            _programar(programacion, ruta_id, servicio, ini, fin)

    grupos: dict[tuple[str, str], dict[tuple, list]] = defaultdict(lambda: defaultdict(list))
    for viaje, filas_v in paradas_viaje.items():
        filas_v.sort()
        secuencia = tuple((q, p) for q, p, _ in filas_v)
        t_ini = filas_v[0][2]
        grupos[muestra[viaje]][secuencia].append([t - t_ini for _, _, t in filas_v])

    recorridos = []
    for (ruta_id, _trazado), por_secuencia in grupos.items():
        secuencia, tiempos = max(por_secuencia.items(), key=lambda kv: len(kv[1]))
        recorridos.append(
            {
                "r": ruta_id,
                "p": [p for _, p in secuencia],
                "q": [q for q, _ in secuencia],
                "t": [int(statistics.median(col)) for col in zip(*tiempos, strict=True)],
            }
        )

    log(
        f"Índice listo en {time.time() - t0:.0f} s: {len(rutas)} rutas, {len(paradas)} paradas, "
        f"{len(recorridos)} recorridos, {len(extremos)} viajes programados."
    )
    return {
        "version": VERSION,
        "generado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "gtfs": info_gtfs or {"name": Path(zip_path).name},
        "licencia": LICENCIA,
        "agencias": agencias,
        "rutas": rutas,
        "paradas": paradas,
        "patrones": recorridos,
        "servicios": servicios,
        "programacion": programacion,
    }


# ---------------------------------------------------------------- caché


def guardar(indice: dict, ruta: Path) -> None:
    tmp = ruta.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(ruta)


def leer(ruta: Path) -> dict:
    with gzip.open(ruta, "rt", encoding="utf-8") as f:
        return json.load(f)


def _leer_valido(ruta: Path) -> dict | None:
    try:
        ind = leer(ruta)
    except Exception as e:
        log(f"Índice en caché ilegible ({e}).")
        return None
    return ind if ind.get("version") == VERSION else None


def obtener_indice() -> dict:
    """Caché fresca, luego índice publicado, luego construcción local, luego caché vieja."""
    archivo = config.carpeta_cache() / "indice.json.gz"
    fresca = archivo.exists() and (time.time() - archivo.stat().st_mtime) / 3600 < config.INDICE_MAX_EDAD_H
    if fresca and (ind := _leer_valido(archivo)):
        return ind

    if config.INDICE_URL:
        try:
            log(f"Descargando índice publicado: {config.INDICE_URL}")
            r = httpx.get(config.INDICE_URL, follow_redirects=True, timeout=120)
            r.raise_for_status()
            ind = json.loads(gzip.decompress(r.content))
            if ind.get("version") == VERSION:
                guardar(ind, archivo)
                return ind
            log("El índice publicado es de otra versión; se construye local.")
        except Exception as e:
            log(f"No se pudo bajar el índice publicado ({e}); se construye local.")

    try:
        with tempfile.TemporaryDirectory() as d:
            zp = Path(d) / "gtfs.zip"
            ind = construir(zp, descargar(zp))
        guardar(ind, archivo)
        return ind
    except Exception:
        if archivo.exists() and (viejo := _leer_valido(archivo)):
            log("No se pudo actualizar el índice; se usa la copia en caché.")
            return viejo
        raise


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Construye el índice del GTFS de TransMilenio.")
    ap.add_argument("zip", nargs="?", help="GTFS .zip local (por defecto descarga el más reciente)")
    ap.add_argument("-o", "--salida", help="archivo .json.gz de salida (por defecto, la caché)")
    a = ap.parse_args()
    salida = Path(a.salida) if a.salida else config.carpeta_cache() / "indice.json.gz"
    if a.zip:
        ind = construir(Path(a.zip), {"name": Path(a.zip).name})
    else:
        with tempfile.TemporaryDirectory() as d:
            zp = Path(d) / "gtfs.zip"
            ind = construir(zp, descargar(zp))
    guardar(ind, salida)
    log(f"Guardado en {salida} ({salida.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
