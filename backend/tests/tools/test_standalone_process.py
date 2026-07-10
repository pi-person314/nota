"""Verify the MCP server package works as a standalone process configured
only by DATABASE_URL and SCORE_STORAGE_DIR environment variables — the same
lazy-initialization path `python -m nota.mcp_server` relies on. The
subprocess imports the tool functions with no explicit storage.configure()
call and mutates a score created by the test process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

SCRIPT = """
import json
from nota.mcp_server import tools

result = tools.add_dynamic({score_id!r}, measure=1, beat=1, dynamic="f")
print(json.dumps(result))
"""


def test_tools_run_in_fresh_process_with_only_env_vars(make_score, tmp_path, read_score_xml):
    sid = make_score("simple_4_4")

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'test.db'}"
    env["SCORE_STORAGE_DIR"] = str(tmp_path / "scores")
    env.pop("SECRET_KEY", None)  # the MCP server must not need Flask config

    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT.format(score_id=sid)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND_DIR),
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["success"] is True
    assert len(result["changed_element_ids"]) == 1
    assert f'id="{result["changed_element_ids"][0]}"' in read_score_xml(sid)


def test_dunder_main_module_starts_and_exits_cleanly(tmp_path):
    """`python -m nota.mcp_server` must start the stdio server without
    crashing on import/startup. Closing stdin immediately makes a
    well-behaved stdio MCP server shut down, so an exit code of 0 with no
    traceback is the pass condition.
    """
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'standalone.db'}"
    env["SCORE_STORAGE_DIR"] = str(tmp_path / "scores")
    env.pop("SECRET_KEY", None)

    completed = subprocess.run(
        [sys.executable, "-m", "nota.mcp_server"],
        input="",
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND_DIR),
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Traceback" not in completed.stderr
