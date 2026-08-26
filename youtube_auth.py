"""OAuth2 de Google para subir vídeos (scope youtube.upload). Adaptado de
services/bot_conciertos/apis/google_calendar.py, con dos diferencias:

- Aquí el servicio es de un solo usuario -- el token vive en una fila
  única (id=1) de la tabla youtube_auth, no por usuario.
- El intercambio de código usa el mismo POST directo a
  oauth2.googleapis.com/token (en vez del flujo normal de
  google_auth_oauthlib) porque redirect_uri="http://localhost" nunca
  redirige de verdad -- el usuario copia el "code" de la URL rota de su
  navegador y lo pega en la web, así que no hay negociación de "state"
  que verificar del lado del servidor.
"""
import os
from datetime import datetime

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
REDIRECT_URI = "http://localhost"

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")


def _client_config() -> dict:
    return {
        "installed": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uris": [REDIRECT_URI],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def get_auth_url() -> str:
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent",
    )
    return auth_url


def exchange_code(code: str) -> dict:
    import requests
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code.strip(),
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    resp.raise_for_status()
    token_json = resp.json()
    if "error" in token_json:
        raise ValueError(f"Error de Google OAuth: {token_json.get('error_description', token_json['error'])}")
    return {
        "token": token_json.get("access_token"),
        "refresh_token": token_json.get("refresh_token"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "scopes": token_json.get("scope", "").split() or list(SCOPES),
        "expiry": None,
    }


def save_token(conn, token_data: dict) -> None:
    conn.execute(
        """
        INSERT INTO youtube_auth (id, token, refresh_token, token_uri, client_id, client_secret, scopes, expiry)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            token=excluded.token, refresh_token=excluded.refresh_token, token_uri=excluded.token_uri,
            client_id=excluded.client_id, client_secret=excluded.client_secret,
            scopes=excluded.scopes, expiry=excluded.expiry
        """,
        (
            token_data.get("token"), token_data.get("refresh_token"), token_data.get("token_uri"),
            token_data.get("client_id"), token_data.get("client_secret"),
            " ".join(token_data.get("scopes") or []), token_data.get("expiry"),
        ),
    )
    conn.commit()


def load_token(conn) -> dict | None:
    row = conn.execute("SELECT * FROM youtube_auth WHERE id = 1").fetchone()
    if not row or not row["refresh_token"]:
        return None
    return {
        "token": row["token"], "refresh_token": row["refresh_token"], "token_uri": row["token_uri"],
        "client_id": row["client_id"], "client_secret": row["client_secret"],
        "scopes": (row["scopes"] or "").split(), "expiry": row["expiry"],
    }


def _build_credentials(token_data: dict):
    from google.oauth2.credentials import Credentials
    expiry = None
    if token_data.get("expiry"):
        try:
            expiry = datetime.fromisoformat(token_data["expiry"])
        except (ValueError, TypeError):
            pass
    return Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id", GOOGLE_CLIENT_ID),
        client_secret=token_data.get("client_secret", GOOGLE_CLIENT_SECRET),
        scopes=token_data.get("scopes") or list(SCOPES),
        expiry=expiry,
    )


def get_valid_credentials(conn):
    """Carga el token guardado, lo refresca si ha expirado y lo regraba.
    None si no hay token (el usuario no ha conectado con YouTube todavía)."""
    token_data = load_token(conn)
    if not token_data:
        return None
    from google.auth.transport.requests import Request
    creds = _build_credentials(token_data)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_token(conn, {
            **token_data,
            "token": creds.token,
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
        })
    return creds
