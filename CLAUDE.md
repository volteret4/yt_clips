# yt_clips

## Arquitectura

- `ytdlp_client.py` — descarga de YouTube, mismo `_ydl_base_opts()` que
  `services/tracklist/app.py` (bloqueo anti-bot ya resuelto: deno para el
  n-challenge, `player_client` restringido a android/mweb, `cookiefile`
  opcional). `get_info()` metadata-only; `download_video()` descarga
  **siempre el vídeo completo** (nunca `--download-ranges` de yt-dlp —
  mismo motivo que tracklist: URLs firmadas de googlevideo.com con
  cabeceras que no coinciden si se pide un tramo directamente).
- `clip_extractor.py` — recorta con ffmpeg y normaliza SIEMPRE a
  1920x1080 h264/aac, para que `montage.py` pueda concatenar después con
  `-c copy` (sin recodificar) sin que importe la resolución/códec del
  vídeo original.
- `montage.py` — concat demuxer, adaptado de
  `services/podcast_tts/articles_to_mp3.py::combine_audio_files`.
- `youtube_auth.py` — OAuth2 (scope `youtube.upload` únicamente),
  adaptado de `services/bot_conciertos/apis/google_calendar.py`. Cliente
  tipo "aplicación de escritorio" (`redirect_uri=http://localhost`): el
  usuario copia el `code` de la URL rota tras autorizar, en vez de un
  redirect real -- evita depender de que este servicio tenga un dominio
  HTTPS público. Token en una fila única (`youtube_auth.id = 1`, un solo
  usuario).
- `youtube_upload.py` — subida resumable (`MediaFileUpload(...,
  resumable=True)` + bucle `next_chunk()`), progreso real reportado al
  job en vez de todo-o-nada (importa para vídeos de varios cientos de MB).
- `db.py` — `clips.db` propia: `sources` (vídeos completos descargados,
  cacheados por `video_id` -- varios clips del mismo vídeo no lo
  redescargan), `clips`, `montages`, `youtube_auth`.
- `server.py` — Flask, patrón `JOBS = {}` en memoria + `threading.Thread`
  + `GET /api/jobs/<id>` de polling, copiado de `services/tracklist/app.py`
  (extraer y subir son ambos procesos lentos que no deben bloquear la
  petición HTTP).

## Por qué se descarga el vídeo completo, no solo el tramo

Ver el comentario en `ytdlp_client.py` y la nota equivalente en
`services/tracklist/README.md`/`CLAUDE.md`: yt-dlp con
`--download-ranges` usa ffmpeg como downloader contra la URL firmada de
googlevideo.com, y sus cabeceras no coinciden con las que espera el
cliente (ANDROID_VR etc.), dando 403. Descargar siempre el archivo
completo con el downloader nativo de yt-dlp evita ese problema; el tramo
se recorta después, localmente.

## Por qué el vídeo se normaliza siempre en la extracción

`montage.py` usa el concat **demuxer** de ffmpeg con `-c copy` (rápido,
sin pérdida) en vez del filtro concat (que sí soporta entradas distintas
pero recodifica siempre). Con `-c copy` todos los clips de entrada deben
compartir exactamente resolución y códec -- como aquí TODOS los clips
pasan por `clip_extractor.py`, forzar siempre 1920x1080/h264/aac ahí
garantiza que la concatenación posterior nunca falle, sin importar de
qué vídeo/resolución viniera cada clip.

## OAuth de YouTube: cómo crear el cliente en Google Cloud Console

No existía ningún cliente OAuth para esto (la `YOUTUBE_API_KEY` del resto
del repo es de solo lectura). Pasos manuales (una vez):

1. [Google Cloud Console](https://console.cloud.google.com/) → crear
   proyecto (o reusar uno existente) → **APIs & Services → Library** →
   habilitar **YouTube Data API v3**.
2. **APIs & Services → OAuth consent screen** → tipo "External" (o
   "Internal" si hay Workspace) → añadir tu cuenta de Google como
   "usuario de prueba" (la app se queda en modo Testing, no hace falta
   verificarla para uso personal).
3. **APIs & Services → Credentials → Create Credentials → OAuth client
   ID** → tipo **"Desktop app"** (no "Web application" -- así el
   `redirect_uri=http://localhost` no necesita estar registrado ni
   depende de que este servicio tenga HTTPS público).
4. Copiar el `Client ID`/`Client secret` a `GOOGLE_CLIENT_ID`/
   `GOOGLE_CLIENT_SECRET` en el `.env` de este servicio.
5. En la web (pestaña Montaje, una vez haya un montaje listo): "Conectar
   con YouTube" → autorizar en el navegador → copiar el `code` de la URL
   rota a la que redirige → pegarlo en la web.
