"""PDF-to-MusicXML conversion via Audiveris optical music recognition (OMR),
run out-of-process in batch mode.

Audiveris is a Java desktop application, not a library, so this module
shells out to its CLI launcher rather than calling into it directly. The
launcher's location is read from the `AUDIVERIS_PATH` environment variable,
which must point at the Audiveris executable/launcher itself (e.g.
`C:\\Users\\piper\\tools\\audiveris\\Audiveris.exe` on Windows, or the
`Audiveris` shell script on Linux/macOS installs) rather than at an
install directory. There is no fallback probing of conventional install
locations: if the variable is unset, or points at a path that doesn't
exist, conversion is treated as unavailable.

OMR is slow (tens of seconds to a few minutes for a real page) and can fail
in several distinct ways a caller needs to tell apart: not configured at
all, the process running but failing (bad input, timeout, or Audiveris
declining to export because some page within the PDF failed transcription
-- note that in batch mode Audiveris only exports a book once every sheet
in it has transcribed successfully, so a single bad/blank page fails the
whole document), and the process succeeding but leaving no exported file
where one was expected. `OMRNotConfigured` covers the first case;
`OMRConversionFailed` covers the rest.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# OMR on a real page is CPU-heavy; this default gives Audiveris room to
# finish a modest multi-page score without the request hanging forever if
# something has actually gone wrong.
DEFAULT_TIMEOUT_S = 180.0

_OUTPUT_EXTENSIONS = (".mxl", ".xml", ".musicxml")


class OMRNotConfigured(Exception):
    """Raised when `AUDIVERIS_PATH` is unset or does not point at an
    existing file. Callers should turn this into a clean 4xx response
    rather than letting conversion attempt to run at all.
    """


class OMRConversionFailed(Exception):
    """Raised when Audiveris runs but does not produce usable output:
    non-zero exit status, a timeout, or a successful-looking process that
    simply left no exported MusicXML file behind.
    """


def _audiveris_launcher() -> Path:
    launcher = os.environ.get("AUDIVERIS_PATH")
    if not launcher:
        raise OMRNotConfigured("AUDIVERIS_PATH is not set.")
    path = Path(launcher)
    if not path.is_file():
        raise OMRNotConfigured(f"AUDIVERIS_PATH does not point to a file: {launcher}")
    return path


def _find_output_file(output_dir: Path, stem: str) -> Path | None:
    """Locate the MusicXML Audiveris exported for `stem` inside
    `output_dir`. Audiveris names its export after the input file's stem;
    `.mxl` (compressed) is the normal `-export` output, `.xml`/`.musicxml`
    are accepted too in case of a differently configured install.
    """
    for ext in _OUTPUT_EXTENSIONS:
        candidate = output_dir / f"{stem}{ext}"
        if candidate.is_file():
            return candidate
    return None


def _cleanup_scratch(output_dir: Path, stem: str, keep: Path) -> None:
    """Remove Audiveris's own working files (the `.omr` project file and
    per-run log) from `output_dir`, leaving only the exported MusicXML
    (`keep`) behind. Best-effort: a failure to delete a scratch file is
    not worth failing the conversion over.
    """
    for path in output_dir.glob(f"{stem}*"):
        if path == keep:
            continue
        try:
            path.unlink()
        except OSError:
            pass


def convert_pdf_to_musicxml(
    pdf_path: str | Path,
    output_dir: str | Path,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> Path:
    """Run Audiveris in batch mode on `pdf_path`, exporting into
    `output_dir`, and return the path to the resulting MusicXML file.

    `output_dir` is created if it doesn't already exist. On success, any
    Audiveris scratch files (the `.omr` book file, per-run log) are removed
    from it, leaving only the exported MusicXML file. Callers own
    `output_dir`'s lifecycle beyond that (e.g. a temporary directory the
    caller cleans up once it has read the returned file).

    Raises `OMRNotConfigured` if Audiveris isn't set up, `OMRConversionFailed`
    if the process fails, times out, or produces no output.
    """
    launcher = _audiveris_launcher()

    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(launcher),
        "-batch",
        "-export",
        "-output",
        str(output_dir),
        "--",
        str(pdf_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise OMRConversionFailed(
            f"Audiveris did not finish within {timeout_s:.0f}s."
        ) from exc
    except OSError as exc:
        raise OMRConversionFailed(f"Could not run Audiveris: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        tail = " | ".join(detail[-5:]) if detail else "no output"
        raise OMRConversionFailed(
            f"Audiveris exited with status {result.returncode}: {tail}"
        )

    produced = _find_output_file(output_dir, pdf_path.stem)
    if produced is None:
        raise OMRConversionFailed(
            "Audiveris finished but produced no MusicXML output."
        )

    _cleanup_scratch(output_dir, pdf_path.stem, keep=produced)
    return produced
