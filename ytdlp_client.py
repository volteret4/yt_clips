"""Descarga de YouTube vía yt-dlp -- mismo patrón que services/tracklist/app.py
(bloqueo anti-bot "Sign in to confirm you're not a bot" ya resuelto ahí).

Descarga siempre el vídeo COMPLETO, nunca --download-ranges de yt-dlp: un
intento anterior (en tracklist) de bajar solo un tramo obligaba a yt-dlp a
usar ffmpeg como downloader contra la URL firmada de googlevideo.com, cuyas
cabeceras no coinciden con las que espera el cliente (ANDROID_VR etc.),
dando 403. El tramo se recorta después, localmente, con ffmpeg (ver
clip_extractor.py) sobre el archivo ya descargado completo.
"""
import os

import yt_dlp

COOKIES_FILE = os.environ.get("YTCLIPS_COOKIES_FILE", "/app/cookies.txt")


def _ydl_base_opts(restrict_client: bool = True) -> dict:
    # remote_components: yt-dlp resuelve el "n challenge"/firma de YouTube
    # con un runtime JS (deno, instalado en la imagen).
    #
    # player_client=android/mweb (restrict_client=True): mismo ajuste que
    # services/tracklist/app.py -- evita 403 en la URL firmada real para
    # los clientes problemáticos (android_vr/web_safari/tv). PERO estos
    # dos clientes solo exponen hasta ~360p en muchos vídeos (comprobado
    # en vivo) -- ver download_video(), que intenta primero SIN esta
    # restricción para conseguir la mejor calidad, y solo cae aquí si
    # falla.
    opts = {"remote_components": ["ejs:github"]}
    if restrict_client:
        opts["extractor_args"] = {"youtube": {"player_client": ["android", "mweb"]}}
    if os.path.isfile(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0:
        opts["cookiefile"] = COOKIES_FILE
    return opts


def get_info(url: str) -> dict:
    """Metadata-only, sin descargar nada."""
    ydl_opts = {
        "quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
        **_ydl_base_opts(),
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        "video_id": info.get("id"),
        "title": info.get("title"),
        "duration": info.get("duration"),
        "url": url,
    }


def _do_download(url: str, out_dir: str, restrict_client: bool) -> tuple[str, dict]:
    outtmpl = os.path.join(out_dir, "%(id)s.%(ext)s")
    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": outtmpl,
        "quiet": True, "no_warnings": True, "noplaylist": True,
        **_ydl_base_opts(restrict_client=restrict_client),
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        # merge_output_format fuerza la extensión final a mp4 aunque la
        # descarga original fuera webm/mkv -- prepare_filename ya lo
        # refleja normalmente, pero por si acaso comprobamos el mp4 real.
        mp4_path = os.path.splitext(path)[0] + ".mp4"
        if os.path.isfile(mp4_path):
            path = mp4_path
    return path, info


def download_video(url: str, out_dir: str) -> tuple[str, dict]:
    """Descarga el vídeo completo a out_dir, en la mejor calidad
    disponible. Primero intenta SIN restringir el player_client (expone
    hasta 4K, pero en algunos vídeos/IPs de servidor la URL firmada real
    puede dar 403); si falla, reintenta con player_client=android/mweb
    (el ajuste ya probado en tracklist -- sin bloqueo, pero con techo
    real de ~360p en algunos vídeos). Devuelve (ruta_del_archivo, info)."""
    try:
        path, info = _do_download(url, out_dir, restrict_client=False)
    except yt_dlp.utils.DownloadError:
        path, info = _do_download(url, out_dir, restrict_client=True)
    return path, {
        "video_id": info.get("id"),
        "title": info.get("title"),
        "duration": info.get("duration"),
        "url": url,
    }
