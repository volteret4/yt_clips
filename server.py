#!/usr/bin/env python3
import os
import threading
import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, request, render_template_string, send_file

import clip_extractor
import montage as montage_mod
import youtube_auth
import youtube_upload
import ytdlp_client
from db import get_conn

app = Flask(__name__)

CLIPS_DIR = os.environ.get("CLIPS_DIR", "/app/clips")
SOURCES_DIR = os.environ.get("SOURCES_DIR", "/app/sources")
MONTAGES_DIR = os.environ.get("MONTAGES_DIR", "/app/montages")

JOBS = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_job(job_type: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"type": job_type, "status": "queued", "progress": None, "result": None, "error": None}
    return job_id


@app.route("/health")
def health():
    return jsonify({"ok": True})


# ── Extraer ──────────────────────────────────────────────────────────────

@app.route("/api/info")
def api_info():
    url = (request.args.get("url") or "").strip()
    if not url:
        return jsonify({"error": "falta la url"}), 400
    try:
        info = ytdlp_client.get_info(url)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(info)


def _run_extract_job(job_id: str, url: str, start: float, end: float, label: str):
    job = JOBS[job_id]
    conn = None
    try:
        os.makedirs(CLIPS_DIR, exist_ok=True)
        os.makedirs(SOURCES_DIR, exist_ok=True)
        job["status"] = "resolviendo"
        info = ytdlp_client.get_info(url)
        video_id = info["video_id"]
        if not video_id:
            raise ValueError("no se pudo resolver el vídeo")

        conn = get_conn()
        source_row = conn.execute("SELECT * FROM sources WHERE video_id = ?", (video_id,)).fetchone()

        if source_row and source_row["file_path"] and os.path.isfile(source_row["file_path"]):
            source_path = source_row["file_path"]
            source_id = source_row["id"]
        else:
            job["status"] = "descargando"
            source_path, dl_info = ytdlp_client.download_video(url, SOURCES_DIR)
            conn.execute(
                """
                INSERT INTO sources (video_id, url, title, duration, file_path, downloaded_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(video_id) DO UPDATE SET
                    file_path=excluded.file_path, downloaded_at=excluded.downloaded_at,
                    title=excluded.title, duration=excluded.duration
                """,
                (video_id, url, dl_info["title"], dl_info["duration"], source_path, _now()),
            )
            conn.commit()
            source_id = conn.execute("SELECT id FROM sources WHERE video_id = ?", (video_id,)).fetchone()["id"]

        job["status"] = "extrayendo"
        out_path = os.path.join(CLIPS_DIR, f"{uuid.uuid4().hex}.mp4")
        clip_extractor.extract_clip(source_path, start, end, out_path)
        duration = clip_extractor.probe_duration(out_path)

        cur = conn.execute(
            "INSERT INTO clips (source_id, label, start_seconds, end_seconds, file_path, duration, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (source_id, label, start, end, out_path, duration, _now()),
        )
        conn.commit()
        job["status"] = "done"
        job["result"] = {"clip_id": cur.lastrowid}
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
    finally:
        if conn:
            conn.close()


