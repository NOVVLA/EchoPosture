"""全局 i18n 模块：覆盖所有面向用户的 UI 文本。

设计要点：
- 模块级单例，无 QObject 依赖（可在 QApplication 之前使用）。
- _t(key, **kwargs) 支持占位符格式化（用 str.format 语法，{name} 形式）。
- set_language(lang) 切换语言并通知所有注册的监听器。
- 监听器是普通的 callable，列表强引用；widget 销毁时调 remove_listener 清理。
- 默认语言 zh；当前为会话级切换（不落盘），不引入配置文件 / 注册表写入。

覆盖范围：
- tray_flyout.py（托盘浮窗）
- onboarding_toast.py（开场弹窗）
- tray_app.py（启动校准对话框、状态面板、托盘消息、警告弹窗）
- posture_console.py（调试控制台：椎骨功能名、工具提示、状态行）
- debug_ui.py（视觉调试 UI：状态码、原因码、标签、按钮、警告弹窗）
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

# ============================================================
# 翻译表
# ============================================================
_TEXTS: Dict[str, Dict[str, str]] = {
    "zh": {
        # ---- tray_flyout（保留原键名，向后兼容） ----
        "caption": "ECHOPOSTURE · 控制",
        "state_on": "监测运行中 · LIVE",
        "state_off": "已暂停 · STANDBY",
        "recalibrate": "立即重新校准",
        "max_effect": "立即测试最深效果",
        "exit": "退出本程序",
        "gear_tooltip": "打开配置界面",
        "lang_button": "语言：中文",
        # 三态按钮文案：循环顺序 zh → en → auto(跟随系统) → zh
        "lang_button_zh": "语言：中文",
        "lang_button_en": "语言：英文",
        "lang_button_auto_zh": "跟随系统 · 中文",
        "lang_button_auto_en": "跟随系统 · 英文",

        # ---- onboarding_toast（开场弹窗） ----
        "onb_accessible_name": "开启监测",
        "onb_state_off": "监测关闭 · STANDBY",
        "onb_state_on": "监测开启 · LIVE",
        "onb_caption": "ECHOPOSTURE · 系统提醒",
        "onb_title": "开启姿态监测？",
        "onb_body_1": "摄像头将以低功耗方式留意你的坐姿，",
        "onb_body_2": "所有数据仅在本机处理。",

        # ---- tray_app: StartupCalibrationDialog（启动校准对话框） ----
        "sd_caption": "ECHOPOSTURE · 启动校准",
        "sd_title": "请坐直，保持舒适姿态",
        "sd_body_1": "倒计时结束后，将自动用摄像头",
        "sd_body_2": "把当前姿势记为健康基准。",

        # ---- tray_app / posture_console: StatusPanel / SidePanel 共用状态标签 ----
        "sp_status": "当前状态：{status}",
        "sp_dim": "压暗程度：{dim}%",
        "sp_blur": "模糊程度：{blur}%",
        "sp_max_dim": "最深压暗：{v}%",
        "sp_blur_scale": "模糊强度：{v}%",

        # ---- tray_app: 托盘消息 ----
        "tm_worker_error": "监测已停止：{exc}",
        "tm_calib_ok": "校准完成，姿态监测已开始。",
        "tm_calib_fail_startup": "校准失败：没有识别到可用姿态。请重新启动并坐直。",
        "tm_recal_ok": "已按当前姿势重新校准。",
        "tm_recal_fail": "重新校准失败：没有识别到可用姿态。",
        "tm_max_effect": "已触发 8 秒最深压暗和模糊。",
        "tm_flyout_open_fail": "托盘浮窗打开失败，监测仍在运行：{exc}",
        "tm_console_open_fail": "控制台窗口打开失败，监测仍在运行：{exc}",

        # ---- tray_app / debug_ui: 警告弹窗（共用） ----
        "warn_camera_perm_title": "摄像头权限不可用",
        "warn_camera_perm_body": (
            "EchoPosture 无法打开摄像头。\n\n"
            "请在 Windows 设置 > 隐私和安全性 > 摄像头 中允许桌面应用访问摄像头，"
            "确认没有其他程序独占摄像头，然后重新启动 EchoPosture。\n\n"
            "详细信息：{detail}"
        ),
        "warn_camera_black_title": "摄像头画面不可用",
        "warn_camera_black_body": (
            "EchoPosture 已取得摄像头访问权限，但摄像头输出是全黑或几乎全黑，"
            "当前无法看清姿态。\n\n"
            "请检查镜头遮挡、隐私挡片、驱动禁用、虚拟摄像头输出或环境光线，然后重新启动监测。\n\n"
            "详细信息：{detail}"
        ),
        "warn_screen_capture_title": "屏幕捕获权限受限",
        "warn_screen_capture_body": (
            "EchoPosture 无法读取桌面画面用于 GPU 模糊，已切换到基础压暗 fallback。\n\n"
            "请检查屏幕捕获权限、显卡/远程桌面限制或安全软件拦截。\n\n"
            "详细信息：{detail}"
        ),

        # ---- posture_console: FeatureSpec 椎骨功能名 ----
        "feature.calib.cn": "启动校准",
        "feature.prec.cn": "高精度评分",
        "feature.perf.cn": "72FPS 采集",
        "feature.dim.cn": "压暗干预",
        "feature.blur.cn": "GPU 模糊",
        "feature.pres.cn": "离开/多人检测",
        "feature.ident.cn": "换人保护",

        # ---- posture_console: 工具提示 / 状态行 ----
        "console_verb_toggle": "点击切换",
        "console_verb_action": "点击触发",
        "console_verb_placeholder": "即将开放",
        "console_tooltip": "{cn}（{name}） — {verb}",
        "console_placeholder_suffix": "（即将开放）",
        "console_state_paused": "监测已暂停 · STANDBY",
        "console_hint": "监测开关在托盘浮窗 · 点击椎骨切换功能",
        "console_side_title": "CONTROL · 调节",
        "console_note_placeholder": "{name} {cn}：扩展占位，暂不可单独切换",
        "console_mods_suffix": " <span style='color:#5a5f66'>· 即将开放</span>",
        "console_state_active": "监测中 · {n} 项功能已启用",
        "console_state_waiting": "监测中 · 等待启用功能",

        # ---- debug_ui: STATUS_TEXT 状态码映射表 ----
        "status.GOOD": "正常",
        "status.GOOD_PART": "部分正常",
        "status.WATCH": "观察中",
        "status.BAD": "需要调整",
        "status.CRITICAL": "高风险",
        "status.AWAY": "已离开",
        "status.MULTI_USER": "多人",
        "status.PROFILE_MISMATCH": "疑似换人",
        "status.UNKNOWN": "未识别",
        "status.CALIBRATING": "校准中",
        "status.NEEDS_CALIB": "等待校准",

        # ---- debug_ui: REASON_TEXT 原因码映射表 ----
        "reason.press_calibrate": "请坐直后点击校准",
        "reason.within_baseline": "与基准姿势接近",
        "reason.too_close": "脸离屏幕过近",
        "reason.shoulder_tilt": "肩膀高度偏差较大",
        "reason.missing_face_or_pose": "脸部或肩膀未识别",
        "reason.no_usable_metrics": "暂时没有可用视觉指标",
        "reason.face_within_baseline": "脸部距离正常",
        "reason.shoulder_within_baseline": "肩膀高度正常",
        "reason.within_scientific_limits": "高精度指标在建议范围内",
        "reason.distance_calibration": "校准距离",
        "reason.distance_unreliable_head_turn": "转头时距离估算不可靠",
        "reason.head_turn": "头部转向",
        "reason.head_not_facing_camera": "头部未正对屏幕",
        "reason.head_turn_eye_width_ratio": "头部转向眼距比例",
        "reason.head_turn_ratio_delta": "头部转向偏移",
        "reason.multiple_faces_detected": "检测到多张脸",
        "reason.user_away_s": "用户离开秒数",
        "reason.user_missing_observing_s": "用户缺失观察秒数",
        "reason.profile_check_waiting": "等待用户轮廓校验",
        "reason.profile_face_shoulder_delta": "脸肩比例变化",
        "reason.profile_torso_shoulder_delta": "躯干肩宽比例变化",
        "reason.distance_too_close": "距离过近",
        "reason.distance_near": "距离偏近",
        "reason.distance_too_far": "距离过远",
        "reason.distance_far": "距离偏远",
        "reason.shoulder_asymmetry": "肩颈不对称",
        "reason.shoulder_width": "肩宽",
        "reason.shoulder_width_narrow": "肩宽明显缩窄",
        "reason.trunk_lean": "躯干倾斜",
        "reason.sustained_risk_s": "持续风险秒数",
        "reason.smoothed_risk_score": "平滑风险评分",
        "reason.risk_score": "风险评分",
        "reason.risk_observing": "风险观察中",

        # ---- debug_ui: _human_reason 替换片段 ----
        "reason_frag.missing": "缺失：",
        "reason_frag.face": "脸部",
        "reason_frag.shoulder": "肩膀",
        "reason_frag.trunk": "躯干",
        "reason_frag.distance": "距离",
        "reason_frag.baseline": "基准",

        # ---- debug_ui: 静态 QLabel / QPushButton / QCheckBox ----
        "debug_status_init": "等待校准",
        "debug_reason_init": "请坐直后点击校准",
        "debug_calib_init": "未校准",
        "debug_calibrate_btn": "校准当前姿势",
        "debug_precision_cb": "高精度模式（需要输入校准距离）",
        "debug_performance_cb": "高性能模式（72帧捕捉用于高流畅度）",
        "debug_panel_title": "视觉监听",
        "debug_metric_face": "脸部距离",
        "debug_metric_shoulder": "肩膀倾斜",
        "debug_metric_distance": "估算距离",
        "debug_metric_trunk": "躯干倾斜",
        "debug_metric_risk": "风险评分",
        "debug_metric_baseline": "当前基准",

        # ---- debug_ui: 动态 setText ----
        "debug_calib_no_sample": "还没有摄像头样本",
        "debug_calib_fail": "校准失败：没有识别到脸部或肩膀",
        "debug_calib_ok": "已校准：当前姿势已作为健康基准",

        # ---- debug_ui: 指标后缀 ----
        "debug_face_suffix": "{v}  越大越近",
        "debug_shoulder_suffix": "{v}  越大越歪",

        # ---- debug_ui: 启动失败弹窗（main 里） ----
        "debug_main_error": "Startup error",
    },
    "en": {
        # ---- tray_flyout ----
        "caption": "ECHOPOSTURE · CONTROL",
        "state_on": "Monitoring · LIVE",
        "state_off": "Paused · STANDBY",
        "recalibrate": "Recalibrate Now",
        "max_effect": "Test Max Effect",
        "exit": "Exit",
        "gear_tooltip": "Open Settings",
        "lang_button": "Language: English",
        # Three-state button text: cycle order zh → en → auto(system) → zh
        "lang_button_zh": "Language: Chinese",
        "lang_button_en": "Language: English",
        "lang_button_auto_zh": "Auto · Chinese",
        "lang_button_auto_en": "Auto · English",

        # ---- onboarding_toast ----
        "onb_accessible_name": "Enable Monitoring",
        "onb_state_off": "Monitoring Off · STANDBY",
        "onb_state_on": "Monitoring On · LIVE",
        "onb_caption": "ECHOPOSTURE · SYSTEM",
        "onb_title": "Enable Posture Monitoring?",
        "onb_body_1": "The camera will watch your posture at low power.",
        "onb_body_2": "All processing stays on this device.",

        # ---- tray_app: StartupCalibrationDialog ----
        "sd_caption": "ECHOPOSTURE · STARTUP CALIBRATION",
        "sd_title": "Sit upright, stay relaxed",
        "sd_body_1": "When the countdown ends,",
        "sd_body_2": "your posture becomes the baseline.",

        # ---- StatusPanel / SidePanel 共用 ----
        "sp_status": "Status: {status}",
        "sp_dim": "Dimming: {dim}%",
        "sp_blur": "Blur: {blur}%",
        "sp_max_dim": "Max dim: {v}%",
        "sp_blur_scale": "Blur strength: {v}%",

        # ---- tray_app: 托盘消息 ----
        "tm_worker_error": "Monitoring stopped: {exc}",
        "tm_calib_ok": "Calibration complete. Posture monitoring started.",
        "tm_calib_fail_startup": "Calibration failed: no usable posture detected. Please restart and sit upright.",
        "tm_recal_ok": "Re-calibrated to current posture.",
        "tm_recal_fail": "Re-calibration failed: no usable posture detected.",
        "tm_max_effect": "Triggered 8s of max dimming and blur.",
        "tm_flyout_open_fail": "Failed to open tray flyout; monitoring continues: {exc}",
        "tm_console_open_fail": "Failed to open console; monitoring continues: {exc}",

        # ---- 警告弹窗 ----
        "warn_camera_perm_title": "Camera Permission Unavailable",
        "warn_camera_perm_body": (
            "EchoPosture cannot open the camera.\n\n"
            "Please allow desktop apps to access the camera in "
            "Windows Settings > Privacy & security > Camera, "
            "make sure no other app is holding the camera, then restart EchoPosture.\n\n"
            "Details: {detail}"
        ),
        "warn_camera_black_title": "Camera Image Unavailable",
        "warn_camera_black_body": (
            "EchoPosture has camera access, but the camera output is fully black or nearly black. "
            "Posture cannot be read reliably.\n\n"
            "Check the lens cover, privacy shutter, disabled driver, virtual camera output, "
            "or ambient lighting, then restart monitoring.\n\n"
            "Details: {detail}"
        ),
        "warn_screen_capture_title": "Screen Capture Restricted",
        "warn_screen_capture_body": (
            "EchoPosture cannot read the desktop for GPU blur; "
            "switched to the basic dimming fallback.\n\n"
            "Check screen capture permission, GPU / remote desktop restrictions, "
            "or security software interception.\n\n"
            "Details: {detail}"
        ),

        # ---- posture_console: FeatureSpec 椎骨功能名 ----
        "feature.calib.cn": "Start Calibration",
        "feature.prec.cn": "High-Precision Score",
        "feature.perf.cn": "72FPS Capture",
        "feature.dim.cn": "Dimming Intervention",
        "feature.blur.cn": "GPU Blur",
        "feature.pres.cn": "Away / Multi-User",
        "feature.ident.cn": "Identity Protection",

        # ---- posture_console: 工具提示 / 状态行 ----
        "console_verb_toggle": "Click to toggle",
        "console_verb_action": "Click to trigger",
        "console_verb_placeholder": "Coming soon",
        "console_tooltip": "{cn} ({name}) — {verb}",
        "console_placeholder_suffix": " (coming soon)",
        "console_state_paused": "Monitoring Paused · STANDBY",
        "console_hint": "Toggle in tray flyout · Click vertebra to switch",
        "console_side_title": "CONTROL · ADJUST",
        "console_note_placeholder": "{name} {cn}: placeholder, cannot be toggled individually",
        "console_mods_suffix": " <span style='color:#5a5f66'>· coming soon</span>",
        "console_state_active": "Monitoring · {n} feature(s) active",
        "console_state_waiting": "Monitoring · waiting for features",

        # ---- debug_ui: STATUS_TEXT ----
        "status.GOOD": "Good",
        "status.GOOD_PART": "Partial",
        "status.WATCH": "Watching",
        "status.BAD": "Adjust needed",
        "status.CRITICAL": "High risk",
        "status.AWAY": "Away",
        "status.MULTI_USER": "Multi-user",
        "status.PROFILE_MISMATCH": "Profile mismatch",
        "status.UNKNOWN": "Unknown",
        "status.CALIBRATING": "Calibrating",
        "status.NEEDS_CALIB": "Needs calibration",

        # ---- debug_ui: REASON_TEXT ----
        "reason.press_calibrate": "Sit upright, then click calibrate",
        "reason.within_baseline": "Close to baseline posture",
        "reason.too_close": "Face too close to screen",
        "reason.shoulder_tilt": "Shoulder height offset is large",
        "reason.missing_face_or_pose": "Face or shoulders not detected",
        "reason.no_usable_metrics": "No usable visual metrics right now",
        "reason.face_within_baseline": "Face distance is normal",
        "reason.shoulder_within_baseline": "Shoulder height is normal",
        "reason.within_scientific_limits": "High-precision metrics within recommended range",
        "reason.distance_calibration": "Calibration distance",
        "reason.distance_unreliable_head_turn": "Distance estimate unreliable while head turned",
        "reason.head_turn": "Head turn",
        "reason.head_not_facing_camera": "Head not facing the screen",
        "reason.head_turn_eye_width_ratio": "Head turn eye-width ratio",
        "reason.head_turn_ratio_delta": "Head turn offset",
        "reason.multiple_faces_detected": "Multiple faces detected",
        "reason.user_away_s": "User away seconds",
        "reason.user_missing_observing_s": "User missing observed seconds",
        "reason.profile_check_waiting": "Waiting for profile check",
        "reason.profile_face_shoulder_delta": "Face-shoulder ratio change",
        "reason.profile_torso_shoulder_delta": "Torso-shoulder ratio change",
        "reason.distance_too_close": "Too close",
        "reason.distance_near": "Near",
        "reason.distance_too_far": "Too far",
        "reason.distance_far": "Far",
        "reason.shoulder_asymmetry": "Shoulder asymmetry",
        "reason.shoulder_width": "Shoulder width",
        "reason.shoulder_width_narrow": "Shoulder width clearly narrowed",
        "reason.trunk_lean": "Trunk lean",
        "reason.sustained_risk_s": "Sustained risk seconds",
        "reason.smoothed_risk_score": "Smoothed risk score",
        "reason.risk_score": "Risk score",
        "reason.risk_observing": "Risk observing",

        # ---- debug_ui: _human_reason 替换片段 ----
        "reason_frag.missing": "missing: ",
        "reason_frag.face": "face",
        "reason_frag.shoulder": "shoulder",
        "reason_frag.trunk": "trunk",
        "reason_frag.distance": "distance",
        "reason_frag.baseline": "baseline",

        # ---- debug_ui: 静态 UI ----
        "debug_status_init": "Waiting for calibration",
        "debug_reason_init": "Sit upright, then click calibrate",
        "debug_calib_init": "Not calibrated",
        "debug_calibrate_btn": "Calibrate Current Posture",
        "debug_precision_cb": "High-precision mode (requires calibration distance)",
        "debug_performance_cb": "High-performance mode (72fps capture for smoother motion)",
        "debug_panel_title": "Vision Monitor",
        "debug_metric_face": "Face distance",
        "debug_metric_shoulder": "Shoulder tilt",
        "debug_metric_distance": "Estimated distance",
        "debug_metric_trunk": "Trunk lean",
        "debug_metric_risk": "Risk score",
        "debug_metric_baseline": "Current baseline",

        # ---- debug_ui: 动态 setText ----
        "debug_calib_no_sample": "No camera sample yet",
        "debug_calib_fail": "Calibration failed: face or shoulders not detected",
        "debug_calib_ok": "Calibrated: current posture saved as healthy baseline",

        # ---- debug_ui: 指标后缀 ----
        "debug_face_suffix": "{v}  larger = closer",
        "debug_shoulder_suffix": "{v}  larger = more tilted",

        # ---- debug_ui: 启动失败弹窗 ----
        "debug_main_error": "Startup error",
    },
}

# ============================================================
# 状态 + 监听器
# ============================================================
_lang = "zh"
_listeners: list = []  # list of Callable[[], None]


def _detect_system_language() -> str:
    """检测系统语言，只返回 'zh' 或 'en'。

    优先级：
    1. Windows GetUserDefaultLocaleName / GetSystemDefaultUILanguage
    2. 环境变量 LANG / LANGUAGE（POSIX 风格，zh_CN.UTF-8 / en_US.UTF-8）
    3. 默认 'zh'（项目主语言）

    非侵入式：只读取系统 API，不写入任何用户配置。
    """
    # 1) Windows API：GetUserDefaultLocaleName 返回 "zh-CN" / "en-US" 等 BCP-47
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(85)
        # GetUserDefaultLocaleName(kernel32) → LOCALE_NAME
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
            loc = buf.value.lower()
            if loc.startswith("zh"):
                return "zh"
            if loc.startswith("en"):
                return "en"
    except Exception:
        pass

    # 2) POSIX 环境变量（非 Windows 时的兜底）
    import os
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        if not val:
            continue
        val_low = val.lower()
        if val_low.startswith("zh"):
            return "zh"
        if val_low.startswith("en"):
            return "en"

    # 3) 默认中文（项目主语言）
    return "zh"


# 模块加载时：默认跟随系统
_lang = _detect_system_language()


def _t(key: str, **kwargs) -> str:
    """查翻译。支持 {name} 占位符格式化。未知键返回 key 本身。"""
    table = _TEXTS.get(_lang, _TEXTS["zh"])
    text = table.get(key)
    if text is None:
        # 回退到 zh，再不行返回 key
        text = _TEXTS["zh"].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def set_language(lang: str) -> None:
    """切换语言并通知所有监听器。未知值忽略；同语言不重复通知。"""
    global _lang
    if lang not in _TEXTS:
        return
    if lang == _lang:
        return
    _lang = lang
    # 复制一份，避免遍历中监听器自己 add/remove 造成迭代问题
    for cb in list(_listeners):
        try:
            cb()
        except Exception:
            # 监听器出错不能影响其他监听器或主流程
            import traceback
            traceback.print_exc()


def current_language() -> str:
    return _lang


def available_languages() -> tuple:
    return tuple(_TEXTS.keys())


def add_listener(cb: Callable[[], None]) -> None:
    """注册语言变更监听器。重复 add 同一个 cb 不会重复注册。"""
    if cb not in _listeners:
        _listeners.append(cb)


def remove_listener(cb: Callable[[], None]) -> None:
    """移除监听器。widget 销毁时应调用以避免内存泄漏。"""
    try:
        _listeners.remove(cb)
    except ValueError:
        pass


def toggle_language() -> None:
    """在 zh / en 之间切换。"""
    set_language("en" if _lang == "zh" else "zh")


# 用户显式选择的语言；None 表示跟随系统。set_language(None) 重新走系统检测。
_user_override: Optional[str] = None


def set_auto_language() -> None:
    """切换到"跟随系统"模式：清空用户覆盖，重新走 _detect_system_language。

    如果检测到的系统语言与当前一致，不会重复通知监听器。
    """
    global _user_override
    _user_override = None
    detected = _detect_system_language()
    set_language(detected)


def cycle_language() -> str:
    """三态循环：zh → en → auto → zh。

    返回切换后的模式名（'zh' / 'en' / 'auto'），供按钮文案使用。
    auto 模式下，current_language() 仍返回实际生效的 'zh' 或 'en'，
    但按钮会显示"跟随系统"以提示用户。
    """
    global _user_override
    if _user_override is None:
        # 当前是 auto → 切到 zh
        _user_override = "zh"
        set_language("zh")
        return "zh"
    if _user_override == "zh":
        _user_override = "en"
        set_language("en")
        return "en"
    # 当前是 en → 切回 auto
    _user_override = None
    detected = _detect_system_language()
    set_language(detected)
    return "auto"


def current_mode() -> str:
    """返回当前模式：'auto' 表示跟随系统，'zh' / 'en' 表示用户显式选择。"""
    return _user_override if _user_override is not None else "auto"


def effective_language() -> str:
    """当前实际生效的语言（无论 auto 还是手动）。"""
    return _lang


def system_detected_language() -> str:
    """重新检测系统语言，不切换当前模式。用于 UI 显示"系统语言 = ?"。"""
    return _detect_system_language()


def lang_button_text() -> str:
    """根据当前模式 + 生效语言返回语言切换按钮的文案。

    - zh 显式模式：显示"语言：中文"（按当前生效语言本地化）
    - en 显式模式：显示"Language: English"
    - auto 模式 + 系统 zh：显示"跟随系统 · 中文"
    - auto 模式 + 系统 en：显示"Auto · English"

    即文案始终以"当前生效语言"呈现，并显示所选模式（手动选 zh/en vs 跟随系统）。
    """
    mode = current_mode()
    eff = _lang  # 当前实际生效的语言
    if mode == "auto":
        key = f"lang_button_auto_{eff}"
    else:
        key = f"lang_button_{mode}"
    return _t(key)
