"""Isolated launcher checks; mock the command, never run a real backtest."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


LAUNCHER = Path(__file__).resolve().parents[1] / "run-backtest-unseen.bat"
PROFILE_FILES = ("_base.yaml", "scan-selection.yml", "EURAUD.yaml", "GBPCAD.yaml",
                 "AUDCAD.yaml", "CADJPY.yaml")


def test_unseen_launcher_fixes_isolated_inputs_and_outputs():
    text = LAUNCHER.read_text(encoding="utf-8")
    command = next(line for line in text.splitlines() if line.startswith("uv run"))
    assert 'set "EVAL_CONFIG=data\\four_pair_evaluation_20261024\\configs"' in text
    assert command == ('uv run python -m quant.backtest --batch --config-dir "%EVAL_CONFIG%" '
                       '--results-dir "backtest_results\\four_pair_evaluation_20261024"')
    assert "%*" not in text
    assert text.index('if not exist "%EVAL_CONFIG%\\%%F"') < text.index(command)
    assert all(name in text for name in PROFILE_FILES)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows batch launcher")
@pytest.mark.parametrize("missing", [None, *PROFILE_FILES])
@pytest.mark.parametrize("result", [0, 7])
def test_unseen_launcher_guards_local_profile_and_preserves_exit_status(tmp_path, missing, result):
    root = tmp_path / "project with spaces"
    profile = root / "data/four_pair_evaluation_20261024/configs"
    profile.mkdir(parents=True)
    for name in PROFILE_FILES:
        if name != missing:
            (profile / name).write_text("synthetic fixture\n", encoding="utf-8")
    text = LAUNCHER.read_text(encoding="utf-8")
    command = next(line for line in text.splitlines() if line.startswith("uv run"))
    # Substitute the whole process invocation before executing this sandbox copy.
    text = text.replace(command, f"echo mocked>invoked.txt\ncmd /d /c exit {result}")
    launcher = root / LAUNCHER.name
    launcher.write_text(text, encoding="utf-8")
    completed = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c",
                                "call", str(launcher)], cwd=tmp_path, input="",
                               capture_output=True, text=True, timeout=15)
    assert completed.returncode == (1 if missing else result)
    assert (root / "invoked.txt").exists() == (missing is None)
    if missing:
        assert "No backtest started" in completed.stdout