@app.route("/api/clips", methods=["POST"])
def api_create_clip():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    label = (data.get("label") or "").strip()
    try:
        start = float(data.get("start"))
        end = float(data.get("end"))
    except (TypeError, ValueError):
        return jsonify({"error": "start/end deben ser números (segundos)"}), 400
    if not url:
        return jsonify({"error": "falta la url"}), 400
    if end <= start:
        return jsonify({"error": "el fin debe ser mayor que el inicio"}), 400

    job_id = _new_job("extract")
    threading.Thread(target=_run_extract_job, args=(job_id, url, start, end, label), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/jobs/<job_id>")
def api_job_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job no encontrado"}), 404
    return jsonify(job)


@app.route("/api/clips")
def api_list_clips():
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT c.id, c.label, c.start_seconds, c.end_seconds, c.duration, c.created_at,
               s.title AS source_title, s.url AS source_url
        FROM clips c JOIN sources s ON s.id = c.source_id
        ORDER BY c.created_at DESC
        """
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/clips/<int:clip_id>/file")
def api_clip_file(clip_id):
    conn = get_conn()
    row = conn.execute("SELECT file_path FROM clips WHERE id = ?", (clip_id,)).fetchone()
    conn.close()
    if not row or not os.path.isfile(row["file_path"]):
        return jsonify({"error": "no encontrado"}), 404
    return send_file(row["file_path"], mimetype="video/mp4")


@app.route("/api/clips/<int:clip_id>", methods=["DELETE"])
def api_delete_clip(clip_id):
    conn = get_conn()
    row = conn.execute("SELECT file_path FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "no encontrado"}), 404
    conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
    conn.commit()
    conn.close()
    if row["file_path"] and os.path.isfile(row["file_path"]):
        os.remove(row["file_path"])
    return jsonify({"ok": True})


@app.route("/api/sources")
def api_list_sources():
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT s.id, s.title, s.url, s.duration, s.downloaded_at,
               (SELECT COUNT(*) FROM clips c WHERE c.source_id = s.id) AS clip_count
        FROM sources s ORDER BY s.downloaded_at DESC
        """
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/sources/<int:source_id>", methods=["DELETE"])
def api_delete_source(source_id):
    conn = get_conn()
    row = conn.execute("SELECT file_path FROM sources WHERE id = ?", (source_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "no encontrado"}), 404
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.commit()
    conn.close()
    if row["file_path"] and os.path.isfile(row["file_path"]):
        os.remove(row["file_path"])
    return jsonify({"ok": True})


# ── Montaje ──────────────────────────────────────────────────────────────

def _run_montage_job(job_id: str, montage_id: int, clip_ids: list):
    job = JOBS[job_id]
    conn = None
    try:
        os.makedirs(MONTAGES_DIR, exist_ok=True)
        job["status"] = "generando"
        conn = get_conn()
        clip_paths = []
        for cid in clip_ids:
            row = conn.execute("SELECT file_path FROM clips WHERE id = ?", (cid,)).fetchone()
            if not row:
                raise ValueError(f"clip {cid} no encontrado")
            clip_paths.append(row["file_path"])

        out_path = os.path.join(MONTAGES_DIR, f"{uuid.uuid4().hex}.mp4")
        montage_mod.build_montage(clip_paths, out_path)

        conn.execute("UPDATE montages SET file_path = ?, status = 'ready' WHERE id = ?", (out_path, montage_id))
        conn.commit()
        job["status"] = "done"
        job["result"] = {"montage_id": montage_id}
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        if conn:
            conn.execute("UPDATE montages SET status = 'error', error = ? WHERE id = ?", (str(e), montage_id))
            conn.commit()
    finally:
        if conn:
            conn.close()


@app.route("/api/montages", methods=["GET"])
def api_list_montages():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM montages ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/montages", methods=["POST"])
def api_create_montage():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip() or "Montaje sin título"
    clip_ids = data.get("clip_ids") or []
    if not clip_ids:
        return jsonify({"error": "selecciona al menos un clip"}), 400

    import json as _json
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO montages (title, clip_ids_json, status, created_at) VALUES (?,?,?,?)",
        (title, _json.dumps(clip_ids), "rendering", _now()),
    )
    conn.commit()
    montage_id = cur.lastrowid
    conn.close()

    job_id = _new_job("montage")
    threading.Thread(target=_run_montage_job, args=(job_id, montage_id, clip_ids), daemon=True).start()
    return jsonify({"montage_id": montage_id, "job_id": job_id})


@app.route("/api/montages/<int:montage_id>/file")
def api_montage_file(montage_id):
    conn = get_conn()
    row = conn.execute("SELECT file_path FROM montages WHERE id = ?", (montage_id,)).fetchone()
    conn.close()
    if not row or not row["file_path"] or not os.path.isfile(row["file_path"]):
        return jsonify({"error": "no encontrado"}), 404
    return send_file(row["file_path"], mimetype="video/mp4")


# ── Auth + subida a YouTube ─────────────────────────────────────────────

@app.route("/api/auth/youtube/status")
def api_auth_status():
    conn = get_conn()
    connected = youtube_auth.load_token(conn) is not None
    conn.close()
    return jsonify({"connected": connected})


