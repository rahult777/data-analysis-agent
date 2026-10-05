"""The backend refuses to start from any directory but the repository root.

It reads and writes paths relative to the working directory (backend/uploads, backend/outputs/charts,
backend/prompts), so a server started elsewhere would create a stray backend/backend/ tree. The check
runs first in backend/config.py, before .env is loaded or any directory is created.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Imports the app as uvicorn would, without ever reading a developer's .env.
IMPORT_APP = "import dotenv; dotenv.load_dotenv = lambda *a, **k: False; import backend.main"


def test_backend_refuses_to_start_outside_the_repository_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    shutil.copytree(
        REPO / "backend",
        root / "backend",
        ignore=shutil.ignore_patterns("outputs", "uploads", "__pycache__"),
    )
    python_path = os.pathsep.join(filter(None, [str(root), os.environ.get("PYTHONPATH")]))
    result = subprocess.run(
        [sys.executable, "-c", IMPORT_APP],
        cwd=root / "backend",
        env={**os.environ, "PYTHONPATH": python_path},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert "RuntimeError: Start the backend from the repository root" in result.stderr
    assert not (root / "backend" / "backend").exists()
