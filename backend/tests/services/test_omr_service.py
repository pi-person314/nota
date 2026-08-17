"""Unit tests for `nota.services.omr.convert_pdf_to_musicxml`.

The Audiveris subprocess is always mocked (`monkeypatch.setattr(omr,
"subprocess", ...)` / a fake `subprocess.run`); no test in this file shells
out to a real Audiveris install. The one real end-to-end conversion lives
in `tests/routes/test_upload_pdf.py::test_real_audiveris_conversion_end_to_end`,
gated on `AUDIVERIS_PATH` actually being set.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nota.services import omr


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def launcher(tmp_path):
    """A stand-in Audiveris launcher file (just needs to exist on disk)."""
    path = tmp_path / "Audiveris.exe"
    path.write_text("fake launcher")
    return path


@pytest.fixture
def configured(monkeypatch, launcher):
    monkeypatch.setenv("AUDIVERIS_PATH", str(launcher))
    return launcher


def _pdf(tmp_path, name="score.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4 fake pdf bytes")
    return path


def test_not_configured_when_env_var_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("AUDIVERIS_PATH", raising=False)

    with pytest.raises(omr.OMRNotConfigured):
        omr.convert_pdf_to_musicxml(_pdf(tmp_path), tmp_path / "out")


def test_not_configured_when_launcher_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIVERIS_PATH", str(tmp_path / "does_not_exist.exe"))

    with pytest.raises(omr.OMRNotConfigured):
        omr.convert_pdf_to_musicxml(_pdf(tmp_path), tmp_path / "out")


def test_success_returns_produced_mxl_and_cleans_up_scratch(monkeypatch, configured, tmp_path):
    pdf_path = _pdf(tmp_path)
    output_dir = tmp_path / "out"

    def fake_run(cmd, capture_output, text, timeout):
        # Mirror what a real Audiveris run leaves behind: the exported
        # .mxl plus scratch files (.omr project, per-run log).
        out = output_dir
        out.mkdir(parents=True, exist_ok=True)
        (out / "score.mxl").write_bytes(b"fake musicxml archive bytes")
        (out / "score.omr").write_bytes(b"fake book project file")
        (out / "score-20260101T000000.log").write_text("fake log")
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(omr.subprocess, "run", fake_run)

    produced = omr.convert_pdf_to_musicxml(pdf_path, output_dir)

    assert produced == output_dir / "score.mxl"
    assert produced.read_bytes() == b"fake musicxml archive bytes"
    remaining = sorted(p.name for p in output_dir.iterdir())
    assert remaining == ["score.mxl"]


def test_nonzero_exit_raises_conversion_failed(monkeypatch, configured, tmp_path):
    pdf_path = _pdf(tmp_path)

    def fake_run(cmd, capture_output, text, timeout):
        return _FakeCompletedProcess(returncode=1, stderr="ERROR something broke")

    monkeypatch.setattr(omr.subprocess, "run", fake_run)

    with pytest.raises(omr.OMRConversionFailed, match="status 1"):
        omr.convert_pdf_to_musicxml(pdf_path, tmp_path / "out")


def test_timeout_raises_conversion_failed(monkeypatch, configured, tmp_path):
    pdf_path = _pdf(tmp_path)

    def fake_run(cmd, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(omr.subprocess, "run", fake_run)

    with pytest.raises(omr.OMRConversionFailed, match="did not finish"):
        omr.convert_pdf_to_musicxml(pdf_path, tmp_path / "out", timeout_s=5)


def test_no_output_file_raises_conversion_failed(monkeypatch, configured, tmp_path):
    pdf_path = _pdf(tmp_path)
    output_dir = tmp_path / "out"

    def fake_run(cmd, capture_output, text, timeout):
        # Process "succeeds" but leaves nothing exported -- e.g. Audiveris
        # transcribed but a downstream export step silently produced
        # nothing usable.
        output_dir.mkdir(parents=True, exist_ok=True)
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(omr.subprocess, "run", fake_run)

    with pytest.raises(omr.OMRConversionFailed, match="no MusicXML output"):
        omr.convert_pdf_to_musicxml(pdf_path, output_dir)


def test_launcher_not_found_oserror_raises_conversion_failed(monkeypatch, configured, tmp_path):
    pdf_path = _pdf(tmp_path)

    def fake_run(cmd, capture_output, text, timeout):
        raise OSError("launcher vanished")

    monkeypatch.setattr(omr.subprocess, "run", fake_run)

    with pytest.raises(omr.OMRConversionFailed, match="Could not run Audiveris"):
        omr.convert_pdf_to_musicxml(pdf_path, tmp_path / "out")


def _recording_run(output_dir, calls):
    """A fake `subprocess.run` that records the `timeout` it was called
    with and leaves a real exported file behind, so callers can complete
    successfully and inspect what timeout ended up being used.
    """

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(timeout)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "score.mxl").write_bytes(b"fake musicxml archive bytes")
        return _FakeCompletedProcess(returncode=0)

    return fake_run


def test_env_var_timeout_is_used_when_no_explicit_timeout(
    monkeypatch, configured, tmp_path
):
    monkeypatch.setenv("OMR_TIMEOUT_S", "45")
    pdf_path = _pdf(tmp_path)
    output_dir = tmp_path / "out"
    calls: list[float] = []
    monkeypatch.setattr(omr.subprocess, "run", _recording_run(output_dir, calls))

    omr.convert_pdf_to_musicxml(pdf_path, output_dir)

    assert calls == [45.0]


def test_invalid_env_var_timeout_falls_back_to_default(monkeypatch, configured, tmp_path):
    pdf_path = _pdf(tmp_path)
    output_dir = tmp_path / "out"
    calls: list[float] = []
    monkeypatch.setattr(omr.subprocess, "run", _recording_run(output_dir, calls))

    for bad_value in ("abc", "-5"):
        monkeypatch.setenv("OMR_TIMEOUT_S", bad_value)
        calls.clear()

        omr.convert_pdf_to_musicxml(pdf_path, output_dir)

        assert calls == [omr.DEFAULT_TIMEOUT_S]


def test_unset_env_var_timeout_falls_back_to_default(monkeypatch, configured, tmp_path):
    monkeypatch.delenv("OMR_TIMEOUT_S", raising=False)
    pdf_path = _pdf(tmp_path)
    output_dir = tmp_path / "out"
    calls: list[float] = []
    monkeypatch.setattr(omr.subprocess, "run", _recording_run(output_dir, calls))

    omr.convert_pdf_to_musicxml(pdf_path, output_dir)

    assert calls == [omr.DEFAULT_TIMEOUT_S]


def test_explicit_timeout_overrides_env_var(monkeypatch, configured, tmp_path):
    monkeypatch.setenv("OMR_TIMEOUT_S", "45")
    pdf_path = _pdf(tmp_path)
    output_dir = tmp_path / "out"
    calls: list[float] = []
    monkeypatch.setattr(omr.subprocess, "run", _recording_run(output_dir, calls))

    omr.convert_pdf_to_musicxml(pdf_path, output_dir, timeout_s=12.0)

    assert calls == [12.0]
