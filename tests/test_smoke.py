"""Check the CLI boundary, including argparse failures and honest offline status."""

import subprocess
import sys

import pytest

from fantasy_optimizer.cli import main


def test_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "status" in capsys.readouterr().out


@pytest.mark.parametrize("args", [[], ["sync"], ["status", "--unknown"]])
def test_invalid_arguments(args: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert "error:" in output.err
    assert output.out == ""


def test_module_status() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "fantasy_optimizer", "status"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0
    assert "forecasting and optimization are planned" in result.stdout
    assert "Yahoo access is unconfirmed" in result.stdout
    assert result.stderr == ""
