"""Recorta un tramo de un vídeo ya descargado y lo normaliza siempre a la
misma resolución/códec (1920x1080, h264/aac) -- así la concatenación
posterior en montage.py puede usar el concat demuxer con -c copy (sin
recodificar) sin importar de qué fuente/resolución venía cada clip
original."""
import subprocess


def extract_clip(source_path: str, start_seconds: float, end_seconds: float, out_path: str) -> None:
    duration = end_seconds - start_seconds
    if duration <= 0:
        raise ValueError("el tiempo de fin debe ser mayor que el de inicio")
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-ss", str(start_seconds), "-i", source_path, "-t", str(duration),
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
                   "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
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
