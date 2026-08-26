"""Concatena varios clips en un solo vídeo. Adaptado de
services/podcast_tts/articles_to_mp3.py::combine_audio_files -- concat
demuxer con -c copy (sin recodificar). Funciona sin recodificar porque
clip_extractor.py normaliza SIEMPRE todos los clips a la misma
resolución/códec al extraerlos."""
import shutil
import subprocess
import tempfile


def build_montage(clip_paths: list[str], out_path: str) -> None:
    if not clip_paths:
        raise ValueError("no hay clips que concatenar")

    if len(clip_paths) == 1:
        shutil.copy(clip_paths[0], out_path)
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        list_file = f.name
        for path in clip_paths:
            safe_path = path.replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-f", "concat", "-safe", "0", "-i", list_file,
                "-c", "copy",
                out_path,
            ],
            check=True,
        )
    finally:
        import os
        os.unlink(list_file)
