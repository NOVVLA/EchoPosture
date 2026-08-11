"""Deterministic offscreen checks for the visual debug panel."""

from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt5.QtWidgets import QApplication

from debug_ui import DebugWindow
from vision_backend import observation_from_sample
from vision_test import VisionSample


T0 = datetime(2026, 1, 1, 12, 0, 0)


def make_sample() -> VisionSample:
    return VisionSample(
        timestamp=T0,
        interpupillary_px=60.0,
        shoulder_diff_px=4.0,
        signed_shoulder_diff_px=4.0,
        shoulder_width_px=220.0,
        trunk_lean_deg=2.0,
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
        right_shoulder_point=(420.0, 244.0),
        left_hip_point=(260.0, 390.0),
        right_hip_point=(380.0, 390.0),
        shoulder_center=(320.0, 242.0),
        hip_center=(320.0, 390.0),
        head_turn_ratio=0.02,
        torso_height_px=160.0,
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


def test_debug_panel_tracks_and_calibrates_target() -> None:
    app = QApplication.instance() or QApplication([])
    backend = FakeDebugBackend()
    window = DebugWindow(
        camera_id=0,
        fps=4.0,
        width=640,
        height=480,
        intervention_enabled=False,
        target_panel=True,
        backend_factory=lambda: backend,
    )
    try:
        window.update_frame()
        assert backend.started
        assert window.target_state_label.text() == "正在获取目标"
        assert window.target_track_label.text() == "--"
        assert window.target_count_label.text() == "1"
        assert window.current_sample is not None
        assert window.current_sample.target_state == "ACQUIRING"

        window.calibrate_current_sample()
        assert window.calibration_label.text().startswith("已校准")
        assert window.target_state_label.text() == "目标已锁定"
        assert window.target_track_label.text() == "1"
        assert window.target_count_label.text() == "1"
        assert window.current_sample is not None
        assert window.current_sample.target_track_id == 1
        assert window.current_sample.target_state == "TARGET_LOCKED"
    finally:
        window.close()
        app.processEvents()
        assert backend.closed
    print("test_debug_panel_tracks_and_calibrates_target OK")


if __name__ == "__main__":
    test_debug_panel_tracks_and_calibrates_target()
    print("ALL TESTS PASSED")
