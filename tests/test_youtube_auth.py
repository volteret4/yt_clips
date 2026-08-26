import datetime

import requests

import youtube_auth


def test_exchange_code(monkeypatch):
    monkeypatch.setattr(youtube_auth, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(youtube_auth, "GOOGLE_CLIENT_SECRET", "csecret")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "access_token": "at123",
                "refresh_token": "rt123",
                "scope": "https://www.googleapis.com/auth/youtube.upload",
            }

    def fake_post(url, data, timeout):
        assert url == "https://oauth2.googleapis.com/token"
        assert data["code"] == "abc123"
        assert data["client_id"] == "cid"
        return FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)

    token_data = youtube_auth.exchange_code("abc123")
    assert token_data["token"] == "at123"
    assert token_data["refresh_token"] == "rt123"
    assert token_data["scopes"] == ["https://www.googleapis.com/auth/youtube.upload"]


def test_exchange_code_raises_on_google_error(monkeypatch):
    monkeypatch.setattr(youtube_auth, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(youtube_auth, "GOOGLE_CLIENT_SECRET", "csecret")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"error": "invalid_grant", "error_description": "código caducado"}

    monkeypatch.setattr(requests, "post", lambda *a, **kw: FakeResp())

    try:
        youtube_auth.exchange_code("expired")
        assert False, "debería haber lanzado ValueError"
    except ValueError as e:
        assert "código caducado" in str(e)


def test_save_and_load_token_roundtrip(patched_db):
    conn = patched_db.get_conn()
    assert youtube_auth.load_token(conn) is None

    youtube_auth.save_token(conn, {
        "token": "t1", "refresh_token": "r1", "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid", "client_secret": "csecret",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"], "expiry": None,
    })
    loaded = youtube_auth.load_token(conn)
    assert loaded["token"] == "t1"
    assert loaded["refresh_token"] == "r1"
    assert loaded["scopes"] == ["https://www.googleapis.com/auth/youtube.upload"]

    # Guardar de nuevo actualiza la misma fila (id=1), no duplica.
    youtube_auth.save_token(conn, {**loaded, "token": "t2"})
    row = conn.execute("SELECT COUNT(*) AS n FROM youtube_auth").fetchone()
    assert row["n"] == 1
    assert youtube_auth.load_token(conn)["token"] == "t2"
    conn.close()


def test_get_valid_credentials_no_token(patched_db):
    conn = patched_db.get_conn()
    assert youtube_auth.get_valid_credentials(conn) is None
    conn.close()


def test_get_valid_credentials_refreshes_expired_token(patched_db, monkeypatch):
    conn = patched_db.get_conn()
    youtube_auth.save_token(conn, {
        "token": "old", "refresh_token": "rt", "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid", "client_secret": "csecret",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"], "expiry": None,
    })

    class FakeCreds:
        def __init__(self):
            self.expired = True
            self.refresh_token = "rt"
            self.token = "old"
            self.expiry = None

        def refresh(self, request):
            self.token = "new"
            self.expiry = datetime.datetime(2030, 1, 1)

    fake = FakeCreds()
    monkeypatch.setattr(youtube_auth, "_build_credentials", lambda token_data: fake)

    creds = youtube_auth.get_valid_credentials(conn)
    assert creds.token == "new"

    reloaded = youtube_auth.load_token(conn)
    assert reloaded["token"] == "new"
    assert reloaded["expiry"] == "2030-01-01T00:00:00"
    conn.close()
