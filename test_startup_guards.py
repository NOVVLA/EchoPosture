"""Regression tests for startup calibration and tray-control state guards."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from tray_app import TrayMonitor
from tray_flyout import TrayFlyout


class _Worker:
    def __init__(self) -> None:
        self.active = False
        self.pause_calls = 0
        self.resume_calls = 0
        self.begin_calibration_calls = 0
        self.finalize_calibration_calls = 0

    def is_monitoring_active(self) -> bool:
        return self.active

    def pause(self) -> None:
        self.active = False
        self.pause_calls += 1

    def resume(self) -> None:
        self.active = True
        self.resume_calls += 1

    def begin_calibration_sampling(self) -> None:
        self.begin_calibration_calls += 1

    def finalize_calibration(self, _distance, sample_count=1) -> None:
        del sample_count
        self.finalize_calibration_calls += 1


class _Overlay:
    def __init__(self) -> None:
        self.force_clear_calls = 0

    def force_clear(self) -> None:
        self.force_clear_calls += 1


class _Timer:
    def isActive(self) -> bool:
        return True

    def start(self) -> None:
        raise AssertionError("timer was already active")


class _Tray:
    def showMessage(self, *_args) -> None:
        pass


class _MonitorDouble:
    def __init__(self) -> None:
        self._stopping = False
        self._awaiting_calibration = None
        self._monitoring_started = False
        self._calibrated = False
        self._intervention_candidate_started_at = object()
        self._manual_effect_until = object()
        self.onboarding_toast = None
        self.calibration_dialog = None
        self.calibrated_distance_cm = 60.0
        self.worker = _Worker()
        self.overlay = _Overlay()
        self.timer = _Timer()
        self.tray = _Tray()

    def _start_monitoring(self) -> None:
        TrayMonitor._start_monitoring(self)

    def stop(self) -> None:
        raise AssertionError("startup success must not stop the monitor")


class _Switch:
    def __init__(self) -> None:
        self.set_calls = []

    def set_on(self, on: bool, animate: bool = True) -> None:
        self.set_calls.append((on, animate))


class _FlyoutMonitor:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.resume_calls = 0
        self.is_monitoring_calls = 0

    def resume_monitoring(self) -> bool:
        self.resume_calls += 1
        return self.result

    def pause_monitoring(self) -> bool:
        return self.result

    def is_monitoring(self) -> bool:
        self.is_monitoring_calls += 1
        return self.result


class _FlyoutDouble:
    def __init__(self, result: bool) -> None:
        self.monitor = _FlyoutMonitor(result)
        self.switch = _Switch()
        self.label_state = None

    def _update_state_label(self, on: bool) -> None:
        self.label_state = on


class StartupGuardTests(unittest.TestCase):
    def test_resume_is_rejected_during_onboarding(self) -> None:
        monitor = _MonitorDouble()
        monitor.onboarding_toast = object()

        result = TrayMonitor.resume_monitoring(monitor)

        self.assertIs(result, False)
        self.assertEqual(monitor.worker.resume_calls, 0)
        self.assertFalse(monitor._monitoring_started)

    def test_pause_is_rejected_during_startup_calibration(self) -> None:
        monitor = _MonitorDouble()
        monitor.calibration_dialog = object()
        candidate = monitor._intervention_candidate_started_at
        manual_effect = monitor._manual_effect_until

        result = TrayMonitor.pause_monitoring(monitor)

        self.assertIs(result, False)
        self.assertEqual(monitor.worker.pause_calls, 0)
        self.assertEqual(monitor.overlay.force_clear_calls, 0)
        self.assertIs(monitor._intervention_candidate_started_at, candidate)
        self.assertIs(monitor._manual_effect_until, manual_effect)

    def test_recalibration_is_rejected_during_startup_dialog(self) -> None:
        monitor = _MonitorDouble()
        monitor.calibration_dialog = object()

        TrayMonitor.recalibrate_now(monitor)

        self.assertEqual(monitor.worker.begin_calibration_calls, 0)
        self.assertEqual(monitor.worker.finalize_calibration_calls, 0)
        self.assertIsNone(monitor._awaiting_calibration)

    def test_prestarted_worker_is_resumed_after_startup_calibration(self) -> None:
        monitor = _MonitorDouble()
        monitor._monitoring_started = True
        monitor._awaiting_calibration = ("startup", False)

        TrayMonitor._on_calibration_result(monitor, SimpleNamespace(ok=True))

        self.assertEqual(monitor.worker.resume_calls, 1)
        self.assertTrue(monitor.worker.active)

    def test_normal_resume_still_succeeds_after_startup(self) -> None:
        monitor = _MonitorDouble()
        monitor._monitoring_started = True

        result = TrayMonitor.resume_monitoring(monitor)

        self.assertIs(result, True)
        self.assertEqual(monitor.worker.resume_calls, 1)

    def test_normal_pause_still_succeeds_after_startup(self) -> None:
        monitor = _MonitorDouble()
        monitor.worker.active = True

        result = TrayMonitor.pause_monitoring(monitor)

        self.assertIs(result, True)
        self.assertEqual(monitor.worker.pause_calls, 1)
        self.assertEqual(monitor.overlay.force_clear_calls, 1)

    def test_rejected_flyout_toggle_restores_previous_state(self) -> None:
        flyout = _FlyoutDouble(result=False)

        TrayFlyout._on_switch_toggled(flyout, True)

        self.assertEqual(flyout.switch.set_calls, [(False, True)])
        self.assertIs(flyout.label_state, False)
        self.assertEqual(flyout.monitor.is_monitoring_calls, 0)

    def test_accepted_flyout_toggle_keeps_normal_state_sync(self) -> None:
        flyout = _FlyoutDouble(result=True)

        TrayFlyout._on_switch_toggled(flyout, True)

        self.assertEqual(flyout.switch.set_calls, [])
        self.assertIs(flyout.label_state, True)
        self.assertEqual(flyout.monitor.is_monitoring_calls, 1)


if __name__ == "__main__":
    unittest.main()
