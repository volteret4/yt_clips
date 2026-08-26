import os

import pytest

import clip_extractor
import montage


def test_build_montage_single_clip_copies(sample_video_factory, tmp_path):
    clip = sample_video_factory()
    out = str(tmp_path / "montage.mp4")
    montage.build_montage([clip], out)
    assert os.path.isfile(out)


def test_build_montage_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        montage.build_montage([], str(tmp_path / "x.mp4"))


def test_build_montage_concatenates_normalized_clips(sample_video_factory, tmp_path):
    # Flujo real: extraer (normaliza resolución/códec) -> concatenar con
    # -c copy. Si la normalización de clip_extractor no fuera consistente,
    # esto fallaría o produciría un vídeo corrupto.
    raw1 = sample_video_factory(duration=3, color="red")
    raw2 = sample_video_factory(duration=2, color="blue")
    c1, c2 = str(tmp_path / "c1.mp4"), str(tmp_path / "c2.mp4")
    clip_extractor.extract_clip(raw1, 0, 3, c1)
    clip_extractor.extract_clip(raw2, 0, 2, c2)

    out = str(tmp_path / "montage.mp4")
    montage.build_montage([c1, c2], out)

    assert os.path.isfile(out)
    dur = clip_extractor.probe_duration(out)
    assert abs(dur - 5.0) < 0.5
