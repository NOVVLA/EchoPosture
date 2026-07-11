"""Regression tests for tray flyout language-state synchronization."""

from __future__ import annotations

from unittest.mock import patch

from tray_flyout import TrayFlyout


class _TextSink:
    def setText(self, _value) -> None:
        pass

    def setToolTip(self, _value) -> None:
        pass

    def adjustSize(self) -> None:
        pass

    def height(self) -> int:
        return 10

    def move(self, _x, _y) -> None:
        pass


class _Switch:
    def is_on(self) -> bool:
        return True


class _Monitor:
    def __init__(self) -> None:
        self.calls = 0

    def is_monitoring(self) -> bool:
        self.calls += 1
        return False


class _FlyoutDouble:
    def __init__(self) -> None:
        self.recalibrate_button = _TextSink()
        self.max_effect_button = _TextSink()
        self.lang_button = _TextSink()
        self.exit_button = _TextSink()
        self.gear_button = _TextSink()
        self.caption = _TextSink()
        self.switch = _Switch()
        self.monitor = _Monitor()
        self.state = None

    def _update_state_label(self, on: bool) -> None:
        self.state = on

    def _apply_texts(self) -> None:
        pass


def test_language_refresh_preserves_switch_state() -> None:
    flyout = _FlyoutDouble()

    TrayFlyout._apply_texts(flyout)

    assert flyout.monitor.calls == 0
    assert flyout.state is True


def test_popup_restores_language_listener() -> None:
    flyout = _FlyoutDouble()

    with patch("tray_flyout.add_listener", side_effect=RuntimeError("registered")):
        try:
            TrayFlyout.popup_bottom_right(flyout)
        except RuntimeError as exc:
            assert str(exc) == "registered"
        else:
            raise AssertionError("popup did not restore the language listener")


if __name__ == "__main__":
    test_language_refresh_preserves_switch_state()
    test_popup_restores_language_listener()
    print("ALL TESTS PASSED")
