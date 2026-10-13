"""Task events stay in the backend; the frontend chooses their presentation."""

from backend_host.runtime import Signal


class TaskEvents:
    link_start = Signal()
    pause_resume = Signal()
    kill_signal = Signal()
    request_focus = Signal()
    warning = Signal(str)
    hdr_warning = Signal(object)
    tasks_warning = Signal()
    mirror_signal = Signal(int, int)
    mirror_bar_kill_signal = Signal()


mediator = TaskEvents()
