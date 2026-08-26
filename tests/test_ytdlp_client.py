import ytdlp_client


class _FakeYDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download):
        return {"id": "abc123", "title": "Test Video", "duration": 120}

    def prepare_filename(self, info):
        return f"/tmp/{info['id']}.mp4"


def test_get_info(monkeypatch):
    monkeypatch.setattr(ytdlp_client.yt_dlp, "YoutubeDL", _FakeYDL)
    info = ytdlp_client.get_info("https://youtube.com/watch?v=abc123")
    assert info == {
        "video_id": "abc123", "title": "Test Video", "duration": 120,
        "url": "https://youtube.com/watch?v=abc123",
    }


def test_get_info_uses_base_opts(monkeypatch):
    captured = {}

    class RecordingYDL(_FakeYDL):
        def __init__(self, opts):
            captured["opts"] = opts
            super().__init__(opts)

    monkeypatch.setattr(ytdlp_client.yt_dlp, "YoutubeDL", RecordingYDL)
    ytdlp_client.get_info("https://youtube.com/watch?v=abc123")
    assert captured["opts"]["skip_download"] is True
    assert captured["opts"]["extractor_args"]["youtube"]["player_client"] == ["android", "mweb"]


def test_download_video(monkeypatch, tmp_path):
    monkeypatch.setattr(ytdlp_client.yt_dlp, "YoutubeDL", _FakeYDL)
    path, info = ytdlp_client.download_video("https://youtube.com/watch?v=abc123", str(tmp_path))
    assert info["video_id"] == "abc123"
    assert path.endswith(".mp4")
