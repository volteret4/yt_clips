# yt_clips

Extrae clips de vídeos de YouTube (mejores momentos), los guarda en disco
y permite verlos en la web. Segunda pestaña para juntar varios clips en
un montaje y subirlo como vídeo nuevo a YouTube. Parte de
[repeat-one](https://github.com/volteret4/repeat-one).

## Cómo funciona

- **Extraer**: pega una URL de YouTube + tiempo de inicio/fin (segundos).
  El vídeo completo se descarga una vez por `video_id` (yt-dlp, se
  reutiliza si ya se había descargado para un clip anterior del mismo
  vídeo) y el tramo se recorta localmente con ffmpeg, normalizado siempre
  a 1920x1080 h264/aac.
- **Montaje**: elige varios clips guardados, en el orden deseado, y
  genera un vídeo concatenado. Como todos los clips ya están
  normalizados, la concatenación es directa (sin recodificar).
- **Subir a YouTube**: sube el montaje generado (privado por defecto,
  elegible no listado/público). Requiere conectar una cuenta de YouTube
  la primera vez (OAuth2, ver `CLAUDE.md` para cómo crear el cliente en
  Google Cloud Console — no usa la `YOUTUBE_API_KEY` de solo lectura del
  resto del repo).

## Variables de entorno

```bash
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
DB_PATH=/app/clips.db
CLIPS_DIR=/app/clips
SOURCES_DIR=/app/sources
MONTAGES_DIR=/app/montages
YTCLIPS_COOKIES_FILE=/app/cookies.txt   # opcional, ver más abajo
PORT=5000
```

## Cookies (bloqueo anti-bot de YouTube)

Si yt-dlp falla con `Sign in to confirm you're not a bot` (frecuente
desde IPs de servidor), rellena `cookies.txt` en este directorio con
cookies de una sesión de YouTube logueada, formato Netscape — mismo
mecanismo que `services/tracklist` (ver su README para el paso a paso de
cómo exportarlas). Vacío por defecto, funciona igual sin cookies hasta
que YouTube empiece a pedir verificación.

## Uso

```bash
pip install -r requirements.txt
python3 server.py          # web en 0.0.0.0:5000
```

## Tests

```bash
pip install -r requirements.txt pytest
pytest tests/ -v
```

Los tests de `clip_extractor`/`montage` corren ffmpeg de verdad contra
vídeos sintéticos generados con `ffmpeg -f lavfi` (sin depender de
descargas reales de YouTube); `ytdlp_client`/`youtube_auth`/las rutas de
`server.py` van mockeados.