@app.route("/api/auth/youtube/url")
def api_auth_url():
    if not youtube_auth.GOOGLE_CLIENT_ID or not youtube_auth.GOOGLE_CLIENT_SECRET:
        return jsonify({"error": "GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET no configurados"}), 400
    try:
        return jsonify({"auth_url": youtube_auth.get_auth_url()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/youtube/exchange", methods=["POST"])
def api_auth_exchange():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify({"error": "falta el código"}), 400
    conn = get_conn()
    try:
        token_data = youtube_auth.exchange_code(code)
        youtube_auth.save_token(conn, token_data)
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 400
    conn.close()
    return jsonify({"ok": True})


def _run_upload_job(job_id: str, montage_id: int, title: str, description: str, privacy: str):
    job = JOBS[job_id]
    conn = None
    try:
        job["status"] = "subiendo"
        conn = get_conn()
        creds = youtube_auth.get_valid_credentials(conn)
        if not creds:
            raise ValueError("no hay ninguna cuenta de YouTube conectada")
        row = conn.execute("SELECT file_path FROM montages WHERE id = ?", (montage_id,)).fetchone()
        if not row or not row["file_path"]:
            raise ValueError("el montaje no está listo")

        conn.execute("UPDATE montages SET status = 'uploading' WHERE id = ?", (montage_id,))
        conn.commit()

        def _progress(fraction):
            job["progress"] = fraction

        video_id = youtube_upload.upload_video(
            creds, row["file_path"], title, description, privacy, progress_cb=_progress,
        )
        conn.execute(
            "UPDATE montages SET status = 'uploaded', youtube_video_id = ? WHERE id = ?",
            (video_id, montage_id),
        )
        conn.commit()
        job["status"] = "done"
        job["result"] = {"youtube_video_id": video_id}
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        if conn:
            conn.execute("UPDATE montages SET status = 'error', error = ? WHERE id = ?", (str(e), montage_id))
            conn.commit()
    finally:
        if conn:
            conn.close()


@app.route("/api/montages/<int:montage_id>/upload", methods=["POST"])
def api_upload_montage(montage_id):
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    description = data.get("description") or ""
    privacy = data.get("privacy") or "private"
    if privacy not in ("private", "unlisted", "public"):
        return jsonify({"error": "privacy inválido"}), 400
    if not title:
        return jsonify({"error": "falta el título"}), 400

    conn = get_conn()
    connected = youtube_auth.load_token(conn) is not None
    conn.close()
    if not connected:
        return jsonify({"error": "conecta con YouTube primero"}), 401

    job_id = _new_job("upload")
    threading.Thread(
        target=_run_upload_job, args=(job_id, montage_id, title, description, privacy), daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


HTML_PAGE = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>YT Clips</title>
<style>
:root {
    --bg: #0a0e27; --surface: #16213e; --surface-2: #1f2d4a; --border: #2d3e5f;
    --text: #b0b8c9; --text-muted: #7a8694; --accent: #35bf88; --accent-2: #8e44ad;
    --warning: #f39c12; --danger: #e74c3c;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: var(--bg); color: var(--text); padding: 20px; }
h1 { color: #fff; margin-bottom: 16px; font-size: 20px; }
.tabs { display: flex; gap: 6px; margin-bottom: 16px; }
.tab-btn { background: var(--surface); color: var(--text-muted); border: 1px solid var(--border); padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; }
.tab-btn.active { background: var(--accent); color: var(--bg); border-color: var(--accent); }
.tab-panel { display: none; }
.tab-panel.active { display: block; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; margin-bottom: 16px; }
.form-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.form-row > div { flex: 1; min-width: 140px; }
.form-row label { font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px; }
.form-row input, .form-row select, .form-row textarea { width: 100%; padding: 7px 9px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; color: var(--text); font-size: 13px; }
.form-row input:focus, .form-row select:focus, .form-row textarea:focus { outline: none; border-color: var(--accent); }
button { background: var(--accent); color: var(--bg); border: none; padding: 8px 16px; border-radius: 6px; font-weight: bold; cursor: pointer; font-size: 13px; }
button.secondary { background: var(--surface-2); color: var(--text); }
button.danger { background: var(--danger); color: #fff; }
button:disabled { opacity: 0.5; cursor: default; }
.error { color: var(--danger); font-size: 12px; margin-top: 6px; }
.job-status { font-size: 12px; color: var(--text-muted); margin-top: 8px; }
.job-status.error { color: var(--danger); }
.job-status.done { color: var(--accent); }
.clip-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }
.clip-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.clip-card video { width: 100%; display: block; background: #000; }
.clip-card .body { padding: 10px 12px; }
.clip-title { font-size: 13px; color: #fff; font-weight: 600; margin-bottom: 2px; }
.clip-meta { font-size: 11px; color: var(--text-muted); }
.clip-actions { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; }
.clip-pick { display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: var(--surface-2); border-radius: 6px; margin-bottom: 6px; }
.clip-pick .clip-title { flex: 1; margin: 0; font-size: 12px; }
.selected-list { display: flex; flex-direction: column; gap: 6px; margin: 10px 0; }
.selected-item { display: flex; align-items: center; gap: 8px; background: var(--surface-2); padding: 6px 10px; border-radius: 6px; font-size: 12px; }
.selected-item .order-btns { display: flex; gap: 4px; margin-left: auto; }
.selected-item .order-btns button { padding: 2px 8px; font-size: 11px; }
.empty { color: var(--text-muted); font-size: 12px; padding: 10px 0; }
.montage-row { border-bottom: 1px solid var(--border); padding: 10px 0; }
.montage-row:last-child { border-bottom: none; }
.badge { display: inline-block; font-size: 11px; padding: 1px 8px; border-radius: 4px; background: var(--surface-2); color: var(--text-muted); }
.badge.ready { color: var(--accent); }
.badge.error { color: var(--danger); }
.badge.uploaded { color: var(--accent-2); }
a.yt-link { color: var(--accent); font-size: 12px; }
</style>
</head>
<body>
<h1>YT Clips — REPEAT-ONE</h1>
<div class="tabs">
    <button class="tab-btn active" data-tab="extraer" onclick="switchTab('extraer')">Extraer</button>
    <button class="tab-btn" data-tab="montaje" onclick="switchTab('montaje')">Montaje</button>
</div>

<div id="tab-extraer" class="tab-panel active">
    <div class="card">
        <div class="form-row">
            <div style="flex:3">
                <label>URL de YouTube</label>
                <input type="text" id="f_url" placeholder="https://www.youtube.com/watch?v=...">
            </div>
            <div>
                <label>Inicio (segundos)</label>
                <input type="number" id="f_start" step="0.1" min="0">
            </div>
            <div>
                <label>Fin (segundos)</label>
                <input type="number" id="f_end" step="0.1" min="0">
            </div>
            <div>
                <label>Etiqueta (opcional)</label>
                <input type="text" id="f_label" placeholder="mejor momento...">
            </div>
        </div>
        <button onclick="createClip()">Extraer clip</button>
        <div id="extract-error" class="error"></div>
        <div id="extract-job" class="job-status"></div>
    </div>
    <div id="clips-list" class="clip-grid"></div>
</div>

<div id="tab-montaje" class="tab-panel">
    <div class="card">
        <h3 style="color:#fff;font-size:14px;margin-bottom:10px">Elegir clips (en orden)</h3>
        <div id="clip-picker"></div>
        <div class="selected-list" id="selected-list"></div>
        <div class="form-row">
            <div><label>Título del montaje</label><input type="text" id="f_montage_title"></div>
        </div>
        <button onclick="createMontage()">Generar montaje</button>
        <div id="montage-error" class="error"></div>
        <div id="montage-job" class="job-status"></div>
    </div>
    <div class="card">
        <h3 style="color:#fff;font-size:14px;margin-bottom:10px">Montajes</h3>
        <div id="montages-list"></div>
    </div>
</div>

<script>
function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
}

function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + tab));
    if (tab === 'montaje') { loadClipsForPicker(); loadMontages(); }
}

// ── Extraer ─────────────────────────────────────────────────────────────

async function pollJob(jobId, statusEl, onDone) {
    const r = await fetch('/api/jobs/' + jobId);
    const job = await r.json();
    statusEl.className = 'job-status' + (job.status === 'error' ? ' error' : job.status === 'done' ? ' done' : '');
    if (job.status === 'error') {
        statusEl.textContent = 'Error: ' + job.error;
        return;
    }
    if (job.status === 'done') {
        statusEl.textContent = 'Hecho.';
        onDone(job);
        return;
    }
    const progress = (typeof job.progress === 'number') ? ` (${Math.round(job.progress * 100)}%)` : '';
    statusEl.textContent = job.status + '...' + progress;
    setTimeout(() => pollJob(jobId, statusEl, onDone), 1500);
}

async function createClip() {
    const url = document.getElementById('f_url').value.trim();
    const start = document.getElementById('f_start').value;
    const end = document.getElementById('f_end').value;
    const label = document.getElementById('f_label').value.trim();
    const errEl = document.getElementById('extract-error');
    const statusEl = document.getElementById('extract-job');
    errEl.textContent = '';
    if (!url || start === '' || end === '') { errEl.textContent = 'Faltan campos'; return; }

    const r = await fetch('/api/clips', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url, start: parseFloat(start), end: parseFloat(end), label}),
    });
    const data = await r.json();
    if (data.error) { errEl.textContent = data.error; return; }
    statusEl.textContent = 'iniciando...';
    pollJob(data.job_id, statusEl, () => { loadClips(); });
}

