"""Windows mascot behavior.

WebView2 content can't be made truly transparent on Windows, so we use a
chroma key instead: the WinForms window behind the page is painted magenta,
and every magenta pixel becomes a hole — see-through AND click-through.
Ancient technology, still undefeated.

Windows 11 adds one wrinkle: pywebview gives dark-theme windows a Mica
backdrop, which paints itself between the page and the magenta and hides
the key. We switch the backdrop off on every mode change (see
_disable_backdrop) and 11 behaves exactly like 10.
"""

import ctypes

DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_NONE = 1


def _disable_backdrop(form) -> None:
    """Windows 11 only. pywebview gives dark-theme windows a Mica backdrop
    (DwmSetWindowAttribute 38 = 2): a wallpaper-tinted grey painted BEHIND
    the page. Transparent pixels then show Mica instead of the form, so the
    chroma key never sees its magenta and she floats on a grey slab. Turn it
    off. On Windows 10 the attribute doesn't exist and the call fails
    harmlessly, so there's no version check."""
    value = ctypes.c_int(DWMSBT_NONE)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(
        form.Handle.ToInt32(), DWMWA_SYSTEMBACKDROP_TYPE,
        ctypes.byref(value), ctypes.sizeof(value),
    )


def set_mode(window, solid: bool) -> None:
    from System import Action
    from System.Drawing import Color

    form = window.native

    def apply():
        _disable_backdrop(form)

        if solid:
            # No chroma hole: the form's background shows, which doubles as
            # the "you can click and drag me now" indicator.
            form.TransparencyKey = Color.Empty
            form.BackColor = Color.FromArgb(30, 30, 30)
        else:
            form.BackColor = Color.Magenta
            form.TransparencyKey = Color.Magenta

    # WinForms law: only the UI thread may touch the form. Calling apply()
    # directly from another thread deadlocks the whole window.
    form.Invoke(Action(apply))


def cursor_scale(window) -> float:
    """Cursor positions arrive in physical pixels; pywebview windows live in
    logical ones. Read once — moving her to a monitor with a different DPI
    will throw tracking off until restart."""
    return ctypes.windll.user32.GetDpiForWindow(window.native.Handle.ToInt64()) / 96