"""macOS mascot behavior.

Cocoa has real per-pixel window transparency, so this file is about a tenth
the size of the Windows one.
"""

import AppKit
from PyObjCTools import AppHelper



def set_mode(window, solid: bool) -> None:
    def apply():
        ns = window.native
        if solid:
            ns.setIgnoresMouseEvents_(False)
            ns.setOpaque_(True)
            ns.setBackgroundColor_(
                AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(
                    0.12, 0.12, 0.12, 1.0
                )
            )
        else:
            ns.setOpaque_(False)
            ns.setBackgroundColor_(AppKit.NSColor.clearColor())
            ns.setIgnoresMouseEvents_(True)  # one call. That's the whole hack.

    # Cocoa's version of form.Invoke — UI work belongs on the main thread.
    AppHelper.callAfter(apply)


def cursor_scale(window) -> float:
    """Cocoa works in logical points, and so does the cursor. No math needed."""
    return 1.0