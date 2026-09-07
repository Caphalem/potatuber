"""Run the potato.

    uv run python -m potatuber              → mascot windows on your desktop
    uv run python -m potatuber --headless   → server only, open her in a browser
"""

import socket
import sys
import threading
import time

import uvicorn

from potatuber import mascot
from potatuber.config import load


def wait_for_server(host: str, port: int, timeout: float = 120.0) -> None:
    """Don't open the windows until the server is actually answering.

    The organs (and possibly a few model downloads) load first, so this can
    take a while on the very first run.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("Server never came up. Check the logs above.")


def main() -> None:
    config = load()
    url = f"http://{config.server.host}:{config.server.port}"
    headless = "--headless" in sys.argv

    if config.vts.enabled:
        # VTube Studio is her body — no mascot window needed. Everything
        # else (console, subtitles, ears, brain) works exactly the same.
        print("🥔 VTube Studio mode — make sure VTS is running with the API enabled.")
        headless = True
    elif not headless and not mascot.supported():
        print(f"🥔 Desktop mascot windows aren't supported on {sys.platform} yet.")
        print(f"   Running in browser mode instead — open {url}/mascot/")
        headless = True

    def serve(**kwargs) -> None:
        from potatuber.server import app

        uvicorn.run(
            app,
            host=config.server.host,
            port=config.server.port,
            timeout_graceful_shutdown=1,
            **kwargs,
        )

    if headless:
        print(f"🥔 Console: {url}/")
        serve()
        return

    threading.Thread(target=lambda: serve(log_level="warning"), daemon=True).start()
    wait_for_server(config.server.host, config.server.port)
    print(f"🥔 Console: {url}/")
    mascot.run(config)


if __name__ == "__main__":
    main()