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
