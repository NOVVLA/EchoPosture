"""Regression tests for startup calibration and tray-control state guards."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from tray_app import TrayMonitor
from tray_flyout import TrayFlyout
from vision_modes import (
    VISION_MODE_COMPATIBILITY,
    VISION_MODE_PROFESSIONAL_BETA,
    VISION_MODE_STANDARD,
    ModeAvailability,
)
from vision_test import PostureDecision


class _Worker:
    def __init__(self) -> None:
        self.active = False
        self.pause_calls = 0
        self.resume_calls = 0
        self.begin_calibration_calls = 0
        self.complete_preferred_calls = 0
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

    def complete_preferred_calibration(self, _distance) -> int:
        self.complete_preferred_calls += 1
        return self.complete_preferred_calls


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


class _CountdownTimer:
    def __init__(self) -> None:
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


class _Tray:
    def __init__(self) -> None:
        self.messages = []

    def showMessage(self, *_args) -> None:
        self.messages.append(_args)


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
        self._calibration_prompt_context = None
        self.calibrated_distance_cm = 60.0
        self.worker = _Worker()
        self.overlay = _Overlay()
        self.timer = _Timer()
        self.countdown_timer = _CountdownTimer()
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


class _InterventionDouble:
    def __init__(self) -> None:
        self._intervention_candidate_started_at = None
        self._intervention_episode_active = False
        self._last_intervention_ended_at = None


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
        self.assertEqual(monitor.worker.complete_preferred_calls, 0)
        self.assertIsNone(monitor._awaiting_calibration)

    def test_countdown_closes_before_silent_relaxed_collection(self) -> None:
        events = []

        class Dialog:
            def step(self) -> bool:
                events.append("countdown_finished")
                return True

            def close(self) -> None:
                events.append("dialog_closed")

        class Worker(_Worker):
            def complete_preferred_calibration(self, _distance) -> int:
                events.append("relaxed_requested")
                return super().complete_preferred_calibration(_distance)

        class Tray(_Tray):
            def showMessage(self, *_args) -> None:
                events.append("relax_prompted")
                super().showMessage(*_args)

        monitor = _MonitorDouble()
        monitor.calibration_dialog = Dialog()
        monitor.worker = Worker()
        monitor.tray = Tray()
        monitor._calibration_prompt_context = ("startup", False)

        TrayMonitor._countdown_step(monitor)

        self.assertEqual(
            events,
            [
                "countdown_finished",
                "dialog_closed",
                "relaxed_requested",
                "relax_prompted",
            ],
        )
        self.assertIsNone(monitor.calibration_dialog)
        self.assertEqual(monitor.worker.complete_preferred_calls, 1)
        self.assertEqual(monitor.worker.finalize_calibration_calls, 0)
        self.assertEqual(monitor._awaiting_calibration, ("startup", False))

    def test_silent_relaxed_collection_keeps_controls_guarded(self) -> None:
        monitor = _MonitorDouble()
        monitor._awaiting_calibration = ("recal", True)

        self.assertFalse(TrayMonitor.pause_monitoring(monitor))
        self.assertFalse(TrayMonitor.resume_monitoring(monitor))
        TrayMonitor.recalibrate_now(monitor)

        self.assertEqual(monitor.worker.pause_calls, 0)
        self.assertEqual(monitor.worker.resume_calls, 0)
        self.assertEqual(monitor.worker.begin_calibration_calls, 0)

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

    def test_scientific_intervention_requires_confidence_and_exposure(self) -> None:
        monitor = _InterventionDouble()
        low_confidence = PostureDecision(
            "BAD",
            "test",
            True,
            posture_deviation=0.9,
            exposure_seconds=20.0,
            confidence=0.4,
            calibration_quality=1.0,
        )
        self.assertFalse(TrayMonitor._should_intervene(monitor, low_confidence))

        eligible = PostureDecision(
            "BAD",
            "test",
            True,
            posture_deviation=0.9,
            exposure_seconds=20.0,
            confidence=0.9,
            calibration_quality=1.0,
        )
        self.assertFalse(TrayMonitor._should_intervene(monitor, eligible))
        monitor._intervention_candidate_started_at = datetime.now() - timedelta(seconds=4)
        self.assertTrue(TrayMonitor._should_intervene(monitor, eligible))
        self.assertTrue(monitor._intervention_episode_active)

    def test_intervention_episode_has_cooldown_after_it_ends(self) -> None:
        monitor = _InterventionDouble()
        monitor._intervention_episode_active = True
        good = PostureDecision("GOOD", "test", True)
        self.assertFalse(TrayMonitor._should_intervene(monitor, good))
        self.assertIsNotNone(monitor._last_intervention_ended_at)

        eligible = PostureDecision(
            "BAD",
            "test",
            True,
            posture_deviation=1.0,
            exposure_seconds=30.0,
            confidence=1.0,
            calibration_quality=1.0,
        )
        monitor._intervention_candidate_started_at = datetime.now() - timedelta(seconds=4)
        self.assertFalse(TrayMonitor._should_intervene(monitor, eligible))


class VisionModeFallbackTests(unittest.TestCase):
    """The degradation order must never silently skip a usable tier."""

    @staticmethod
    def _monitor(available=(VISION_MODE_COMPATIBILITY, VISION_MODE_STANDARD)):
        return SimpleNamespace(
            mode_availability={
                mode: ModeAvailability(mode in available)
                for mode in (
                    VISION_MODE_COMPATIBILITY,
                    VISION_MODE_STANDARD,
                    VISION_MODE_PROFESSIONAL_BETA,
                )
            }
        )

    def test_professional_degrades_through_standard_before_compatibility(self) -> None:
        chain = TrayMonitor._fallback_chain(
            self._monitor(),
            VISION_MODE_PROFESSIONAL_BETA,
            "startup",
            VISION_MODE_COMPATIBILITY,
        )
        self.assertEqual(chain, [VISION_MODE_STANDARD, VISION_MODE_COMPATIBILITY])

    def test_professional_skips_standard_when_it_is_unavailable(self) -> None:
        chain = TrayMonitor._fallback_chain(
            self._monitor(available=(VISION_MODE_COMPATIBILITY,)),
            VISION_MODE_PROFESSIONAL_BETA,
            "startup",
            VISION_MODE_COMPATIBILITY,
        )
        self.assertEqual(chain, [VISION_MODE_COMPATIBILITY])

    def test_runtime_switch_prefers_returning_to_the_previous_mode(self) -> None:
        chain = TrayMonitor._fallback_chain(
            self._monitor(),
            VISION_MODE_PROFESSIONAL_BETA,
            "runtime",
            VISION_MODE_STANDARD,
        )
        # Standard is both the degradation target and the previous mode; it must
        # appear once, ahead of compatibility.
        self.assertEqual(chain, [VISION_MODE_STANDARD, VISION_MODE_COMPATIBILITY])

    def test_compatibility_failure_is_terminal(self) -> None:
        chain = TrayMonitor._fallback_chain(
            self._monitor(),
            VISION_MODE_COMPATIBILITY,
            "startup",
            VISION_MODE_COMPATIBILITY,
        )
        self.assertEqual(chain, [])

    def test_professional_start_gets_a_longer_budget_than_the_other_tiers(self) -> None:
        monitor = self._monitor()
        professional = TrayMonitor._mode_start_timeout(monitor, VISION_MODE_PROFESSIONAL_BETA)
        standard = TrayMonitor._mode_start_timeout(monitor, VISION_MODE_STANDARD)
        # First professional launch builds a CUDA context and benchmarks l and x.
        self.assertGreater(professional, standard)
        self.assertEqual(standard, TrayMonitor._mode_start_timeout(monitor, VISION_MODE_COMPATIBILITY))


if __name__ == "__main__":
    unittest.main()
