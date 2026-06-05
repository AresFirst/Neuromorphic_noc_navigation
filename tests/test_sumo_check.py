"""SUMO environment check tests."""

from __future__ import annotations

from pathlib import Path

from nmn.sumo import check_sumo_available


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_check_sumo_available_accepts_explicit_eclipse_sumo_binary(tmp_path, monkeypatch):
    fake_sumo = _write_executable(
        tmp_path / "sumo",
        "#!/bin/sh\nprintf 'Eclipse SUMO sumo Version 1.20.0\\n'\n",
    )
    monkeypatch.setenv("SUMO_BINARY", str(fake_sumo))
    monkeypatch.delenv("SUMO_HOME", raising=False)
    monkeypatch.setenv("PATH", "")

    status = check_sumo_available()

    assert status["available"] is True
    assert status["sumo_bin"] == str(fake_sumo)
    assert status["version"] == "Eclipse SUMO sumo Version 1.20.0"


def test_check_sumo_available_rejects_shadowing_non_eclipse_sumo(tmp_path, monkeypatch):
    _write_executable(
        tmp_path / "sumo",
        "#!/bin/sh\nprintf 'not Eclipse SUMO\\n' >&2\nexit 1\n",
    )
    monkeypatch.delenv("SUMO_BINARY", raising=False)
    monkeypatch.delenv("SUMO_HOME", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))

    status = check_sumo_available()

    assert status["available"] is False
    assert "No working Eclipse SUMO executable found" in status["error"]
    assert "Install Eclipse SUMO" in status["install_hint"]
