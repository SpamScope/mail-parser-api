import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mail_parser_api.app import create_app

FILES = Path(__file__).parent / "files"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def read_sample():
    def read(name: str) -> bytes:
        return (FILES / name).read_bytes()

    return read


@pytest.fixture
def fake_cli(monkeypatch):
    """Replace the CLI run: write ``stdout`` to its output file, return stderr.

    The fixture value installs the fake and returns the list of argument
    tuples it was called with.
    """

    def install(returncode: int, stdout: bytes = b"", stderr: bytes = b""):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            kwargs["stdout"].write(stdout)
            kwargs["stdout"].flush()
            return subprocess.CompletedProcess(
                args=args, returncode=returncode, stderr=stderr
            )

        monkeypatch.setattr(subprocess, "run", run)
        return calls

    return install
