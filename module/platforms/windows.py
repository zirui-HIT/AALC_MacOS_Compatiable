def initialize_windows() -> None:
    import sys
    from ctypes import c_void_p, windll

    import pyuac

    try:
        windll.user32.SetProcessDpiAwarenessContext(c_void_p(-4))
    except (AttributeError, OSError):
        try:
            windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            windll.user32.SetProcessDPIAware()
    if not pyuac.isUserAdmin():
        pyuac.runAsAdmin(False)
        sys.exit(0)
