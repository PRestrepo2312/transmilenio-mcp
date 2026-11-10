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

**Las llegadas se estiman, no se leen.** Los feeds no traen la hora prevista en las siguientes
paradas. La estimación (`dominio/estimacion.py`) usa la posición del bus dentro de su tramo y el
tiempo de cada tramo que le falta: el del horario por el factor de tráfico medido. Se descartan
buses que llevan más de 5 minutos sin reportar y llegadas que, según el cálculo, debieron ocurrir
hace más de 2 minutos.

**Tráfico con la flota como sensor** (`dominio/trafico.py`). Cada vez que se ubica un bus se
compara con dónde iba el mismo bus, en el mismo recorrido, hace entre 4 y 15 minutos: tiempo real
contra lo que da el horario para ese trecho. El cociente queda como muestra en cada tramo recorrido
(par de paradas, compartido entre rutas). El factor de un tramo es la mediana de sus muestras de
los últimos 20 minutos, con al menos 2. La ventana mínima importa: entre lecturas seguidas (~1 min)
un bus detenido en un semáforo no avanza, la medida se descarta y el factor sale optimista; así
medido, el backtest daba llegadas 4 minutos adelantadas a 10-20 minutos. Backtest del 10-nov
(35 min al mediodía, 222 mil llegadas verificadas con lecturas posteriores): error medio 2,09 →
1,70 min; 0-5 min 1,26 → 1,11; 5-10 min 2,45 → 1,91; 10-20 min 3,58 → 2,78; sesgo +0,13 → -0,12.
La verdad sale de la misma ubicación geométrica, así que no corrige sus errores; y es un solo
rato de un día: falta repetirlo en hora pico. Con 7 minutos de ventana mínima da lo mismo.

**El bus se ubica por geometría.** Hasta el 5-nov-2026 el feed traía `stop_id` y
`current_stop_sequence` coherentes con la posición. Desde el 10-nov ya no: la parada reportada
queda en la mediana a 6 km del bus, `start_time` es la hora del reporte y los `trip_id` no están
en el GTFS. Solo la posición, la ruta y el bus son confiables. `Red.ubicar` usa la parada del feed
si queda a menos de 400 m del bus (así sigue sirviendo si TransMilenio lo corrige); si no, busca
el tramo (recta entre dos paradas seguidas) de los recorridos de la ruta más cercano al bus, a
menos de 250 m. Ida y vuelta por la misma vía empatan en distancia: las separa el rumbo del bus,
que sale de `Rastro` (sus posiciones de los últimos 7 minutos, en memoria). Sin rumbo y con tramos
empatados en sentidos opuestos, el bus no se ubica: mejor faltar que dar una llegada falsa (la
regla "va por la derecha, más cerca de sus paraderos" acertó solo el 73 % en los zonales). Como
TransMilenio regenera el feed cada 60-75 s, tras cada consulta un hilo sigue leyendo el feed
15 minutos para que la siguiente encuentre el rastro al día. Medido el 10-nov al mediodía: en
frío se ubica el 56 % de la flota, tras un minuto el 88 % y luego 93-95 %; dos minutos después el
94 % de los ubicados sigue en la misma variante y más adelante.

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
ruta, la suma y el máximo de buses en las fotos, y cada viaje visto por su `trip_id` (estable
mientras dura el viaje). Si el feed no trae la hora programada de salida, como pasa desde el
10-nov-2026, el viaje cuenta en la hora en que se vio por primera vez. Solo se comparan horas
con al menos la mitad de las fotos esperadas, para que un rato con el recolector apagado no
parezca un rato sin buses. TransMiCable queda fuera de las comparaciones porque sus cabinas no
reportan en el feed.

**Viajes cancelados.** Desde el 10-nov-2026 `tripupdates.pb` trae todos los viajes del día de
servicio (~83 mil), cada uno con su hora programada y un `schedule_relationship`: SCHEDULED,
CANCELED o ADDED. No trae tiempos por parada. Los programados más los cancelados coinciden con
los viajes del GTFS de ese día (el C25 zonal, 105 y 105). `viajes_cancelados` cuenta por ruta y
hora de salida: el día en curso sale del feed y queda guardado en la tabla `estados`; otros días
salen de esa tabla, que el recolector actualiza cada 10 minutos. Es lo que declara el operador,
no una verificación de que el bus salió.

**Una caída del feed no se cuenta como buses.** Si el último reporte no cambia entre lecturas, se
anota la lectura (para `salud_feed`) y no se suma nada.

**La red se puede reemplazar sin cortar el servicio.** `CargadorRed` la carga en un hilo, la
reintenta cada minuto si falló y la refresca cuando cumple 3 días. Mientras tanto se sigue
respondiendo con la anterior.

## Pruebas

`tests/fixtures/` guarda un recorte real del 5-nov-2026: 18 rutas, 184 buses y 40 alertas. Las
pruebas no usan internet. Para regenerarlos está `tests/crear_fixtures.py`.

## Pendiente

- Intervalos reales entre buses de una misma ruta en una parada (frecuencia vista vs. programada).
- Versión del mapa para GitHub Pages con un proxy CORS (el feed no envía cabeceras CORS).
