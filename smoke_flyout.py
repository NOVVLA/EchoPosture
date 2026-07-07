"""TrayFlyout 烟雾测试：跳过摄像头/校准/开场弹窗，直接弹浮窗。

用途：手动验证语言切换按钮，不依赖摄像头和主程序完整启动流程。
运行：python smoke_flyout.py
关闭：点 Exit 按钮，或关闭窗口。
"""

from __future__ import annotations

import sys

from PyQt5.QtWidgets import QApplication

from tray_flyout import TrayFlyout


class _StubMonitor:
    """替身 monitor：所有动作空实现，只让 TrayFlyout 能初始化和切换语言。"""

    def is_monitoring(self) -> bool:
        return True

    def resume_monitoring(self) -> None:
        pass

    def pause_monitoring(self) -> None:
        pass

    def open_console(self) -> None:
        pass

    def recalibrate_now(self) -> None:
        pass

    def trigger_max_visual_effect(self) -> None:
        pass

    def stop(self) -> None:
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    flyout = TrayFlyout(_StubMonitor())
    flyout.popup_bottom_right()
    sys.exit(app.exec_())
