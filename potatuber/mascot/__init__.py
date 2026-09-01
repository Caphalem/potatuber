"""Her floating body and her subtitles.

Everything platform-independent lives here. The parts that have to fight a
specific operating system live in the sibling modules — each implementing
the same two functions:

    set_mode(window, solid) — ghost (click-through) or solid (clickable)
    cursor_scale(window)    — physical-to-logical pixel ratio

Adding a platform means writing those two. That's the whole contract.
"""

import json
import pathlib
import sys
import threading
import time
from pathlib import Path

from pynput import keyboard, mouse

if sys.platform == "win32":
    from . import windows as platform
elif sys.platform == "darwin":
    from . import macos as platform
else:
    platform = None  # browser mode — see __main__.py

POSITIONS_FILE = Path("positions.json")


def supported() -> bool:
    return platform is not None


def load_positions() -> dict:
    try:
        return json.loads(POSITIONS_FILE.read_text())
    except Exception:
        return {}  # no file yet, or it's mangled — config positions it is


def follow_cursor(window, positions, config) -> None:
    """Feed the global cursor position to the mascot.

    In ghost mode the window is click-through, so the page never sees a single
    pointer event — we read the cursor from the OS and hand it over instead.
    Bonus: she tracks the mouse across the whole screen, not just her window.
    """
    controller = mouse.Controller()

    # webview.start() builds the native window AFTER this thread starts.
    while window.native is None:
        time.sleep(0.1)
    scale = platform.cursor_scale(window)

    last = None
    complained = False
    while True:
        time.sleep(1 / config.face.follow_rate)

        pos = controller.position
        if pos == last:
            continue
        last = pos

        # positions["mascot"] is kept fresh by the "moved" handler below.
        x = pos[0] / scale - positions["mascot"]["x"]
        y = pos[1] / scale - positions["mascot"]["y"]
        try:
            window.evaluate_js(f"window.lookAt && window.lookAt({x}, {y})")
        except Exception as e:
            if not complained:
                print(f"🥔 follow_cursor: {type(e).__name__}: {e}")
                complained = True


def run(config) -> None:
    """Open her windows and hand control to pywebview. Blocks until closed."""
    import webview  # imported here so unsupported platforms never touch it

    base = f"http://{config.server.host}:{config.server.port}"
    positions = load_positions()

    # setdefault does double duty: saved position wins, config is the
    # first-boot fallback, and the dict ends up seeded for follow_cursor.
    mascot_pos = positions.setdefault(
        "mascot", {"x": config.mascot.x, "y": config.mascot.y}
    )
    subtitle_pos = positions.setdefault(
        "subtitles", {"x": config.subtitles.x, "y": config.subtitles.y}
    )

    mascot_window = webview.create_window(
        "PotaTuber",
        f"{base}/mascot/",
        frameless=True,
        transparent=True,
        on_top=True,
        width=config.mascot.width,
        height=config.mascot.height,
        x=mascot_pos["x"],
        y=mascot_pos["y"],
    )
    subtitle_window = webview.create_window(
        "PotaTuber Subtitles",
        f"{base}/subtitles/",
        frameless=True,
        transparent=True,
        on_top=True,
        width=config.subtitles.width,
        height=config.subtitles.height,
        x=subtitle_pos["x"],
        y=subtitle_pos["y"],
    )
    all_windows = [mascot_window, subtitle_window]

    save_timer = None

    def remember(name):
        """Save this window's position whenever you park it somewhere.

        Saved positions OVERRIDE the config's x/y — those only matter on
        first boot, or after deleting positions.json.
        """
        def on_moved(x, y):
            nonlocal save_timer
            positions[name] = {"x": x, "y": y}
            # Move events fire continuously during a drag — debounce so we
            # write the file once when the dust settles.
            if save_timer:
                save_timer.cancel()
            save_timer = threading.Timer(
                0.5, lambda: POSITIONS_FILE.write_text(json.dumps(positions, indent=2))
            )
            save_timer.daemon = True
            save_timer.start()

        return on_moved

    mascot_window.events.moved += remember("mascot")
    subtitle_window.events.moved += remember("subtitles")

    solid = {"value": True}  # start solid so you can click her awake

    def toggle():
        solid["value"] = not solid["value"]
        for w in all_windows:
            platform.set_mode(w, solid["value"])

    def on_loaded(window):
        """Fires AFTER pywebview's internal show/hide dance, so our mode wins."""
        def handler():
            platform.set_mode(window, solid["value"])

        return handler

    for w in all_windows:
        w.events.loaded += on_loaded(w)

    hotkeys = keyboard.GlobalHotKeys({config.mascot.toggle_hotkey: toggle})
    hotkeys.daemon = True
    hotkeys.start()

    if config.face.follow_mouse:
        threading.Thread(
            target=follow_cursor,
            args=(mascot_window, positions, config),
            daemon=True,
        ).start()

    # gets the folder location of the local folder to store pywebview files in.
    storage_path = f"{pathlib.Path().resolve()}/.pywebview_storage"

    # private_mode=False: localStorage persists between runs (she remembers
    # her zoom level). Default pywebview behavior wipes it on every exit.
    webview.start(storage_path=storage_path, private_mode=False)