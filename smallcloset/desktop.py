"""Local Windows entrypoint: wait for readiness, then open the user's browser."""
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser

from .runtime import data_dir


def is_our_server(port):
    # Loopback readiness must not be sent through an upstream corporate proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
            return json.load(response).get("app") == "smallcloset"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def open_when_ready(port, timeout=30, open_browser=None):
    opener = open_browser or webbrowser.open
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_our_server(port):
            return bool(opener(f"http://127.0.0.1:{port}"))
        time.sleep(0.1)
    return False


def reserve_port(preferred):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", preferred))
    except OSError:
        sock.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
    return sock


def main():
    import uvicorn
    from .app import create_app
    directory = data_dir()
    os.environ.setdefault("SM_TESSDATA", str(directory / "tessdata"))
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(directory / "browsers"))
    port = int(os.environ.get("SM_PORT", "8000"))
    if not 1 <= port <= 65535:
        raise SystemExit("SM_PORT must be between 1 and 65535.")
    if is_our_server(port):
        if os.environ.get("SM_NO_AUTO_OPEN") != "1":
            webbrowser.open(f"http://127.0.0.1:{port}")
        print("SmallCloset is already running. Opened the existing local application.")
        return
    sock = reserve_port(port)
    port = sock.getsockname()[1]
    print(f"SmallCloset: http://127.0.0.1:{port}", flush=True)
    print("Keep this window open. Ctrl+C stops the application.", flush=True)
    if os.environ.get("SM_NO_AUTO_OPEN") != "1":
        thread = threading.Thread(target=open_when_ready, args=(port,), daemon=True)
        thread.start()
    server = uvicorn.Server(uvicorn.Config(create_app(directory), host="127.0.0.1", port=port, access_log=False))
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
