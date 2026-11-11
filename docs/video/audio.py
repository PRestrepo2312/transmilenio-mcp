"""Sonido del video: voz en off (Edge TTS, es-CO) y una música de fondo hecha aquí mismo.

    python audio.py <datos_video.json> <salida.m4a>

`datos_video.json` lo escribe grabar.py con las cifras del momento de grabar y la duración de
cada escena. La música es una síntesis propia (acordes suaves y un arpegio), sin derechos de
terceros. La voz se baja con ffmpeg: la música se agacha cuando habla (sidechain) y el total
queda en -16 LUFS, lo normal para redes.
"""

import asyncio
import json
import subprocess
import sys
import wave
from pathlib import Path

import edge_tts
import numpy as np

VOZ = "es-CO-SalomeNeural"
SR = 44100
AQUI = Path(__file__).parent


def guion(d: dict) -> dict[str, str]:
    pct = f"{d['pct_zonal']:.1f}".replace(".", ",")
    return {
        "portada": f"Ahora mismo hay {d['n']} buses de TransMilenio en la calle.",
        "vuelo": "Cada ícono es un bus real: su ruta, su placa y hacia dónde va.",
        "estacion": "Buscas tu estación y ves qué buses vienen, y en cuántos minutos llegan.",
        "bus": "Con un clic en el bus ves por dónde pasó y a qué hora llega a cada parada.",
        "veedor": "También compara lo que pone el horario con lo que de verdad hay en la calle.",
        "cancelados": f"Y hoy, TransMilenio marcó como cancelados el {pct} por ciento de los viajes del zonal.",
        "chat": "Todo esto se lo puedes preguntar a Claude, con un servidor eme ce pe de código abierto. "
        "Responde con los datos del momento.",
        "cierre": "TransMilenio eme ce pe. Datos abiertos de Bogotá.",
    }


