"""Deterministic offscreen checks for the visual debug panel."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt5.QtWidgets import QApplication

from debug_ui import DebugWindow
from vision_backend import observation_from_sample
from vision_test import VisionSample


T0 = datetime(2026, 1, 1, 12, 0, 0)


def make_sample(timestamp: datetime = T0, relaxed: float = 0.0) -> VisionSample:
    shoulder_width = 200.0
    return VisionSample(
        timestamp=timestamp,
        interpupillary_px=60.0 + relaxed * 20.0,
        shoulder_diff_px=4.0 + relaxed * 18.0,
        signed_shoulder_diff_px=4.0 + relaxed * 18.0,
        shoulder_width_px=shoulder_width,
        trunk_lean_deg=2.0 + relaxed * 10.0,
        face_detected=True,
        pose_detected=True,
        face_count=1,
        frame_width=640,
        frame_height=480,
        left_eye_center=(290.0, 150.0),
        right_eye_center=(350.0, 150.0),
        face_nose_point=(320.0, 170.0),
        nose_point=(320.0, 170.0),
        left_shoulder_point=(220.0, 240.0),
        right_shoulder_point=(420.0, 244.0 + relaxed * 18.0),
        left_hip_point=(260.0, 390.0),
        right_hip_point=(380.0, 390.0),
        shoulder_center=(320.0, 242.0 + relaxed * 9.0),
        hip_center=(320.0, 390.0),
        head_turn_ratio=0.02,
        torso_height_px=180.0 - relaxed * 40.0,
        face_quality=1.0,
        pose_quality=1.0,
        target_motion=0.0,
        activity_state="STATIC",
    )


class FakeDebugBackend:
    """Camera-free backend implementing the subset used by DebugWindow."""

    def __init__(self) -> None:
        self.sample = make_sample()
        self.observations = ()
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def read_frame_sample(self):
        self.observations = observation_from_sample(self.sample)
        return np.zeros((480, 640, 3), dtype=np.uint8), self.sample

    def observations_for_last_sample(self):
        return self.observations

    def set_capture_fps(self, _fps: float) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def make_window(app: QApplication, backend: FakeDebugBackend) -> DebugWindow:
    return DebugWindow(
        camera_id=0,
        fps=4.0,
        width=640,
        height=480,
        intervention_enabled=False,
        target_panel=True,
        backend_factory=lambda: backend,
    )


def test_debug_panel_runs_full_dual_anchor_calibration() -> None:
    app = QApplication.instance() or QApplication([])
    backend = FakeDebugBackend()
    window = make_window(app, backend)
    try:
        window.update_frame()
        assert backend.started
        assert window.target_state_label.text() == "正在获取目标"
        assert window.target_track_label.text() == "--"
        assert window.target_count_label.text() == "1"
        assert window.current_sample is not None
        assert window.current_sample.target_state == "ACQUIRING"

        window.start_dual_anchor_calibration()
        window.dual_calibration_timer.stop()
        preferred_style = window.calibration_stage_card.styleSheet()
        assert window._calibration_visual_phase == "preferred"
        assert "background: #17633a" in preferred_style
        assert "color: white" in preferred_style
        assert window.calibration_stage_badge.text() == "1/2"
        assert window.calibration_stage_progress.value() == 20
        assert "阶段 1/2" in window.calibration_stage_title.text()
        assert "5s" in window.calibration_stage_title.text()
        assert "现在不要放松" in window.calibration_stage_detail.text()
        assert not window.calibration_camera_stage_banner.isHidden()
        assert "阶段 1/2" in window.calibration_camera_stage_banner.text()
        assert "坐直姿势" in window.calibration_camera_stage_banner.text()
        for index in range(5):
            backend.sample = make_sample(T0 + timedelta(seconds=index))
            window.update_frame()
        assert window._dual_calibration_accumulator is not None
        assert window._dual_calibration_accumulator.stage_counts == {
            "preferred": 5,
            "relaxed": 0,
        }
        window.complete_preferred_stage(T0 + timedelta(seconds=5))
        assert window.calibration_label.text().startswith("舒适坐姿阶段完成")
        transition_style = window.calibration_stage_card.styleSheet()
        assert window._calibration_visual_phase == "transition"
        assert "background: #9a4f00" in transition_style
        assert window.calibration_stage_badge.text() == "放松"
        assert window.calibration_stage_progress.value() == 50
        assert "现在可以自然放松" in window.calibration_stage_title.text()
        assert not window.calibration_camera_prompt.isHidden()
        assert "现在可以自然放松" in window.calibration_camera_prompt.text()
        assert window.calibration_camera_prompt.parent() is window.video_label
        assert "阶段切换" in window.calibration_camera_stage_banner.text()
        prompt_geometry = window.calibration_camera_prompt.geometry()
        assert window.video_label.rect().contains(prompt_geometry)
        assert transition_style != preferred_style
        backend.sample = make_sample(T0 + timedelta(seconds=5.5), relaxed=0.5)
        window.update_frame()
        assert window._dual_calibration_accumulator.stage_counts == {
            "preferred": 5,
            "relaxed": 0,
        }
        assert window._calibration_visual_phase == "transition"
        backend.sample = make_sample(T0 + timedelta(seconds=6), relaxed=1.0)
        window.update_frame()
        relaxed_style = window.calibration_stage_card.styleSheet()
        assert window._calibration_visual_phase == "relaxed"
        assert "background: #6d35ad" in relaxed_style
        window.calibration_camera_prompt_timer.stop()
        window.calibration_camera_prompt.hide()
        assert window.calibration_stage_badge.text() == "2/2"
        assert window.calibration_stage_progress.value() == 80
        assert "阶段 2/2" in window.calibration_stage_title.text()
        assert "5s" in window.calibration_stage_title.text()
        assert "保持自然放松" in window.calibration_stage_detail.text()
        assert not window.calibration_camera_stage_banner.isHidden()
        assert "阶段 2/2" in window.calibration_camera_stage_banner.text()
        assert "自然放松姿势" in window.calibration_camera_stage_banner.text()
        banner_geometry = window.calibration_camera_stage_banner.geometry()
        assert window.video_label.rect().contains(banner_geometry)
        assert relaxed_style not in {preferred_style, transition_style}
        for index in range(4):
            backend.sample = make_sample(
                T0 + timedelta(seconds=(7 + index if index < 3 else 11)),
                relaxed=1.0,
            )
            window.update_frame()

        assert window.analyzer.calibration_profile is not None
        assert window.analyzer.require_dual_anchor
        assert window.analyzer.calibration_profile.stage_counts == {
            "preferred": 5,
            "relaxed": 5,
        }
        assert window.calibration_label.text().startswith("双锚点科学校准完成")
        assert window._calibration_visual_phase == "active"
        assert window.calibration_stage_badge.text() == "监测"
        assert "正式监测中" in window.calibration_stage_title.text()
        assert window.calibration_camera_stage_banner.isHidden()
        assert window.calibration_stage_card.styleSheet() not in {
            preferred_style,
            transition_style,
            relaxed_style,
        }
        backend.sample = make_sample(T0 + timedelta(seconds=13), relaxed=1.0)
        window.update_frame()
        assert window._calibration_visual_phase == "active"
        assert window.calibration_stage_badge.text() == "监测"
        assert window.calibration_stage_progress.value() == 100
        assert "正式监测中" in window.calibration_stage_title.text()
        assert window.target_state_label.text() == "目标已锁定"
        assert window.target_track_label.text() == "1"
        assert window.target_count_label.text() == "1"
        assert window.current_sample is not None
        assert window.current_sample.target_track_id == 1
        assert window.current_sample.target_state == "TARGET_LOCKED"

        profile = window.analyzer.calibration_profile
        window.start_dual_anchor_calibration()
        window.dual_calibration_timer.stop()
        window.cancel_dual_anchor_calibration()
        assert window.analyzer.calibration_profile is profile
        assert window.calibration_label.text().startswith("已取消双锚点校准")
        assert window.legacy_calibrate_button.isEnabled()
        assert window.precision_checkbox.isEnabled()
    finally:
        window.close()
        app.processEvents()
        assert backend.closed
    print("test_debug_panel_runs_full_dual_anchor_calibration OK")


def test_debug_panel_places_stage_card_above_camera() -> None:
    app = QApplication.instance() or QApplication([])
    backend = FakeDebugBackend()
    window = make_window(app, backend)
    try:
        window.show()
        app.processEvents()
        stage_geometry = window.calibration_stage_card.geometry()
        video_geometry = window.video_label.geometry()
        assert stage_geometry.width() == video_geometry.width()
        assert stage_geometry.height() >= 136
        assert stage_geometry.bottom() < video_geometry.top()
        assert window.calibration_stage_badge.width() >= 92
        assert window.calibration_stage_progress.width() > 0
        window.start_dual_anchor_calibration()
        window.dual_calibration_timer.stop()
        app.processEvents()
        banner_geometry = window.calibration_camera_stage_banner.geometry()
        assert window.video_label.rect().contains(banner_geometry)
    finally:
        window.close()
        app.processEvents()
    print("test_debug_panel_places_stage_card_above_camera OK")


def test_debug_panel_keeps_legacy_single_frame_comparison() -> None:
    app = QApplication.instance() or QApplication([])
    backend = FakeDebugBackend()
    window = make_window(app, backend)
    try:
        window.update_frame()
        window.calibrate_current_sample()
        assert window.calibration_label.text().startswith("已校准（旧版调试）")
        assert window.analyzer.calibration_profile is None
        assert window.analyzer.legacy_calibration_used
        assert not window.analyzer.require_dual_anchor
    finally:
        window.close()
        app.processEvents()
    print("test_debug_panel_keeps_legacy_single_frame_comparison OK")


def test_debug_panel_reports_incomplete_dual_anchor_profile() -> None:
    app = QApplication.instance() or QApplication([])
    backend = FakeDebugBackend()
    window = make_window(app, backend)
    try:
        window.update_frame()
        window.start_dual_anchor_calibration()
        window.dual_calibration_timer.stop()
        for index in range(3):
            backend.sample = make_sample(T0 + timedelta(seconds=index * 0.2))
            window.update_frame()
        window.complete_preferred_stage(T0 + timedelta(seconds=5))
        window.finish_dual_anchor_calibration()
        assert window.analyzer.calibration_profile is None
        assert window.calibration_label.text().startswith("双锚点校准失败")
        assert "有效样本不足" in window.calibration_label.text()
        assert window._calibration_visual_phase == "failed"
        assert window.legacy_calibrate_button.isEnabled()
        assert window.precision_checkbox.isEnabled()
    finally:
        window.close()
        app.processEvents()
    print("test_debug_panel_reports_incomplete_dual_anchor_profile OK")


if __name__ == "__main__":
    test_debug_panel_runs_full_dual_anchor_calibration()
    test_debug_panel_places_stage_card_above_camera()
    test_debug_panel_keeps_legacy_single_frame_comparison()
    test_debug_panel_reports_incomplete_dual_anchor_profile()
    print("ALL TESTS PASSED")
