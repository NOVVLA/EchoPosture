"""Mock VisionEngine：不依赖真实摄像头，生成稳定的"良好姿态"样本。

用途：
- 在没有摄像头或摄像头被占用时，让 tray_app / debug_ui 完整启动，
  验证所有 UI 文案、i18n 切换、控件交互，不被硬件阻塞。
- 生成的是"基准姿态"样本：脸肩对称、躯干直立、距离合适，
  这样校准会成功、监测会进入 GOOD 状态，所有 UI 都能展示。

接口对齐 VisionEngine 的最小集：
- start() / stop() / release()
- set_capture_fps(fps) / get_capture_fps()
- read_frame_sample() -> VisionSample
- read_sample() -> VisionSample（VisionWorker 调用入口）

不读取任何文件、不打开任何硬件，纯内存计算。
"""

from __future__ import annotations

import math
import random
import time
from datetime import datetime
from typing import Optional, Tuple

from vision_test import Point, VisionSample


class MockVisionEngine:
    """生成稳定良好姿态样本的 VisionEngine 替身。

    生成的样本几何关系：
    - 帧尺寸 640x480
    - 双眼中心 (270, 220) / (370, 220)，瞳距 100px
    - 鼻子 (320, 240)，与眼中线对齐 → 头部正向
    - 左肩 (220, 320) / 右肩 (420, 320)，对称
    - 左髋 (240, 420) / 右髋 (400, 420)，对称
    - 躯干直立，无倾斜

    加入小幅随机扰动（±2px）模拟真实采集抖动，避免数据完全静止。
    """

    FRAME_WIDTH = 640
    FRAME_HEIGHT = 480
    BASE_INTERPUPILLARY_PX = 100.0
    BASE_SHOULDER_WIDTH_PX = 200.0

    def __init__(
        self,
        camera_id: int = 0,
        width: int = 640,
        height: int = 480,
        min_detection_confidence: float = 0.6,
        min_tracking_confidence: float = 0.6,
    ) -> None:
        # 接口对齐 VisionEngine.__init__ 签名，参数仅作记录
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self._target_fps = 15.0
        self._started = False
        self._jitter_rng = random.Random(20260705)

    # ---- 生命周期 ----
    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def release(self) -> None:
        self._started = False

    def close(self) -> None:
        """接口对齐 VisionEngine.close()（部分代码路径会调用）。"""
        self._started = False

    # ---- FPS（接口对齐） ----
    def set_capture_fps(self, fps: float) -> None:
        if fps > 0:
            self._target_fps = float(fps)

    def get_capture_fps(self) -> float:
        return self._target_fps

    # ---- 帧读取（核心） ----
    def _make_sample(self) -> VisionSample:
        # 小幅抖动 ±2px，模拟真实采集
        j = lambda v: v + self._jitter_rng.uniform(-2.0, 2.0)

        left_eye: Point = (j(270.0), j(220.0))
        right_eye: Point = (j(370.0), j(220.0))
        face_nose: Point = (j(320.0), j(240.0))
        nose: Point = (j(320.0), j(250.0))

        left_shoulder: Point = (j(220.0), j(320.0))
        right_shoulder: Point = (j(420.0), j(320.0))
        shoulder_center: Point = (
            (left_shoulder[0] + right_shoulder[0]) / 2.0,
            (left_shoulder[1] + right_shoulder[1]) / 2.0,
        )

        left_hip: Point = (j(240.0), j(420.0))
        right_hip: Point = (j(400.0), j(420.0))
        hip_center: Point = (
            (left_hip[0] + right_hip[0]) / 2.0,
            (left_hip[1] + right_hip[1]) / 2.0,
        )

        interpupillary_px = math.dist(left_eye, right_eye)
        signed_shoulder_diff_px = left_shoulder[1] - right_shoulder[1]
        shoulder_diff_px = abs(signed_shoulder_diff_px)
        shoulder_width_px = math.dist(left_shoulder, right_shoulder)
        trunk_lean_deg = math.degrees(
            math.atan2(
                shoulder_center[0] - hip_center[0],
                hip_center[1] - shoulder_center[1],
            )
        )
        torso_height_px = math.dist(shoulder_center, hip_center)
        eye_mid_x = (left_eye[0] + right_eye[0]) / 2.0
        head_turn_ratio = (
            (face_nose[0] - eye_mid_x) / interpupillary_px
            if interpupillary_px > 0 else None
        )

        return VisionSample(
            timestamp=datetime.now(),
            interpupillary_px=interpupillary_px,
            shoulder_diff_px=shoulder_diff_px,
            signed_shoulder_diff_px=signed_shoulder_diff_px,
            shoulder_width_px=shoulder_width_px,
            trunk_lean_deg=trunk_lean_deg,
            face_detected=True,
            pose_detected=True,
            face_count=1,
            frame_width=self.FRAME_WIDTH,
            frame_height=self.FRAME_HEIGHT,
            left_eye_center=left_eye,
            right_eye_center=right_eye,
            nose_point=nose,
            left_shoulder_point=left_shoulder,
            right_shoulder_point=right_shoulder,
            shoulder_center=shoulder_center,
            left_hip_point=left_hip,
            right_hip_point=right_hip,
            hip_center=hip_center,
            face_nose_point=face_nose,
            head_turn_ratio=head_turn_ratio,
            torso_height_px=torso_height_px,
        )

    def read_frame_sample(self) -> VisionSample:
        if not self._started:
            raise RuntimeError("MockVisionEngine.start() must be called first.")
        return self._make_sample()

    def read_sample(self) -> VisionSample:
        """VisionWorker 调用入口，与 VisionEngine.read_sample 同名。"""
        return self.read_frame_sample()
