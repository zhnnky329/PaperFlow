"""Ubuntu path selection, native desktop opening and Linux filename boundaries."""

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import desktop
from app.config import Config
from app.folders import FolderConflict, folder_name


@pytest.mark.parametrize("xdg", [None, "", "relative/path", "/tmp/paperflow-xdg"])
def test_xdg_data_directory_is_evaluated_for_each_config(monkeypatch, tmp_path, xdg):
    monkeypatch.delenv("PAPERFLOW_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    if xdg is None:
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_DATA_HOME", xdg)
    expected = Path(xdg) if xdg and Path(xdg).is_absolute() else tmp_path / ".local/share"
    assert Config(_env_file=None).data_dir == expected / "paperflow"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "changed"))
    assert Config(_env_file=None).data_dir == tmp_path / "changed/paperflow"


def test_explicit_data_directory_wins_and_expands_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("PAPERFLOW_DATA_DIR", "~/my papers")
    assert Config(_env_file=None).data_dir == tmp_path / "my papers"
    assert Config(_env_file=None, data_dir=tmp_path / "explicit").data_dir == tmp_path / "explicit"
    with pytest.raises(ValidationError, match="absolute path"):
        Config(_env_file=None, data_dir="relative")


@pytest.mark.parametrize("session", ["DISPLAY", "WAYLAND_DISPLAY"])
def test_native_opener_keeps_path_as_a_single_argument(monkeypatch, tmp_path, session):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv(session, ":1")
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/xdg-open")
    calls = []
    monkeypatch.setattr(desktop.subprocess, "run", lambda argv, **kw: calls.append((argv, kw)))
    directory = tmp_path / "中文 papers; $(anything)"
    desktop.open_folder(directory)
    assert calls[0][0] == ["/usr/bin/xdg-open", str(directory)]
    assert calls[0][1] == {"check": True, "timeout": 5, "capture_output": True}


def test_gio_fallback_and_no_desktop_do_not_launch(monkeypatch, tmp_path):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/gio" if name == "gio" else None)
    assert desktop.folder_opener() == ["/usr/bin/gio", "open"]
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(desktop.subprocess, "run", lambda *_a, **_kw: pytest.fail("spawned without desktop"))
    assert desktop.folder_opener() is None
    with pytest.raises(OSError):
        desktop.open_folder(tmp_path)


@pytest.mark.parametrize("failure", [OSError(), subprocess.TimeoutExpired("xdg-open", 5)])
def test_reveal_reports_unavailable_and_preserves_folder(client, app, monkeypatch, failure):
    row = client.post("/api/v1/collections", json={"name": "Ubuntu papers"}).json()
    app.state.folder_sync.sync()
    path = Path(client.get("/api/v1/collections").json()[0]["folder_path"])
    assert (path / ".paperflow.json").is_file()

    def fail(_path):
        raise failure

    monkeypatch.setattr(desktop, "open_folder", fail)
    response = client.post(f"/api/v1/collections/{row['id']}/reveal")
    assert response.status_code == 503
    assert (path / ".paperflow.json").is_file()


def test_reveal_validated_folder_on_ubuntu(client, app, monkeypatch):
    row = client.post("/api/v1/collections", json={"name": "论文"}).json()
    app.state.folder_sync.sync()
    paths = []
    monkeypatch.setattr(desktop, "open_folder", paths.append)
    assert client.post(f"/api/v1/collections/{row['id']}/reveal").json() == {"opened": True}
    assert paths == [Path(client.get("/api/v1/collections").json()[0]["folder_path"])]


def test_linux_filename_byte_limit_preserves_normalization():
    assert folder_name("e\u0301") == "é"
    assert folder_name("中" * 80) == "中" * 80
    with pytest.raises(FolderConflict, match="255 字节"):
        folder_name("😀" * 64)
