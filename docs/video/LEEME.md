# Video del README

`grabar.py` graba el video cuadro por cuadro desde el mapa local, con los datos del feed en el
momento de grabar. `audio.py` le pone voz en off (Edge TTS, `es-CO-SalomeNeural`) y una música
sintetizada aquí mismo, sin derechos de terceros. El del README se grabó el martes 10 de
noviembre de 2026 a las 7:18 p. m.

Hace falta, además del paquete: `playwright` con Chrome instalado, `pillow`, `edge-tts`,
`numpy` y `ffmpeg` en el PATH. Mejor en hora pico de noche (5:30 a 7:30 p. m.).

```bash
transmilenio-web --no-abrir   # otra consola; esperar ~4 min para que el rastro sepa el sentido de cada bus
GPU=1 PORTADA=docs/img/portada.webp python -X utf8 docs/video/grabar.py ../cuadros   # ~10 min, 1.800 cuadros
python -X utf8 docs/video/audio.py ../datos_video.json ../audio.m4a
ffmpeg -framerate 30 -i ../cuadros/%05d.jpg -i ../audio.m4a -af apad \
  -c:v libx264 -crf 21 -pix_fmt yuv420p -c:a aac -shortest -movflags +faststart video.mp4
```

`grabar.py` deja `datos_video.json` junto a la carpeta de cuadros, con las cifras que dice la voz.
Los cuadros pesan ~700 MB: déjalos fuera del repo.

Para el README (GitHub acepta hasta 10 MB), dos pasadas a 1,1 Mbps:

```bash
X="-c:v libx264 -b:v 1100k -preset veryslow -x264-params aq-mode=3:bframes=8:ref=6 -pix_fmt yuv420p"
ffmpeg -framerate 30 -i ../cuadros/%05d.jpg $X -pass 1 -an -f null -
ffmpeg -framerate 30 -i ../cuadros/%05d.jpg -i ../audio.m4a -af apad $X -pass 2 \
  -c:a aac -b:a 96k -shortest -movflags +faststart video-github.mp4
```

Escenas: buses en vía · vuelo a la Calle 72 · llegadas a la estación · línea de tiempo de un bus ·
programado contra real por sistema · viajes cancelados · dos preguntas a Claude · cierre.
