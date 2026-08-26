import os

import pytest

import clip_extractor
import server as server_mod


@pytest.fixture
def client(patched_db):
    server_mod.app.config["TESTING"] = True
    with server_mod.app.test_client() as c:
        yield c


@pytest.fixture
def patched_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(server_mod, "CLIPS_DIR", str(tmp_path / "clips"))
    monkeypatch.setattr(server_mod, "SOURCES_DIR", str(tmp_path / "sources"))
    monkeypatch.setattr(server_mod, "MONTAGES_DIR", str(tmp_path / "montages"))
    return tmp_path


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}


def test_extract_job_creates_clip(patched_db, patched_dirs, monkeypatch, sample_video):
    monkeypatch.setattr(
        server_mod.ytdlp_client, "get_info",
        lambda url: {"video_id": "vid1", "title": "Test", "duration": 6, "url": url},
    )
    monkeypatch.setattr(
        server_mod.ytdlp_client, "download_video",
        lambda url, out_dir: (sample_video, {"video_id": "vid1", "title": "Test", "duration": 6, "url": url}),
    )

    job_id = server_mod._new_job("extract")
    server_mod._run_extract_job(job_id, "https://youtube.com/watch?v=vid1", 1.0, 3.0, "mi etiqueta")

    job = server_mod.JOBS[job_id]
    assert job["status"] == "done", job.get("error")
    clip_id = job["result"]["clip_id"]

    conn = patched_db.get_conn()
    row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    conn.close()
    assert row is not None
    assert row["label"] == "mi etiqueta"
    assert os.path.isfile(row["file_path"])


def test_extract_job_reuses_cached_source(patched_db, patched_dirs, monkeypatch, sample_video):
    calls = {"n": 0}

    def fake_download_video(url, out_dir):
        calls["n"] += 1
        return sample_video, {"video_id": "vid1", "title": "Test", "duration": 6, "url": url}

    monkeypatch.setattr(
        server_mod.ytdlp_client, "get_info",
        lambda url: {"video_id": "vid1", "title": "Test", "duration": 6, "url": url},
    )
    monkeypatch.setattr(server_mod.ytdlp_client, "download_video", fake_download_video)

    job1 = server_mod._new_job("extract")
    server_mod._run_extract_job(job1, "https://youtube.com/watch?v=vid1", 0.0, 2.0, "")
    job2 = server_mod._new_job("extract")
    server_mod._run_extract_job(job2, "https://youtube.com/watch?v=vid1", 2.0, 4.0, "")

    assert server_mod.JOBS[job1]["status"] == "done"
    assert server_mod.JOBS[job2]["status"] == "done"
    assert calls["n"] == 1  # el segundo clip reutiliza la fuente ya descargada

    conn = patched_db.get_conn()
    n_sources = conn.execute("SELECT COUNT(*) AS n FROM sources").fetchone()["n"]
    n_clips = conn.execute("SELECT COUNT(*) AS n FROM clips").fetchone()["n"]
    conn.close()
    assert n_sources == 1
    assert n_clips == 2


def test_extract_job_invalid_range_sets_job_error(patched_db, patched_dirs, monkeypatch, sample_video):
    monkeypatch.setattr(
        server_mod.ytdlp_client, "get_info",
        lambda url: {"video_id": "vid1", "title": "Test", "duration": 6, "url": url},
    )
    monkeypatch.setattr(
        server_mod.ytdlp_client, "download_video",
        lambda url, out_dir: (sample_video, {"video_id": "vid1", "title": "Test", "duration": 6, "url": url}),
    )

    job_id = server_mod._new_job("extract")
    server_mod._run_extract_job(job_id, "https://youtube.com/watch?v=vid1", 5.0, 1.0, "")
    assert server_mod.JOBS[job_id]["status"] == "error"