async function loadClips() {
    const r = await fetch('/api/clips');
    const clips = await r.json();
    const el = document.getElementById('clips-list');
    if (!clips.length) { el.innerHTML = '<div class="empty">Todavía no hay clips.</div>'; return; }
    el.innerHTML = clips.map(c => `
        <div class="clip-card">
            <video controls preload="metadata" src="/api/clips/${c.id}/file"></video>
            <div class="body">
                <div class="clip-title">${escapeHtml(c.label || c.source_title || ('Clip ' + c.id))}</div>
                <div class="clip-meta">${escapeHtml(c.source_title || '')} · ${c.start_seconds}s–${c.end_seconds}s</div>
                <div class="clip-actions">
                    <span class="clip-meta">${c.duration ? c.duration.toFixed(1) + 's' : ''}</span>
                    <button class="danger" onclick="deleteClip(${c.id})">Borrar</button>
                </div>
            </div>
        </div>
    `).join('');
}

async function deleteClip(id) {
    if (!confirm('¿Borrar este clip?')) return;
    await fetch('/api/clips/' + id, { method: 'DELETE' });
    loadClips();
}

// ── Montaje ─────────────────────────────────────────────────────────────

let allClips = [];
let selectedClipIds = [];

async function loadClipsForPicker() {
    const r = await fetch('/api/clips');
    allClips = await r.json();
    renderPicker();
}

