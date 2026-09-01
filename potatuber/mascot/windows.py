"""Windows mascot behavior.

WebView2 content can't be made truly transparent on Windows, so we use a
chroma key instead: the WinForms window behind the page is painted magenta,
and every magenta pixel becomes a hole — see-through AND click-through.
Ancient technology, still undefeated.
"""

import ctypes


def set_mode(window, solid: bool) -> None:
    from System import Action
    from System.Drawing import Color

    form = window.native

    def apply():
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