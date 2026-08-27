import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as db_module  # noqa: E402


@pytest.fixture
def own_db_path(tmp_path):
    return str(tmp_path / "clips.db")


@pytest.fixture
def patched_db(monkeypatch, own_db_path):
    monkeypatch.setattr(db_module, "DB_PATH", own_db_path)
    return db_module


def _make_test_video(path: str, duration: float = 6.0, size: str = "640x360", color: str = "red") -> None:
    """Vídeo sintético corto (barra de color + tono) para no depender de
    descargas reales de YouTube en los tests."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s={size}:d={duration}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
            "-pix_fmt", "yuv420p",
            path,
        ],
        check=True,
    )


@pytest.fixture
def sample_video(tmp_path):
    path = str(tmp_path / "source.mp4")
    _make_test_video(path, duration=6.0, color="red")
    return path


@pytest.fixture
def sample_video_factory(tmp_path):
    counter = {"n": 0}

    def _factory(duration: float = 3.0, color: str = "blue", size: str = "640x360") -> str:
        counter["n"] += 1
        path = str(tmp_path / f"clip_{counter['n']}.mp4")
        _make_test_video(path, duration=duration, color=color, size=size)
        return path

    return _factory
