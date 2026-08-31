"""Run dbt from the application.

dbt Core is a CLI first and foremost; driving it as a subprocess is the supported,
version-stable interface, and it keeps dbt's own dependency graph out of the worker
process. Credentials are passed through the environment so they are never written into
`profiles.yml`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)

DBT_DIR = Path(__file__).resolve().parents[2] / "dbt"


class DbtNotInstalled(RuntimeError):
    pass


@dataclass
class DbtResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def summary(self) -> dict:
        # dbt puts its one-line verdict on the last non-empty stdout line.
        tail = [line for line in self.stdout.splitlines() if line.strip()]
        return {
            "command": self.command,
            "ok": self.ok,
            "returncode": self.returncode,
            "result": tail[-1].strip() if tail else "",
        }


def _dbt_executable() -> str:
    exe = shutil.which("dbt")
    if exe:
        return exe
    # Windows venvs put it in Scripts/ which may not be on PATH inside a worker.
    for candidate in (
        Path(".venv/Scripts/dbt.exe"),
        Path(".venv/bin/dbt"),
    ):
        if candidate.exists():
            return str(candidate.resolve())
    raise DbtNotInstalled(
        "dbt executable not found; install with: uv pip install -e '.[dev]'"
    )


def _dbt_env() -> dict[str, str]:
    settings = get_settings()
    env = os.environ.copy()
    env["DBT_PROFILES_DIR"] = str(DBT_DIR)
    env.setdefault("POSTGRES_HOST", settings.postgres_host)
    env.setdefault("POSTGRES_PORT", str(settings.postgres_port))
    env.setdefault("POSTGRES_USER", settings.postgres_user)
    env.setdefault("POSTGRES_PASSWORD", settings.postgres_password)
    env.setdefault("POSTGRES_DB", settings.postgres_db)
    return env


def run_dbt(command: str = "build", *extra_args: str, timeout: int = 1800) -> DbtResult:
    """Run one dbt command in the project directory."""
    args = [_dbt_executable(), command, *extra_args]
    log.info("dbt.start", command=command, args=list(extra_args))

    proc = subprocess.run(  # noqa: S603 - fixed executable, no shell
        args,
        cwd=DBT_DIR,
        env=_dbt_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )

    result = DbtResult(
        command=command, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr
    )
    if result.ok:
        log.info("dbt.done", **result.summary())
    else:
        log.error("dbt.failed", **result.summary(), stderr=proc.stderr[-2000:])
    return result
