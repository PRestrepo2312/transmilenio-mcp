# Arquitectura

```
                       gtfs.transmilenio.gov.co                storage.googleapis.com/gtfs-estaticos
                  positions.pb  tripupdates.pb  alerts.pb             GTFS_YYYYMMDD.zip (diario)
                               │                                              │
                     datos/gtfs_rt.py                              datos/gtfs_estatico.py
                caché de 15 s y candado por feed;              descarga, recorta a ~0,4 MB y
                si falla, devuelve la lectura anterior          guarda en caché (3 días)
                               │                                              │
                               │                                    dominio/red.py
                               │                       rutas, paradas, recorridos, búsquedas,
                               │                       origen, destino y sentido de cada recorrido
                               │                                              │
                               └──────────────────► servicios.py ◄────────────┘
                                         llegadas, rutas, un bus, cercanos, alertas
                                         (dominio/estimacion.py calcula los tiempos)
                                                 │                    │
                                        servidor_mcp.py        servidor_web.py + web/
                                        Claude y otros         mapa en el navegador
                                        clientes MCP
                                                 │
                                            veedor.py  ◄── datos/historial.py (SQLite)
                                  programado vs. observado        ▲
                                                                  │
                                                     recolector.py: una lectura por minuto
```

## Decisiones

**Todo corre en la máquina del usuario.** No hay servidor propio en el medio ni API key. Cada
instalación le pide a TransMilenio como mucho una lectura por feed cada 15 segundos.

**El índice se arma una vez y se guarda.** El GTFS oficial pesa 180 MB y `stop_times.txt` tiene
9,5 millones de filas sin orden. Para cada recorrido se toma una muestra de 8 viajes y se guarda
la mediana del tiempo desde la primera parada. Sale un archivo de 0,4 MB que carga en menos de un
segundo. Una GitHub Action lo puede publicar ya armado (`TRANSMI_INDICE_URL`).

**Las llegadas se estiman, no se leen.** `tripupdates.pb` solo trae la última parada alcanzada y
el retraso. La estimación (`dominio/estimacion.py`) usa la posición del bus dentro de su tramo y los
tiempos del horario. Se descartan buses que llevan más de 5 minutos sin reportar y llegadas que,
según el cálculo, debieron ocurrir hace más de 2 minutos.

**Una variante es un recorrido, no un código.** El código C25 existe como troncal y como zonal, y
cada uno puede tener ida, regreso o recorridos cortos. El filtro y el sentido se calculan por
recorrido (`ruta_id:indice`).

**Rutas circulares.** Si el origen y el destino quedan a menos de 800 m, la ruta es circular. El
sentido de cada bus depende de si va antes o después del punto más lejano del recorrido ("Hacia
Unicentro" o "Regresa a Engativá").

**Veedor: programado contra observado.** La programación sale del GTFS: en la misma pasada por
`stop_times.txt` se guarda la primera y la última hora de cada viaje (181 mil en un día hábil) y
con eso, por ruta y `service_id`, cuántos viajes salen en cada hora y cuántos están andando a cada
HH:30. El calendario (`calendar.txt` y `calendar_dates.txt`) dice qué servicios operan cada día,
así un lunes festivo usa el horario de domingo. Lo observado lo guarda `recolector.py`: por hora y
ruta, la suma y el máximo de buses en las fotos, y cada viaje visto (los `trip_id` del feed son los
del horario). Solo se comparan horas con al menos la mitad de las fotos esperadas, para que un
rato con el recolector apagado no parezca un rato sin buses. TransMiCable queda fuera de las
comparaciones porque sus cabinas no reportan en el feed.

**Una caída del feed no se cuenta como buses.** Si el último reporte no cambia entre lecturas, se
anota la lectura (para `salud_feed`) y no se suma nada.

**La red se puede reemplazar sin cortar el servicio.** `CargadorRed` la carga en un hilo, la
reintenta cada minuto si falló y la refresca cuando cumple 3 días. Mientras tanto se sigue
respondiendo con la anterior.

## Pruebas

`tests/fixtures/` guarda un recorte real del 5-nov-2026: 18 rutas, 184 buses y 40 alertas. Las
pruebas no usan internet. Para regenerarlos está `tests/crear_fixtures.py`.

## Pendiente

- Usar los propios buses para medir los tiempos reales entre paradas (tráfico del momento).
- Intervalos reales entre buses de una misma ruta en una parada (frecuencia vista vs. programada).
- Versión del mapa para GitHub Pages con un proxy CORS (el feed no envía cabeceras CORS).
