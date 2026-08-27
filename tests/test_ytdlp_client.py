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


def test_download_video_tries_unrestricted_client_first(monkeypatch, tmp_path):
    captured = []

    class RecordingYDL(_FakeYDL):
        def __init__(self, opts):
            captured.append(opts)
            super().__init__(opts)

    monkeypatch.setattr(ytdlp_client.yt_dlp, "YoutubeDL", RecordingYDL)
    ytdlp_client.download_video("https://youtube.com/watch?v=abc123", str(tmp_path))
    assert len(captured) == 1
    assert "extractor_args" not in captured[0]  # sin restricción de player_client


def test_download_video_falls_back_when_unrestricted_client_fails(monkeypatch, tmp_path):
    calls = []

    class FlakyYDL(_FakeYDL):
        def __init__(self, opts):
            calls.append(opts)
            super().__init__(opts)

        def extract_info(self, url, download):
            if "extractor_args" not in self.opts:
                raise ytdlp_client.yt_dlp.utils.DownloadError("403")
            return super().extract_info(url, download)

    monkeypatch.setattr(ytdlp_client.yt_dlp, "YoutubeDL", FlakyYDL)
    path, info = ytdlp_client.download_video("https://youtube.com/watch?v=abc123", str(tmp_path))
    assert len(calls) == 2
    assert "extractor_args" not in calls[0]  # 1er intento: sin restricción, falla
    assert calls[1]["extractor_args"]["youtube"]["player_client"] == ["android", "mweb"]  # 2o: con restricción
    assert info["video_id"] == "abc123"
