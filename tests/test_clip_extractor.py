import os
import subprocess

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


def test_extract_clip_normalizes_resolution(sample_video, tmp_path):
    # sample_video ya se genera a 640x360 -- confirma que extract_clip
    # siempre reescala/rellena a 1920x1080 sea cual sea la fuente (para
    # que la concatenación posterior con -c copy funcione siempre).
    out = str(tmp_path / "out.mp4")
    clip_extractor.extract_clip(sample_video, 0, 2, out)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
        capture_output=True, text=True, check=True,
    )
    width, height = result.stdout.strip().split(",")
    assert width == "1920"
    assert height == "1080"