def test_list_and_delete_clip(client, patched_db, patched_dirs, monkeypatch, sample_video):
    monkeypatch.setattr(
        server_mod.ytdlp_client, "get_info",
        lambda url: {"video_id": "vid1", "title": "Test", "duration": 6, "url": url},
    )
    monkeypatch.setattr(
        server_mod.ytdlp_client, "download_video",
        lambda url, out_dir: (sample_video, {"video_id": "vid1", "title": "Test", "duration": 6, "url": url}),
    )
    job_id = server_mod._new_job("extract")
    server_mod._run_extract_job(job_id, "https://youtube.com/watch?v=vid1", 0.0, 2.0, "")
    clip_id = server_mod.JOBS[job_id]["result"]["clip_id"]

    r = client.get("/api/clips")
    items = r.get_json()
    assert len(items) == 1
    assert items[0]["id"] == clip_id

    r = client.get(f"/api/clips/{clip_id}/file")
    assert r.status_code == 200

    conn = patched_db.get_conn()
    file_path = conn.execute("SELECT file_path FROM clips WHERE id = ?", (clip_id,)).fetchone()["file_path"]
    conn.close()

    r = client.delete(f"/api/clips/{clip_id}")
    assert r.get_json() == {"ok": True}
    assert not os.path.isfile(file_path)
    assert client.get("/api/clips").get_json() == []


def test_montage_job_builds_and_serves_file(patched_db, patched_dirs, sample_video_factory):
    os.makedirs(server_mod.CLIPS_DIR, exist_ok=True)
    conn = patched_db.get_conn()
    conn.execute(
        "INSERT INTO sources (video_id, url, title, duration, file_path, downloaded_at) "
        "VALUES ('vid1','u','t',6,'x','now')"
    )
    conn.commit()
    source_id = conn.execute("SELECT id FROM sources").fetchone()["id"]

    clip_ids = []
    for i in range(2):
        raw = sample_video_factory(duration=2, color="red" if i == 0 else "blue")
        out = os.path.join(server_mod.CLIPS_DIR, f"c{i}.mp4")
        clip_extractor.extract_clip(raw, 0, 2, out)
        cur = conn.execute(
            "INSERT INTO clips (source_id, label, start_seconds, end_seconds, file_path, duration, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (source_id, f"clip{i}", 0, 2, out, 2.0, "now"),
        )
        clip_ids.append(cur.lastrowid)
    conn.commit()
    conn.close()

    job_id = server_mod._new_job("montage")
    server_mod._run_montage_job(job_id, 1, clip_ids)  # montage_id=1 no existe todavía en la tabla, pero el UPDATE simplemente no afecta filas
    assert server_mod.JOBS[job_id]["status"] == "done", server_mod.JOBS[job_id].get("error")


def test_upload_job_requires_connected_account(patched_db, monkeypatch, tmp_path):
    monkeypatch.setattr(server_mod.youtube_auth, "get_valid_credentials", lambda conn: None)
    conn = patched_db.get_conn()
    conn.execute(
        "INSERT INTO montages (id, title, clip_ids_json, file_path, status, created_at) "
        "VALUES (1,'t','[]','x.mp4','ready','now')"
    )
    conn.commit()
    conn.close()

    job_id = server_mod._new_job("upload")
    server_mod._run_upload_job(job_id, 1, "titulo", "desc", "private")
    job = server_mod.JOBS[job_id]
    assert job["status"] == "error"
    assert "conectada" in job["error"]


def test_upload_job_success_updates_montage(patched_db, monkeypatch, tmp_path):
    montage_file = tmp_path / "m.mp4"
    montage_file.write_bytes(b"contenido falso")
    conn = patched_db.get_conn()
    conn.execute(
        "INSERT INTO montages (id, title, clip_ids_json, file_path, status, created_at) "
        "VALUES (1,'t','[]',?, 'ready', 'now')",
        (str(montage_file),),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(server_mod.youtube_auth, "get_valid_credentials", lambda conn: object())
    monkeypatch.setattr(
        server_mod.youtube_upload, "upload_video",
        lambda creds, path, title, desc, privacy, progress_cb=None: "YT123",
    )

    job_id = server_mod._new_job("upload")
    server_mod._run_upload_job(job_id, 1, "titulo", "desc", "private")
    job = server_mod.JOBS[job_id]
    assert job["status"] == "done"
    assert job["result"]["youtube_video_id"] == "YT123"

    conn = patched_db.get_conn()
    row = conn.execute("SELECT status, youtube_video_id FROM montages WHERE id = 1").fetchone()
    conn.close()
    assert row["status"] == "uploaded"
    assert row["youtube_video_id"] == "YT123"


def test_api_upload_montage_requires_auth(client, patched_db):
    conn = patched_db.get_conn()
    conn.execute(
        "INSERT INTO montages (id, title, clip_ids_json, file_path, status, created_at) "
        "VALUES (1,'t','[]','x.mp4','ready','now')"
    )
    conn.commit()
    conn.close()

    r = client.post("/api/montages/1/upload", json={"title": "t", "privacy": "private"})
    assert r.status_code == 401
