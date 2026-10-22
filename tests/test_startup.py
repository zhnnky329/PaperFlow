"""Exercise startup readiness and failure against real local processes/sockets."""

import importlib.util
import signal
import socket
from pathlib import Path

import httpx


def launcher(monkeypatch, tmp_path, port):
    path = Path(__file__).resolve().parents[1] / "scripts/run.py"
    spec = importlib.util.spec_from_file_location("paperflow_launcher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("PAPERFLOW_DATA_DIR", str(tmp_path / "library"))
    monkeypatch.setenv("PAPERFLOW_PORT", str(port))
    monkeypatch.setenv("PAPERFLOW_MARKER_EXECUTABLE", "/missing/marker")
    monkeypatch.setenv("PAPERFLOW_DISCOVERY_ONLINE", "false")
    monkeypatch.setattr(module, "load_dotenv", lambda *_: None)
    return module


def test_browser_opens_after_real_server_is_ready_and_shutdown_releases_port(monkeypatch, tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    module = launcher(monkeypatch, tmp_path, port)
    calls = []
    old_handler = signal.getsignal(signal.SIGTERM)

    def browser(url):
        with httpx.Client(trust_env=False) as client:
            health = client.get(url + "/api/v1/health")
            assert health.json()["database"] == "ok"
            assert client.get(url + "/").status_code == 200
        calls.append(url)
        raise KeyboardInterrupt

    monkeypatch.setattr(module, "open_browser", browser)
    assert module.main(["serve"]) == 0
    assert calls == [f"http://127.0.0.1:{port}"]
    assert signal.getsignal(signal.SIGTERM) == old_handler
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0


def test_occupied_port_does_not_open_an_existing_service(monkeypatch, tmp_path):
    with socket.socket() as existing:
        existing.bind(("127.0.0.1", 0))
        existing.listen()
        port = existing.getsockname()[1]
        module = launcher(monkeypatch, tmp_path, port)
        calls = []
        monkeypatch.setattr(module, "open_browser", calls.append)
        assert module.main(["serve"]) == 1
        assert calls == []
        assert existing.getsockname()[1] == port