function renderPicker() {
    const el = document.getElementById('clip-picker');
    if (!allClips.length) { el.innerHTML = '<div class="empty">No hay clips extraídos todavía.</div>'; return; }
    el.innerHTML = allClips.map(c => `
        <label class="clip-pick">
            <input type="checkbox" data-id="${c.id}" ${selectedClipIds.includes(c.id) ? 'checked' : ''}>
            <span class="clip-title">${escapeHtml(c.label || c.source_title || ('Clip ' + c.id))}</span>
            <span class="clip-meta">${c.duration ? c.duration.toFixed(1) + 's' : ''}</span>
        </label>
    `).join('');
    el.querySelectorAll('input[type=checkbox]').forEach(cb => {
        cb.addEventListener('change', () => {
            const id = parseInt(cb.dataset.id);
            if (cb.checked) { if (!selectedClipIds.includes(id)) selectedClipIds.push(id); }
            else { selectedClipIds = selectedClipIds.filter(x => x !== id); }
            renderSelected();
        });
    });
}

function renderSelected() {
    const el = document.getElementById('selected-list');
    if (!selectedClipIds.length) { el.innerHTML = '<div class="empty">Ningún clip seleccionado.</div>'; return; }
    el.innerHTML = selectedClipIds.map((id, i) => {
        const c = allClips.find(x => x.id === id);
        const label = c ? (c.label || c.source_title || ('Clip ' + id)) : ('Clip ' + id);
        return `
        <div class="selected-item">
            <span>${i + 1}.</span>
            <span>${escapeHtml(label)}</span>
            <div class="order-btns">
                <button class="secondary" onclick="moveSelected(${i}, -1)">↑</button>
                <button class="secondary" onclick="moveSelected(${i}, 1)">↓</button>
                <button class="danger" onclick="removeSelected(${id})">×</button>
            </div>
        </div>`;
    }).join('');
}

function moveSelected(index, delta) {
    const newIndex = index + delta;
    if (newIndex < 0 || newIndex >= selectedClipIds.length) return;
    [selectedClipIds[index], selectedClipIds[newIndex]] = [selectedClipIds[newIndex], selectedClipIds[index]];
    renderSelected();
}

function removeSelected(id) {
    selectedClipIds = selectedClipIds.filter(x => x !== id);
    renderPicker();
    renderSelected();
}

async function createMontage() {
    const title = document.getElementById('f_montage_title').value.trim();
    const errEl = document.getElementById('montage-error');
    const statusEl = document.getElementById('montage-job');
    errEl.textContent = '';
    if (!selectedClipIds.length) { errEl.textContent = 'Selecciona al menos un clip'; return; }

    const r = await fetch('/api/montages', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title, clip_ids: selectedClipIds}),
    });
    const data = await r.json();
    if (data.error) { errEl.textContent = data.error; return; }
    statusEl.textContent = 'iniciando...';
    pollJob(data.job_id, statusEl, () => { loadMontages(); });
}

