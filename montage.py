"""Concatena varios clips en un solo vídeo.

Usa el filtro concat de ffmpeg (no el concat demuxer con -c copy): los
clips ya no se normalizan a una resolución fija al extraerlos (ver
clip_extractor.py -- ahora conservan la resolución nativa de la fuente
para no perder calidad), así que pueden venir en tamaños distintos. El
filtro concat sí soporta re-escalar cada entrada sobre la marcha -- se
escalan todas a la resolución MÁS ALTA entre los clips elegidos (nunca se
downscala innecesariamente el clip de mayor calidad del lote)."""
import shutil
import subprocess

from clip_extractor import probe_resolution


def build_montage(clip_paths: list[str], out_path: str) -> None:
    if not clip_paths:
        raise ValueError("no hay clips que concatenar")

    if len(clip_paths) == 1:
        shutil.copy(clip_paths[0], out_path)
        return

    resolutions = [probe_resolution(p) for p in clip_paths]
    target_w = max(w for w, _ in resolutions)
    target_h = max(h for _, h in resolutions)
    # libx264 necesita dimensiones pares.
    target_w += target_w % 2
    target_h += target_h % 2

    inputs = []
    filter_parts = []
    for i, path in enumerate(clip_paths):
        inputs += ["-i", path]
        filter_parts.append(
            f"[{i}:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}]"
        )
        filter_parts.append(f"[{i}:a]aresample=48000[a{i}]")
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(clip_paths)))
    filter_complex = ";".join(filter_parts) + f";{concat_inputs}concat=n={len(clip_paths)}:v=1:a=1[outv][outa]"

    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "256k",
            "-movflags", "+faststart",
            out_path,
        ],
        check=True,
    )
