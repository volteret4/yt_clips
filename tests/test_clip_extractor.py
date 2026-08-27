import os

import pytest

import clip_extractor


def test_extract_clip_duration(sample_video, tmp_path):
    out = str(tmp_path / "out.mp4")
    clip_extractor.extract_clip(sample_video, 1.0, 3.0, out)
    assert os.path.isfile(out)
    dur = clip_extractor.probe_duration(out)
    assert abs(dur - 2.0) < 0.3


def test_extract_clip_invalid_range_raises(sample_video, tmp_path):
    out = str(tmp_path / "out.mp4")
    with pytest.raises(ValueError):
        clip_extractor.extract_clip(sample_video, 3.0, 1.0, out)


def test_extract_clip_preserves_source_resolution(sample_video, tmp_path):
    # sample_video se genera a 640x360 -- extract_clip NO debe reescalar
    # (perdía calidad al forzar todo a un tamaño fijo). La normalización,
    # si hace falta, se hace en montage.py al generar el montaje, no aquí.
    out = str(tmp_path / "out.mp4")
    clip_extractor.extract_clip(sample_video, 0, 2, out)
    assert clip_extractor.probe_resolution(out) == (640, 360)


def test_probe_resolution(sample_video):
    assert clip_extractor.probe_resolution(sample_video) == (640, 360)
