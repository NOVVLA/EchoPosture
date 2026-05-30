"""
EchoPosture (潜影护脊) - Step 2 overlay intervention test.

This script creates a fullscreen, always-on-top, mouse-transparent black overlay.
It repeatedly fades the overlay in to 35% opacity, then quickly clears it.

Controls:
- Press Ctrl+C in the terminal to stop.
- If needed, close the terminal window to force quit.
"""

from __future__ import annotations

import ctypes
import signal
import sys
from typing import Optional

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PyQt5.QtGui import QColor, QGuiApplication
from PyQt5.QtWidgets import QApplication, QWidget


MAX_ALPHA = 0.35
FADE_IN_MS = 2600
FADE_OUT_MS = 300
HOLD_MS = 1200


class OverlayWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._animation: Optional[QPropertyAnimation] = None
        self._darkening = False

        self.setWindowTitle("EchoPosture Overlay Test")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )

        self._cover_all_screens()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._enable_windows_click_through()

    def fade_to(self, target_opacity: float, duration_ms: int) -> None:
        if self._animation is not None:
            self._animation.stop()

        self._animation = QPropertyAnimation(self, b"windowOpacity", self)
        self._animation.setStartValue(self.windowOpacity())
        self._animation.setEndValue(target_opacity)
        self._animation.setDuration(duration_ms)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.start()

    def fade_in(self) -> None:
        self._darkening = True
        self.fade_to(MAX_ALPHA, FADE_IN_MS)

    def clear_fast(self) -> None:
        self._darkening = False
        self.fade_to(0.0, FADE_OUT_MS)

    def paintEvent(self, event) -> None:
        painter = None
        try:
            from PyQt5.QtGui import QPainter

            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 255))
        finally:
            if painter is not None:
                painter.end()

    def _cover_all_screens(self) -> None:
        screens = QGuiApplication.screens()
        if not screens:
            return

        rect = screens[0].geometry()
        for screen in screens[1:]:
            rect = rect.united(screen.geometry())
        self.setGeometry(rect)

    def _enable_windows_click_through(self) -> None:
        if sys.platform != "win32":
            return

        hwnd = int(self.winId())
        user32 = ctypes.windll.user32

        gwl_exstyle = -20
        ws_ex_layered = 0x00080000
        ws_ex_transparent = 0x00000020
        ws_ex_toolwindow = 0x00000080

        style = user32.GetWindowLongW(hwnd, gwl_exstyle)
        style |= ws_ex_layered | ws_ex_transparent | ws_ex_toolwindow
        user32.SetWindowLongW(hwnd, gwl_exstyle, style)


class OverlayDemo:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.overlay = OverlayWindow()
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._next_phase)
        self.phase = "idle"

    def start(self) -> None:
        self.overlay.setWindowOpacity(0.0)
        self.overlay.showFullScreen()
        self._start_fade_in()

    def stop(self) -> None:
        self.timer.stop()
        self.overlay.close()
        self.app.quit()

    def _start_fade_in(self) -> None:
        print("Overlay fading in to 35%. Mouse clicks should pass through it.", flush=True)
        self.phase = "dark"
        self.overlay.fade_in()
        self.timer.start(FADE_IN_MS + HOLD_MS)

    def _start_clear(self) -> None:
        print("Overlay clearing quickly to 0%.", flush=True)
        self.phase = "clear"
        self.overlay.clear_fast()
        self.timer.start(FADE_OUT_MS + HOLD_MS)

    def _next_phase(self) -> None:
        if self.phase == "dark":
            self._start_clear()
        else:
            self._start_fade_in()


def main() -> int:
    app = QApplication(sys.argv)
    demo = OverlayDemo(app)

    signal.signal(signal.SIGINT, lambda *_args: demo.stop())

    # Let Python process Ctrl+C while the Qt event loop is running.
    interrupt_timer = QTimer()
    interrupt_timer.timeout.connect(lambda: None)
    interrupt_timer.start(100)

    demo.start()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
