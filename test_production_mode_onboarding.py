"""Hardware-independent checks for production mode onboarding and selectors."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication

from mode_select_card import ModeSelectCard
from mode_themes import MODE_THEMES
from mode_wheel_selector import ModeWheelSelector, _SLOT_DEGREES
from onboarding_toast import OnboardingToast, TOAST_H, TOAST_W
from posture_console import PostureConsoleWindow
from user_settings import UserSettings, load_user_settings, save_user_settings
from vision_modes import (
    VISION_MODE_COMPATIBILITY,
    VISION_MODE_PROFESSIONAL_BETA,
    VISION_MODE_STANDARD,
    ModeAvailability,
    detect_mode_availability,
    probe_professional_support,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec_()


def _availability() -> dict[str, ModeAvailability]:
    return {
        VISION_MODE_COMPATIBILITY: ModeAvailability(True),
        VISION_MODE_STANDARD: ModeAvailability(True),
        VISION_MODE_PROFESSIONAL_BETA: ModeAvailability(
            False,
            "vision_mode_professional_unavailable",
        ),
    }


def _save_widget(widget, name: str) -> None:
    output = os.environ.get("ECHOPOSTURE_SCREENSHOT_DIR")
    if not output:
        return
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    assert widget.grab().save(str(target / name), "PNG")


class _FakeOverlay:
    max_dim_alpha = 0.32
    blur_scale = 1.0
    dim_level = 0.0
    blur_level = 0.0

    def set_visual_config(self, max_dim_alpha: float, blur_scale: float) -> None:
        self.max_dim_alpha = max_dim_alpha
        self.blur_scale = blur_scale


class _FakeEngine:
    def __init__(self) -> None:
        self.capture_fps = 72.0

    def get_capture_fps(self) -> float:
        return self.capture_fps

    def set_capture_fps(self, value: float) -> None:
        self.capture_fps = value


class _FakeAnalyzer:
    precision_enabled = True
    presence_check_enabled = True
    identity_check_enabled = True


class _FakeMonitor:
    def __init__(self) -> None:
        self.mode_availability = _availability()
        self.vision_mode = VISION_MODE_STANDARD
        self.vision_mode_switching = False
        self.user_settings = UserSettings(VISION_MODE_STANDARD, True)
        self.overlay = _FakeOverlay()
        self.engine = _FakeEngine()
        self.analyzer = _FakeAnalyzer()
        self.last_decision = None

    def is_monitoring(self) -> bool:
        return False

    def request_vision_mode(self, mode: str) -> bool:
        self.vision_mode = mode
        return True

    def set_ask_mode_on_startup(self, ask: bool) -> None:
        self.user_settings = UserSettings(self.vision_mode, ask)

    def trigger_max_visual_effect(self) -> None:
        pass

    def recalibrate_now(self) -> None:
        pass


def test_lightweight_availability_probe_uses_specs_without_importing() -> None:
    looked_up = []

    def fake_find_spec(name: str):
        looked_up.append(name)
        return object()

    with tempfile.TemporaryDirectory() as temporary:
        model = Path(temporary) / "pose.pt"
        model.write_bytes(b"test")
        started = time.perf_counter()
        result = detect_mode_availability(model_path=model, find_spec=fake_find_spec)
        elapsed_ms = (time.perf_counter() - started) * 1000.0

    # torch and ultralytics are each looked up once and shared by both tiers.
    assert looked_up == ["cv2", "mediapipe", "torch", "ultralytics"]
    assert result[VISION_MODE_COMPATIBILITY].available
    assert result[VISION_MODE_STANDARD].available
    # A spec object with no origin cannot prove a CUDA build exists.
    assert not result[VISION_MODE_PROFESSIONAL_BETA].available
    assert result[VISION_MODE_PROFESSIONAL_BETA].reason_key == "vision_mode_pro_unavailable_no_cuda_torch"
    assert elapsed_ms < 50.0


def _torch_spec(directory: Path, *, cuda: bool):
    """A stand-in torch spec whose lib/ folder decides the CUDA verdict."""
    torch_root = directory / "torch"
    (torch_root / "lib").mkdir(parents=True, exist_ok=True)
    if cuda:
        (torch_root / "lib" / "torch_cuda.dll").write_bytes(b"\x00")
    else:
        (torch_root / "lib" / "torch_cpu.dll").write_bytes(b"\x00")
    (torch_root / "__init__.py").write_text("", encoding="utf-8")
    return SimpleNamespace(origin=str(torch_root / "__init__.py"))


def test_professional_probe_names_the_specific_blocker() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        weight = root / "yolo26l-pose.pt"
        weight.write_bytes(b"test")

        # A CPU-only wheel is the most common blocker and must say so.
        cpu_only = probe_professional_support(_torch_spec(root / "cpu", cuda=False), model_path=weight)
        assert not cpu_only.available
        assert cpu_only.reason_key == "vision_mode_pro_unavailable_no_cuda_torch"

        # No torch at all reads the same way to the user.
        assert probe_professional_support(None).reason_key == "vision_mode_pro_unavailable_no_cuda_torch"

        cuda_spec = _torch_spec(root / "cuda", cuda=True)
        missing_weights = probe_professional_support(cuda_spec, model_path=root / "absent.pt")
        assert not missing_weights.available
        assert missing_weights.reason_key == "vision_mode_pro_unavailable_no_weights"

        ready = probe_professional_support(cuda_spec, model_path=weight)
        assert ready.available, "CUDA torch plus a local weight must offer the tier"
        assert ready.reason_key is None


def test_professional_probe_reports_a_missing_nvidia_driver() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        weight = root / "yolo26x-pose.pt"
        weight.write_bytes(b"test")
        spec = _torch_spec(root / "cuda", cuda=True)
        previous = os.environ.get("SystemRoot")
        # Point SystemRoot at a directory with no System32/nvml.dll.
        os.environ["SystemRoot"] = str(root / "fake-windows")
        try:
            result = probe_professional_support(spec, model_path=weight)
        finally:
            if previous is None:
                os.environ.pop("SystemRoot", None)
            else:
                os.environ["SystemRoot"] = previous
        assert not result.available
        assert result.reason_key == "vision_mode_pro_unavailable_no_driver"


def test_user_settings_store_only_mode_preferences() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "settings.json"
        settings = UserSettings(VISION_MODE_STANDARD, False)
        save_user_settings(settings, path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert set(payload) == {"version", "vision_mode", "ask_on_startup"}
        assert load_user_settings(path) == settings

        path.write_text('{"vision_mode":"unknown","ask_on_startup":false}', encoding="utf-8")
        assert load_user_settings(path) == UserSettings()


def test_mode_themes_are_complete_and_limited() -> None:
    assert set(MODE_THEMES) == {
        VISION_MODE_COMPATIBILITY,
        VISION_MODE_STANDARD,
        VISION_MODE_PROFESSIONAL_BETA,
    }
    for theme in MODE_THEMES.values():
        assert theme.accent.startswith("#")
        assert theme.duration_scale > 0
        assert theme.breathing_ms > 0


def test_onboarding_keeps_window_geometry_and_exposes_real_progress() -> None:
    app = _app()
    toast = OnboardingToast(_availability())
    selected = []
    toast.mode_selected.connect(selected.append)
    toast.show()
    app.processEvents()
    before = toast.geometry()
    _save_widget(toast, "onboarding-boot.png")

    toast._show_modes(auto_countdown=False)
    toast._set_reveal_progress(0.0)
    first_card = toast.mode_cards[VISION_MODE_COMPATIBILITY]
    first_card.show()
    app.processEvents()
    assert first_card.mapTo(toast, first_card.rect().topLeft()).y() == 91
    assert first_card.visibleRegion().boundingRect().top() > 0
    _wait(560)
    assert toast.geometry() == before
    assert toast.size().width() == TOAST_W
    assert toast.size().height() == TOAST_H
    assert all(card.isVisible() for card in toast.mode_cards.values())
    assert not toast.mode_cards[VISION_MODE_PROFESSIONAL_BETA].available
    _save_widget(toast, "onboarding-modes.png")

    toast._choose_mode(VISION_MODE_STANDARD)
    assert selected == [VISION_MODE_STANDARD]
    toast.set_loading_progress(35, "onb_mode_loading_import")
    _wait(280)
    assert toast._progress >= 35
    _save_widget(toast, "onboarding-standard-loading.png")
    toast.show_mode_failure("synthetic failure")
    assert toast._phase == "failed"
    assert toast._selected_mode == VISION_MODE_COMPATIBILITY
    toast.complete_mode(VISION_MODE_COMPATIBILITY)
    assert toast._progress == 100
    toast.close()
    app.processEvents()


def test_terminal_mode_failure_does_not_claim_a_working_fallback() -> None:
    app = _app()
    toast = OnboardingToast(_availability())
    try:
        toast._show_modes(auto_countdown=False)
        toast._choose_mode(VISION_MODE_COMPATIBILITY)
        toast.show_terminal_failure("camera unavailable")

        assert toast._phase == "failed"
        assert toast._selected_mode is None
        assert "camera unavailable" in toast._failure_detail
    finally:
        toast.close()
        app.processEvents()


def test_mode_cards_and_wheel_render_and_cycle_over_available_modes() -> None:
    app = _app()
    card = ModeSelectCard(VISION_MODE_STANDARD)
    card.set_selected(True)
    card.show()
    app.processEvents()
    card_image = card.grab().toImage()
    assert not card_image.isNull()
    assert any(
        card_image.pixelColor(x, y).alpha() > 0
        for x in range(0, card_image.width(), 12)
        for y in range(0, card_image.height(), 8)
    )

    wheel = ModeWheelSelector(_availability(), VISION_MODE_COMPATIBILITY)
    requested = []
    wheel.mode_requested.connect(requested.append)
    wheel.show()
    app.processEvents()
    wheel_image = wheel.grab().toImage()
    assert not wheel_image.isNull()
    assert any(
        wheel_image.pixelColor(x, y).alpha() > 0
        for x in range(0, wheel_image.width(), 16)
        for y in range(0, wheel_image.height(), 8)
    )
    _save_widget(wheel, "wheel-settled.png")

    # Mid-rotation the disc must render a different frame than at rest; a static
    # arc of cards would look identical no matter the angle.
    resting = wheel.grab().toImage()
    wheel._set_wheel_angle(wheel._wheel_angle - _SLOT_DEGREES * 0.45)
    app.processEvents()
    turning = wheel.grab().toImage()
    assert turning != resting, "the wheel must repaint as it rotates"
    _save_widget(wheel, "wheel-turning.png")
    wheel._set_wheel_angle(wheel._wheel_angle + _SLOT_DEGREES * 0.45)
    app.processEvents()

    wheel._request_neighbor(1)
    _wait(520)
    assert requested == [VISION_MODE_STANDARD]
    # The disc really turned: one slot of rotation per mode step.
    assert abs(wheel._wheel_angle + _SLOT_DEGREES) < 0.01
    wheel.set_busy(False)
    wheel.set_current_mode(VISION_MODE_STANDARD)
    wheel._request_neighbor(1)
    _wait(720)
    assert requested[-1] == VISION_MODE_COMPATIBILITY
    card.close()
    wheel.close()
    app.processEvents()


def test_full_console_renders_without_wheel_overlap_at_common_desktop_sizes() -> None:
    app = _app()
    window = PostureConsoleWindow(_FakeMonitor())
    window.show()
    app.processEvents()
    if window._entrance_group is not None:
        window._entrance_group.stop()
    for animation in window._anim_keep:
        animation.stop()
    window.setWindowOpacity(1.0)
    window.blueprint.setOpacity(0.9)
    window.eye.setOpacity(1.0)
    for item in getattr(window, "_label_items", []):
        item.setOpacity(1.0)
    for item in window.vertebrae:
        item.setOpacity(1.0)

    # Golden-ratio window sizes produced on 1366x768 and 1920x1080 work areas.
    for width, height, label in ((696, 475, "1366x768"), (978, 667, "1920x1080")):
        window.resize(width, height)
        app.processEvents()
        window.view._place_overlays()
        viewport = window.view.viewport()
        wheel_rect = window.mode_wheel.geometry()
        side_rect = window.side.geometry()
        assert wheel_rect.right() < side_rect.left()
        assert wheel_rect.bottom() <= viewport.height() + 2
        assert window.view.readout_mods.geometry().bottom() < wheel_rect.top()
        assert not window.view.hint.isVisible()
        image = window.grab().toImage()
        assert not image.isNull()
        assert any(
            image.pixelColor(x, y).value() > 10
            for x in range(0, image.width(), 24)
            for y in range(0, image.height(), 24)
        )
        _save_widget(window, f"console-{label}.png")

    window.close()
    app.processEvents()


def test_available_professional_tier_is_selectable_in_both_selectors() -> None:
    app = _app()
    available = {
        VISION_MODE_COMPATIBILITY: ModeAvailability(True),
        VISION_MODE_STANDARD: ModeAvailability(True),
        VISION_MODE_PROFESSIONAL_BETA: ModeAvailability(True),
    }

    card = ModeSelectCard(VISION_MODE_PROFESSIONAL_BETA, available=True)
    activated = []
    refused = []
    card.activated.connect(activated.append)
    card.unavailable_requested.connect(lambda mode, reason: refused.append(mode))
    card.show()
    app.processEvents()
    card._activate()
    app.processEvents()
    assert activated == [VISION_MODE_PROFESSIONAL_BETA], "an available Beta tier must be selectable"
    assert refused == [], "an available tier must not shake or report a blocker"
    card.close()

    wheel = ModeWheelSelector(available, VISION_MODE_STANDARD)
    requested = []
    wheel.mode_requested.connect(requested.append)
    wheel.show()
    app.processEvents()
    wheel._request_neighbor(1)
    _wait(520)
    assert requested == [VISION_MODE_PROFESSIONAL_BETA], "the wheel must stop on the now-usable tier"
    wheel.close()
    app.processEvents()

    wheel = ModeWheelSelector(available, VISION_MODE_STANDARD)
    requested = []
    wheel.mode_requested.connect(requested.append)
    wheel.show()
    app.processEvents()
    wheel._request_neighbor(1)
    _wait(520)
    assert requested == [VISION_MODE_PROFESSIONAL_BETA], "the wheel must stop on the now-usable tier"
    wheel.close()
    app.processEvents()


def main() -> int:
    test_lightweight_availability_probe_uses_specs_without_importing()
    test_professional_probe_names_the_specific_blocker()
    test_professional_probe_reports_a_missing_nvidia_driver()
    test_user_settings_store_only_mode_preferences()
    test_mode_themes_are_complete_and_limited()
    test_onboarding_keeps_window_geometry_and_exposes_real_progress()
    test_terminal_mode_failure_does_not_claim_a_working_fallback()
    test_mode_cards_and_wheel_render_and_cycle_over_available_modes()
    test_available_professional_tier_is_selectable_in_both_selectors()
    test_full_console_renders_without_wheel_overlap_at_common_desktop_sizes()
    print("test_production_mode_onboarding OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
