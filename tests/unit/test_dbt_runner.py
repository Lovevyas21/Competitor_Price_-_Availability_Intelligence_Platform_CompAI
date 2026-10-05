from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from app.transform.dbt_runner import DBT_DIR, DbtResult, run_dbt


def _completed(returncode: int = 0, stdout: str = "Done. PASS=10", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["dbt"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_runs_in_the_dbt_project_directory():
    with patch("app.transform.dbt_runner.subprocess.run", return_value=_completed()) as run:
        run_dbt("build")
    assert run.call_args.kwargs["cwd"] == DBT_DIR


def test_passes_extra_args_through():
    with patch("app.transform.dbt_runner.subprocess.run", return_value=_completed()) as run:
        run_dbt("build", "--select", "marts")
    argv = run.call_args.args[0]
    assert argv[1:] == ["build", "--select", "marts"]


def test_supplies_credentials_and_profiles_dir_via_env():
    with patch("app.transform.dbt_runner.subprocess.run", return_value=_completed()) as run:
        run_dbt("build")
    env = run.call_args.kwargs["env"]
    assert env["DBT_PROFILES_DIR"] == str(DBT_DIR)
    for key in ("POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        assert key in env


def test_never_uses_a_shell():
    with patch("app.transform.dbt_runner.subprocess.run", return_value=_completed()) as run:
        run_dbt("build")
    assert run.call_args.kwargs.get("shell", False) is False


def test_nonzero_exit_is_reported_as_failure():
    failed = _completed(returncode=1, stdout="Done. PASS=1 ERROR=1", stderr="boom")
    with patch("app.transform.dbt_runner.subprocess.run", return_value=failed):
        result = run_dbt("build")
    assert not result.ok
    assert result.summary()["returncode"] == 1


def test_summary_reports_dbts_final_verdict_line():
    stdout = "17:00:00 Running...\n17:00:01 Done. PASS=102 WARN=0 ERROR=0\n\n"
    result = DbtResult(command="build", returncode=0, stdout=stdout, stderr="")
    assert "PASS=102" in result.summary()["result"]


def test_summary_handles_empty_output():
    result = DbtResult(command="build", returncode=0, stdout="", stderr="")
    assert result.summary()["result"] == ""


@pytest.mark.parametrize("code,expected", [(0, True), (1, False), (2, False)])
def test_ok_tracks_return_code(code, expected):
    assert DbtResult("build", code, "", "").ok is expected
