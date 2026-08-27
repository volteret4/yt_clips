# yt_clips

## Arquitectura

- `ytdlp_client.py` — descarga de YouTube, mismo `_ydl_base_opts()` que
  `services/tracklist/app.py` (bloqueo anti-bot ya resuelto: deno para el
  n-challenge, `player_client` restringido a android/mweb, `cookiefile`
  opcional). `get_info()` metadata-only; `download_video()` descarga
  **siempre el vídeo completo** (nunca `--download-ranges` de yt-dlp —
  mismo motivo que tracklist: URLs firmadas de googlevideo.com con
  cabeceras que no coinciden si se pide un tramo directamente) y **sin
  techo de resolución** (`bestvideo+bestaudio/best` — si YouTube ofrece
  4K, se baja en 4K).
- `clip_extractor.py` — recorta con ffmpeg preservando la resolución
  nativa de la fuente (no reescala) — recodifica (CRF 18, preset medium)
  solo para que el corte sea exacto al segundo pedido, no por keyframe.
  La normalización de resolución (si hace falta) se hace en `montage.py`,
  no aquí — así un clip guardado nunca pierde calidad respecto a su
  fuente aunque no se llegue a usar en ningún montaje.
- `montage.py` — filtro concat de ffmpeg (no el concat demuxer con
  `-c copy`, que exigiría que todos los clips compartan resolución
  exacta): escala cada clip a la resolución MÁS ALTA entre los
  seleccionados (nunca downscala el de mayor calidad del lote),
  `setsar=1`+`fps=30` para que el filtro acepte fuentes heterogéneas,
  recodifica igual que `clip_extractor.py` (CRF 18/medium). Concepto
  adaptado de `services/podcast_tts/articles_to_mp3.py::combine_audio_files`
  (que sí usa el concat demuxer, porque ahí todos los audios ya comparten
  formato).
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

## Por qué la resolución NO se fuerza en la extracción

Versión anterior: `clip_extractor.py` reescalaba/rellenaba SIEMPRE a
1920x1080 para poder usar el concat demuxer (`-c copy`) en `montage.py`.
Problema real detectado por el usuario: degradaba fuentes de mayor
resolución (4K/1440p) a 1080p aunque nunca se fueran a montar con otros
clips, y además el `download_video()` de entonces ya capaba a
`height<=1080` -- doble pérdida de calidad innecesaria. Ahora
`download_video()` pide la mejor calidad sin techo, `clip_extractor.py`
no reescala nada, y `montage.py` usa el filtro concat (soporta
resoluciones de entrada distintas, escalando sobre la marcha a la más
alta del lote) en vez del demuxer.

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