async function loadMontages() {
    const r = await fetch('/api/montages');
    const montages = await r.json();
    const el = document.getElementById('montages-list');
    if (!montages.length) { el.innerHTML = '<div class="empty">Todavía no hay montajes.</div>'; return; }

    const authR = await fetch('/api/auth/youtube/status');
    const auth = await authR.json();

    el.innerHTML = montages.map(m => `
        <div class="montage-row" id="montage-${m.id}">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
                <strong style="color:#fff">${escapeHtml(m.title)}</strong>
                <span class="badge ${m.status}">${m.status}</span>
                ${m.youtube_video_id ? `<a class="yt-link" href="https://www.youtube.com/watch?v=${m.youtube_video_id}" target="_blank" rel="noopener">Ver en YouTube ↗</a>` : ''}
            </div>
            ${m.status === 'ready' ? `
                <video controls preload="metadata" style="width:100%;max-width:480px;margin-top:8px" src="/api/montages/${m.id}/file"></video>
                <div class="upload-form" style="margin-top:10px">
                    ${auth.connected ? renderUploadForm(m.id) : renderConnectPrompt()}
                </div>
            ` : ''}
            ${m.error ? `<div class="error">${escapeHtml(m.error)}</div>` : ''}
        </div>
    `).join('');
}

function renderConnectPrompt() {
    return `
        <button class="secondary" onclick="startYoutubeAuth()">Conectar con YouTube</button>
        <div id="auth-box" style="margin-top:8px"></div>
    `;
}

async function startYoutubeAuth() {
    const r = await fetch('/api/auth/youtube/url');
    const data = await r.json();
    const box = document.getElementById('auth-box');
    if (data.error) { box.innerHTML = `<div class="error">${escapeHtml(data.error)}</div>`; return; }
    box.innerHTML = `
        <div class="job-status">1. Abre <a class="yt-link" href="${escapeHtml(data.auth_url)}" target="_blank" rel="noopener">este enlace</a>, autoriza, y copia el "code" de la URL rota a la que te redirige.</div>
        <div class="form-row" style="margin-top:6px">
            <div style="flex:3"><input type="text" id="auth_code" placeholder="pega aquí el code"></div>
            <div><button onclick="finishYoutubeAuth()">Conectar</button></div>
        </div>
        <div id="auth-error" class="error"></div>
    `;
}

async function finishYoutubeAuth() {
    const code = document.getElementById('auth_code').value.trim();
    const r = await fetch('/api/auth/youtube/exchange', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code}),
    });
    const data = await r.json();
    if (data.error) { document.getElementById('auth-error').textContent = data.error; return; }
    loadMontages();
}

function renderUploadForm(montageId) {
    return `
        <div class="form-row">
            <div><label>Título en YouTube</label><input type="text" id="up_title_${montageId}"></div>
            <div><label>Privacidad</label>
                <select id="up_privacy_${montageId}">
                    <option value="private">Privado</option>
                    <option value="unlisted">No listado</option>
                    <option value="public">Público</option>
                </select>
            </div>
        </div>
        <div class="form-row"><div style="flex:1"><label>Descripción</label><textarea id="up_desc_${montageId}" rows="2"></textarea></div></div>
        <button onclick="uploadMontage(${montageId})">Subir a YouTube</button>
        <div id="upload-error-${montageId}" class="error"></div>
        <div id="upload-job-${montageId}" class="job-status"></div>
    `;
}

async function uploadMontage(montageId) {
    const title = document.getElementById(`up_title_${montageId}`).value.trim();
    const description = document.getElementById(`up_desc_${montageId}`).value;
    const privacy = document.getElementById(`up_privacy_${montageId}`).value;
    const errEl = document.getElementById(`upload-error-${montageId}`);
    const statusEl = document.getElementById(`upload-job-${montageId}`);
    errEl.textContent = '';
    if (!title) { errEl.textContent = 'Falta el título'; return; }

    const r = await fetch(`/api/montages/${montageId}/upload`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title, description, privacy}),
    });
    const data = await r.json();
    if (data.error) { errEl.textContent = data.error; return; }
    statusEl.textContent = 'iniciando...';
    pollJob(data.job_id, statusEl, () => { loadMontages(); });
}

loadClips();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
