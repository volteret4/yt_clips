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


def test_build_montage_concatenates_clips_of_different_resolution(sample_video_factory, tmp_path):
    # Ya no se pre-normaliza en la extracción (ver clip_extractor.py) --
    # montage.py debe poder concatenar clips de resoluciones distintas
    # sin que el usuario tenga que hacer nada especial.
    c1 = sample_video_factory(duration=3, color="red", size="640x360")
    c2 = sample_video_factory(duration=2, color="blue", size="1280x720")

    out = str(tmp_path / "montage.mp4")
    montage.build_montage([c1, c2], out)

    assert os.path.isfile(out)
    dur = clip_extractor.probe_duration(out)
    assert abs(dur - 5.0) < 0.5
    # Se escala a la resolución más alta de los dos clips (1280x720), no
    # se downscala el de mayor calidad.
    assert clip_extractor.probe_resolution(out) == (1280, 720)


def test_build_montage_preserves_max_resolution_with_extracted_clips(sample_video_factory, tmp_path):
    # Flujo real: extraer (ya no reescala) -> montar.
    raw1 = sample_video_factory(duration=3, color="red", size="640x360")
    raw2 = sample_video_factory(duration=2, color="blue", size="960x540")
    c1, c2 = str(tmp_path / "c1.mp4"), str(tmp_path / "c2.mp4")
    clip_extractor.extract_clip(raw1, 0, 3, c1)
    clip_extractor.extract_clip(raw2, 0, 2, c2)
    assert clip_extractor.probe_resolution(c1) == (640, 360)
    assert clip_extractor.probe_resolution(c2) == (960, 540)

    out = str(tmp_path / "montage.mp4")
    montage.build_montage([c1, c2], out)
    assert clip_extractor.probe_resolution(out) == (960, 540)