def duracion(p: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(r.stdout.strip())


async def decir(texto: str, destino: Path, velocidad: int) -> None:
    await edge_tts.Communicate(texto, VOZ, rate=f"{velocidad:+d}%").save(str(destino))


def voces(d: dict, carpeta: Path) -> list[tuple[float, Path]]:
    """Una frase por escena; si no cabe, se habla un poco más rápido (hasta +25 %)."""
    textos = guion(d)
    inicio, out = 0.0, []
    for seg, nombre in d["plan"]:
        texto = textos[nombre]
        margen = 0.35 if nombre != "portada" else 0.6
        cabe = seg - margen - 0.25
        destino = carpeta / f"voz_{nombre}.mp3"
        for velocidad in (5, 12, 18, 25):
            asyncio.run(decir(texto, destino, velocidad))
            if duracion(destino) <= cabe or nombre == "chat":
                break
        print(f"{nombre:10s} {duracion(destino):4.1f} s de {seg} s  ({velocidad:+d} %)  {texto}")
        out.append((inicio + margen, destino))
        inicio += seg
    return out


# ------------------------------------------------------------------ música


def nota(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def envolvente(n: int, ataque: float, caida: float) -> np.ndarray:
    t = np.arange(n) / SR
    a = np.clip(t / ataque, 0, 1)
    c = np.clip((n / SR - t) / caida, 0, 1)
    return a * c


def musica(segundos: float, destino: Path) -> None:
    """Pad cálido en La menor (Am-F-C-G), un arpegio suave y un latido muy bajo. 84 BPM."""
    n = int(segundos * SR)
    izq, der = np.zeros(n), np.zeros(n)
    rng = np.random.default_rng(7)
    compas = 4 * 60 / 84  # un acorde por compás
    acordes = [[57, 60, 64], [53, 57, 60], [48, 55, 60], [55, 59, 62]]  # Am F C G
    t_total = np.arange(n) / SR
    k = 0
    t = 0.0
    while t < segundos:
        acorde = acordes[k % 4]
        i0, i1 = int(t * SR), min(n, int((t + compas + 1.2) * SR))
        tt = t_total[i0:i1] - t
        env = envolvente(i1 - i0, 0.9, 1.4)
        for j, m in enumerate(acorde + [acorde[0] - 12]):
            f = nota(m)
            # dos osciladores un poco desafinados: el pad "respira"
            s = np.sin(2 * np.pi * f * tt) + 0.6 * np.sin(2 * np.pi * f * 1.004 * tt + j)
            s += 0.15 * np.sin(2 * np.pi * 2 * f * tt)
            pan = 0.35 + 0.1 * j
            izq[i0:i1] += 0.05 * env * s * (1 - pan)
            der[i0:i1] += 0.05 * env * s * pan
        # arpegio: corcheas sobre el acorde, una octava arriba
        corchea = 60 / 84 / 2
        for p in range(8):
            ta = t + p * corchea
            a0, a1 = int(ta * SR), min(n, int((ta + 0.9) * SR))
            if a0 >= n:
                break
            m = acorde[[0, 1, 2, 1][p % 4]] + 12
            ttt = np.arange(a1 - a0) / SR
            golpe = np.exp(-ttt * 5.5) * np.clip(ttt / 0.004, 0, 1)
            s = np.sin(2 * np.pi * nota(m) * ttt) * golpe
            lado = 0.3 if p % 2 else 0.7
            izq[a0:a1] += 0.035 * s * (1 - lado)
            der[a0:a1] += 0.035 * s * lado
        # latido grave en el 1 y el 3
        for p in (0, 2):
            tb = t + p * 60 / 84
            b0, b1 = int(tb * SR), min(n, int((tb + 0.35) * SR))
            if b0 >= n:
                break
            ttt = np.arange(b1 - b0) / SR
            s = np.sin(2 * np.pi * (52 + 30 * np.exp(-ttt * 30)) * ttt) * np.exp(-ttt * 9)
            izq[b0:b1] += 0.09 * s
            der[b0:b1] += 0.09 * s
        t += compas
        k += 1
    ruido = rng.normal(0, 0.0015, n)  # un poco de aire, que no suene a sintetizador de prueba
    izq += ruido
    der += np.roll(ruido, 300)
    general = envolvente(n, 1.5, 3.0)
    est = np.stack([izq, der], axis=1) * general[:, None]
    est /= np.max(np.abs(est)) * 1.12
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((est * 32767).astype("<i2").tobytes())


def mezclar(clips: list[tuple[float, Path]], fondo: Path, total: float, destino: Path) -> None:
    entradas = ["-i", str(fondo)]
    filtros, etiquetas = [], []
    for i, (inicio, p) in enumerate(clips, start=1):
        entradas += ["-i", str(p)]
        ms = int(inicio * 1000)
        filtros.append(f"[{i}:a]aresample={SR},aformat=channel_layouts=stereo,adelay={ms}|{ms}[v{i}]")
        etiquetas.append(f"[v{i}]")
    filtros.append(f"{''.join(etiquetas)}amix=inputs={len(clips)}:normalize=0,volume=1.6[voz]")
    filtros.append("[voz]asplit=2[voz1][voz2]")
    filtros.append("[0:a]volume=0.13[mus]")
    filtros.append("[mus][voz1]sidechaincompress=threshold=0.02:ratio=4:attack=30:release=700[musb]")
    filtros.append(f"[musb][voz2]amix=inputs=2:normalize=0,atrim=0:{total},loudnorm=I=-16:TP=-1.5:LRA=11[out]")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            *entradas,
            "-filter_complex",
            ";".join(filtros),
            "-map",
            "[out]",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            str(SR),
            str(destino),
        ],
        check=True,
    )


def main() -> None:
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    salida = Path(sys.argv[2])
    tmp = salida.parent / "audio_tmp"
    tmp.mkdir(exist_ok=True)
    total = sum(s for s, _ in d["plan"])
    clips = voces(d, tmp)
    musica(total + 0.5, tmp / "musica.wav")
    mezclar(clips, tmp / "musica.wav", total, salida)
    print("Audio:", salida, f"{duracion(salida):.1f} s")


if __name__ == "__main__":
    main()
