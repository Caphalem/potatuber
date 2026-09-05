"""Fetches the frontend's JavaScript libraries on first run.

They're downloaded rather than committed so the repo never redistributes
them — that matters for Cubism Core, which is Live2D's proprietary software
and is fetched straight from Live2D's own server, exactly as a CDN would.
"""

import urllib.request
from pathlib import Path

VENDOR_DIR = Path("frontend/vendor")

# Versions pinned on purpose — a surprise upgrade shouldn't break her face.
FILES = {
    "pixi.min.js":
        "https://cdn.jsdelivr.net/npm/pixi.js@6.5.10/dist/browser/pixi.min.js",
    "cubism4.min.js":
        "https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.4.0/dist/cubism4.min.js",
    "live2dcubismcore.min.js":
        "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js",
}


def ensure() -> None:
    """Download anything missing. Does nothing once everything's in place."""
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        target = VENDOR_DIR / name
        if target.exists():
            continue
        print(f"   Fetching {name}...")
        try:
            request = urllib.request.Request(
                url,
                # Live2D's server refuses Python's default User-Agent (403),
                # so we introduce ourselves like a browser would.
                headers={"User-Agent": "Mozilla/5.0 (PotaTuber)"},
            )
            with urllib.request.urlopen(request) as response:
                target.write_bytes(response.read())
        except Exception as e:
            target.unlink(missing_ok=True)  # never leave a half-written file
            raise RuntimeError(
                f"Couldn't download {name} from {url} — first run needs "
                f"internet access. ({e})"
            ) from e