"""Run the potato.

    uv run python -m potatuber            → desktop mascot mode
"""

import json
from pathlib import Path
import pathlib
import socket
import sys
import threading
import time

import uvicorn

from potatuber.config import load

POSITIONS_FILE = Path("positions.json")

def load_positions() -> dict:
    try:
        return json.loads(POSITIONS_FILE.read_text())
    except Exception:
        return {}  # no file yet, or it's mangled — config positions loaded instead
    
def wait_for_server(host: str, port: int, timeout: float = 30.0) -> None:
    """Don't open the window until the server is actually answering."""
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

    # Mascot mode: same server in a background thread, native window on top.
    def serve() -> None:
        from potatuber.server import app

        uvicorn.run(
            app,
            host=config.server.host,
            port=config.server.port,
            log_level="warning",
            timeout_graceful_shutdown=1
        )

    threading.Thread(target=serve, daemon=True).start()
    wait_for_server(config.server.host, config.server.port, timeout=300.0)

    import webview

    windows = []

    positions = load_positions()
    save_timer = None

    def remember(name: str):
        """Save this window's position whenever the user parks it somewhere.

        Saved positions OVERRIDE the config's x/y — those only matter on
        first boot (or after deleting positions.json).
        """
        def on_moved(x, y):
            nonlocal save_timer
            positions[name] = {"x": x, "y": y}
            # Move events fire continuously during a drag — debounce so we
            # write the file once when the dust settles, not 60 times a second.
            if save_timer:
                save_timer.cancel()
            save_timer = threading.Timer(
                0.5, lambda: POSITIONS_FILE.write_text(json.dumps(positions, indent=2))
            )
            save_timer.daemon = True
            save_timer.start()

        return on_moved

    mascot_pos = positions.get("mascot", {"x": config.mascot.x, "y": config.mascot.y})
    subtitle_pos = positions.get("subtitles", {"x": config.subtitles.x, "y": config.subtitles.y})

    mascot_window = webview.create_window(
        "PotaTuber",
        f"http://{config.server.host}:{config.server.port}/mascot/",
        frameless=True,
        transparent=True,
        on_top=True,
        width=config.mascot.width,
        height=config.mascot.height,
        x=mascot_pos["x"],
        y=mascot_pos["y"]
    )
    windows.append(mascot_window)

    subtitle_window = webview.create_window(
        "PotaTuber Subtitles",
        f"http://{config.server.host}:{config.server.port}/subtitles/",
        frameless=True,
        transparent=True,
        on_top=True,
        width=config.subtitles.width,
        height=config.subtitles.height,
        x=subtitle_pos["x"],
        y=subtitle_pos["y"]
    )
    windows.append(subtitle_window)

    solid = {"value": True}  # start solid: click her awake, park the subtitles

    def set_mode(window, make_solid: bool):
        from System import Action
        from System.Drawing import Color

        form = window.native

        def apply():
            if make_solid:
                # Solid: visible dark panel = "you can click and drag me now."
                form.TransparencyKey = Color.Empty
                form.BackColor = Color.FromArgb(30, 30, 30)
            else:
                # Ghost: magenta pixels become see-through AND click-through.
                form.BackColor = Color.Magenta
                form.TransparencyKey = Color.Magenta

        form.Invoke(Action(apply))

    def prep_window(window):
        """Runs once the page has loaded — AFTER pywebview's internal
        show/hide transparency dance, so our mode wins the race.
        (WebView2's DefaultBackgroundColor is already handled by
        transparent=True — we read the source, ehehe.)"""
        set_mode(window, solid["value"])

    for w in windows:
        w.events.loaded += (lambda win: lambda: prep_window(win))(w)

    def toggle():
        solid["value"] = not solid["value"]
        for w in windows:
            set_mode(w, solid["value"])

    import keyboard

    keyboard.add_hotkey(config.mascot.toggle_hotkey, toggle)

    mascot_window.events.moved += remember("mascot")
    subtitle_window.events.moved += remember("subtitles")

    # gets the folder location of the local folder to store pywebview files in.
    storage_path = f"{pathlib.Path().resolve()}/.pywebview_storage"

    # private_mode=False: localStorage persists between runs (remembers
    # zoom level). Default pywebview behavior wipes it on every exit.
    webview.start(storage_path=storage_path, private_mode=False)


if __name__ == "__main__":
    main()