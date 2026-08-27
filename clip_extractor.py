"""Recorta un tramo de un vídeo ya descargado, preservando su resolución
nativa (sin escalar/recomprimir a un tamaño fijo -- eso degradaba fuentes
de alta resolución). Se recodifica (no -c copy) para que el corte sea
exacto al segundo pedido -- con -c copy ffmpeg solo puede cortar en
keyframes, dando inicios/finales imprecisos. La normalización de
resolución (si hace falta, cuando se juntan clips de tamaños distintos)
se hace en montage.py, en el momento de generar el montaje -- así cada
clip guardado conserva toda la calidad de su fuente."""
import subprocess


def extract_clip(source_path: str, start_seconds: float, end_seconds: float, out_path: str) -> None:
    duration = end_seconds - start_seconds
    if duration <= 0:
        raise ValueError("el tiempo de fin debe ser mayor que el de inicio")
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-ss", str(start_seconds), "-i", source_path, "-t", str(duration),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "256k",
            "-movflags", "+faststart",
            out_path,
        ],
        check=True,
    )


def probe_duration(path: str) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def probe_resolution(path: str) -> tuple[int, int]:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            path,
        ],
        capture_output=True, text=True, check=True,
    )
    width, height = out.stdout.strip().split(",")
    return int(width), int(height)
