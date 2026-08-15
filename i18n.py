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
        "onb_mode_title": "选择监测模式",
        "onb_mode_sub": "可随时在设置里更改",
        "onb_mode_badge_recommended": "推荐",
        "onb_mode_badge_beta": "Beta",
        "onb_mode_badge_unavailable": "不可用",
        "onb_mode_compat_desc": "适配老设备 · 单人场景",
        "onb_mode_standard_desc": "多人场景更稳 · 需要较新的 CPU",
        "onb_mode_pro_desc": "最高精度 · 需要独立显卡",
        "onb_mode_loading": "正在准备模型",
        "onb_mode_loading_import": "正在载入姿态模块",
        "onb_mode_loading_model": "模型已载入，正在预热",
        "onb_mode_loading_camera": "正在连接摄像头",
        "onb_mode_loading_slow": "首次启动较慢，正在加载模型",
        "onb_mode_failed_fallback": "该模式启动失败，已回退到兼容模式：{detail}",
        "onb_mode_failed_terminal": "监测启动失败：{detail}",
        "onb_mode_autoselect": "{seconds} 秒后自动使用{mode}",
        "onb_mode_persisted_hint": "当前为{mode}，可在设置里更改",
        "onb_mode_ready": "{mode}已就绪",

        # ---- tray_app: StartupCalibrationDialog（启动校准对话框） ----
        "sd_caption": "ECHOPOSTURE · 个人双锚点校准",
        "sd_title": "保持希望长期采用的舒适坐姿",
        "sd_body_1": "完整 5 秒倒计时只测量当前舒适坐姿",
        "sd_body_2": "倒计时结束并收到提示后再自然放松；全程保持单人。",

        # ---- tray_app / posture_console: StatusPanel / SidePanel 共用状态标签 ----
        "sp_status": "当前状态：{status}",
        "sp_dim": "压暗程度：{dim}%",
        "sp_blur": "模糊程度：{blur}%",
        "sp_max_dim": "最深压暗：{v}%",
        "sp_blur_scale": "模糊强度：{v}%",

        # ---- tray_app: 托盘消息 ----
        "tm_worker_error": "监测已停止：{exc}",
        "tm_calib_relax_now": "舒适坐姿测量完成，现在可以自然放松。后台将测量约 5 秒，请保持自然放松直到完成。",
        "tm_calib_extending": "放松姿势样本还不够，正在多花几秒继续采集，请稍候……",
        "tm_calib_ok": "双锚点采集完成，正在复验个人正常姿态范围；复验期间不累计静态暴露。",
        "tm_calib_fail_startup": "校准失败：{details}。请正对摄像头，并保持画面中只有一个人。",
        "tm_recal_ok": "双锚点重新采集完成，正在复验个人正常姿态范围。",
        "tm_recal_fail": "重新校准失败：{details}。",
        "calib_missing_unknown": "未获得完整的单人姿态样本",
        "calib_missing_complete_sample": "未获得完整的单人姿态样本",
        "calib_missing_preferred_samples": "5 秒舒适坐姿阶段的有效样本不足 5 个",
        "calib_missing_relaxed_samples": "后台放松姿势阶段（含有限延长）的有效样本不足 5 个",
        "calib_missing_face_quality_low": "面部测量质量不足",
        "calib_missing_pose_quality_low": "身体关键点质量不足",
        "calib_missing_target_moving": "校准期间身体移动过大",
        "calib_missing_target_uncertain": "校准目标暂时不确定",
        "calib_missing_target_ambiguous": "校准目标存在歧义",
        "calib_missing_keypoints_missing": "校准期间关键点缺失",
        "calib_missing_no_posture_features": "没有可用的姿态特征（请让肩膀和躯干完整出现在画面中）",
        "calib_missing_no_common_posture_features": "两个阶段没有共同且足量的可用姿态特征",
        "calib_missing_single_person": "需要单人画面",
        "calib_missing_face_detected": "未检测到脸部",
        "calib_missing_pose_detected": "未检测到姿态",
        "calib_missing_interpupillary_px": "缺少瞳距指标",
        "calib_missing_signed_shoulder_diff_px": "缺少肩膀高度指标",
        "calib_missing_shoulder_width_px": "缺少肩宽指标",
        "calib_missing_trunk_lean_deg": "缺少躯干倾斜指标",
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
        "feature.prec.cn": "个人姿态偏离",
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
        "console_mode_ask_startup": "启动时询问监测模式",
        "console_mode_switching": "正在切换模式",
        "console_mode_selector": "监测模式",
        "console_mode_compat_short": "兼容",
        "console_mode_standard_short": "标准",
        "console_mode_professional_short": "专业 Beta",
        "console_note_placeholder": "{name} {cn}：扩展占位，暂不可单独切换",
        "console_mods_suffix": " <span style='color:#5a5f66'>· 即将开放</span>",
        "console_state_active": "监测中 · {n} 项功能已启用",
        "console_state_waiting": "监测中 · 等待启用功能",

        # ---- debug_ui: STATUS_TEXT 状态码映射表 ----
        "status.GOOD": "正常",
        "status.GOOD_PART": "部分正常",
        "status.MOVING": "活动中",
        "status.ADJUSTING": "姿态调整中",
        "status.OBSERVING": "测量观察中",
        "status.WATCH": "检测到姿态偏离",
        "status.BAD": "静态暴露提醒",
        "status.CRITICAL": "静态暴露较高",
        "status.AWAY": "已离开",
        "status.MULTI_USER": "多人",
        "status.ACQUIRING": "正在获取目标",
        "status.TARGET_LOCKED": "目标已锁定",
        "status.MULTI_PRESENT": "多人，目标保持",
        "status.TARGET_OCCLUDED": "目标关键点暂时缺失",
        "status.TARGET_REACQUIRING": "正在重新匹配人体轨迹",
        "status.IDENTITY_UNCERTAIN": "目标身份待确认",
        "status.TARGET_AMBIGUOUS": "目标归属不明确",
        "status.PROFILE_MISMATCH": "疑似换人",
        "status.UNKNOWN": "未识别",
        "status.CALIBRATING": "校准中",
        "status.NEEDS_CALIB": "等待校准",
        "status.WAITING": "等待监测",

        # ---- debug_ui: REASON_TEXT 原因码映射表 ----
        "reason.press_calibrate": "请坐直后点击校准",
        "reason.within_baseline": "接近个人锚点（legacy）",
        "reason.too_close": "脸离屏幕过近",
        "reason.shoulder_tilt": "肩膀高度偏差较大",
        "reason.missing_face_or_pose": "脸部或肩膀未识别",
        "reason.no_usable_metrics": "暂时没有可用视觉指标",
        "reason.face_within_baseline": "脸部距离正常",
        "reason.shoulder_within_baseline": "肩膀高度正常",
        "reason.within_scientific_limits": "个人姿态偏离在观察范围内",
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
        "reason.distance_too_close": "距离过近",
        "reason.distance_near": "距离偏近",
        "reason.distance_too_far": "距离过远",
        "reason.distance_far": "距离偏远",
        "reason.shoulder_asymmetry": "肩颈不对称",
        "reason.shoulder_width": "肩宽",
        "reason.shoulder_width_narrow": "肩宽明显缩窄",
        "reason.trunk_lean": "躯干倾斜",
        "reason.sustained_risk_s": "持续风险秒数",
        "reason.smoothed_risk_score": "legacy 平滑分数",
        "reason.risk_score": "legacy 分数（兼容别名）",
        "reason.risk_observing": "风险观察中",
        "reason.target_not_locked": "尚未锁定目标",
        "reason.target_observed": "已观察到目标",
        "reason.target_occluded": "目标关键点暂时缺失",
        "reason.target_reacquiring": "正在重新匹配人体轨迹",
        "reason.target_missing_observing_s": "目标缺失观察秒数",
        "reason.target_missing_candidate_present": "检测到候选轨迹，正在确认是否为原目标",
        "reason.target_missing_s": "目标缺失秒数",
        "reason.target_away_s": "目标离开秒数",
        "reason.ambiguous_face_body_association": "脸部与身体归属不明确",
        "reason.target_face_body_association_ambiguous": "目标脸身归属不明确",
        "reason.target_geometry_association_ambiguous": "目标几何关联不明确",
        "reason.association_budget_exceeded": "画面人数超出安全关联预算，已暂停目标选择",
        "reason.reacquired_candidate_needs_identity_confirmation": "重新出现的候选目标需确认",
        "reason.reacquired_candidate_identity_mismatch": "重新出现的候选目标人脸身份不匹配",
        "reason.other_track_present": "检测到其他轨迹",
        "reason.multi_present_observing": "多人状态观察中",
        "reason.multi_exit_stabilizing_s": "多人退出稳定秒数",
        "reason.target_presence_check_disabled": "在场检测已关闭，目标状态仅内部跟踪",
        "reason.dual_anchor_calibration_required": "需要完成双锚点校准",
        "reason.dual_anchor_calibration_collecting": "正在采集双锚点校准样本",
        "reason.activity_moving_exposure_paused": "检测到活动，静态暴露暂停累计",
        "reason.posture_adjustment_exposure_paused": "正在探身或调整姿势，不进行姿态观察和静态暴露累计",
        "reason.minor_posture_variation": "正常的小幅姿态变化，不累计静态暴露",
        "reason.camera_drift_recalibration_required": "镜头位置可能变化，需要重新校准",
        "reason.camera_roll_measurement_abstained": "画面参考方向发生变化，静态暴露暂停累计",
        "reason.camera_scale_jump_measurement_abstained": "距离或整体尺度正在变化，静态暴露暂停累计",
        "reason.head_turn_measurement_abstained": "正在转头，静态暴露暂停累计",
        "reason.sustained_head_direction": "持续大幅转头",
        "reason.head_direction_quality_low": "头部方向信号质量不足",
        "reason.head_direction_delta": "个人头部方向偏离",
        "reason.shared_shoulder_scale_measurement_abstained": "肩部测量尺度发生变化，静态暴露暂停累计",
        "reason.posture_features_unavailable": "当前没有足够的姿态变化指标",
        "reason.posture_evidence_inconclusive": "仅有单项姿态特征变化，静态暴露暂停累计",
        "reason.post_calibration_normal_range_validation": "校准完成，正在确认目标锁定后的测量范围",
        "reason.post_calibration_normal_range_validated": "个人正常姿态范围复验完成",
        "reason.measurement_quality_low": "当前可用姿态证据较少，静态暴露暂停累计",
        "reason.within_personal_posture_range": "处于个人双锚点正常姿态范围",
        "reason.posture_deviation": "个人姿态偏离",
        "reason.exposure_seconds": "等效静态暴露秒数",
        "reason.confidence": "测量置信度",
        "reason.static_hold_seconds": "低轨迹活动时长",
        "reason.static_hold_bonus": "低轨迹活动加成（有上限，不等于姿态异常）",

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
        "debug_dual_calibrate_btn": "开始完整双锚点校准",
        "debug_dual_cancel_btn": "取消双锚点校准",
        "debug_calibrate_btn": "旧版单帧校准（仅调试）",
        "debug_precision_cb": "个人姿态偏离（生产需要双锚点）",
        "debug_performance_cb": "高性能模式（72帧捕捉用于高流畅度）",
        "debug_panel_title": "视觉监听",
        "debug_metric_face": "脸部距离",
        "debug_metric_shoulder": "肩膀倾斜",
        "debug_metric_distance": "估算距离",
        "debug_metric_trunk": "躯干倾斜",
        "debug_metric_projected_trunk_axis": "躯干二维投影轴",
        "debug_metric_projected_head_trunk": "头躯干二维夹角",
        "debug_metric_risk": "姿态偏离 / 综合风险 / 暴露 / 置信度",
        "debug_metric_baseline": "当前锚点",
        "debug_target_title": "P3/P4 目标追踪",
        "debug_target_state": "目标状态",
        "debug_target_track": "锁定轨迹",
        "debug_target_count": "当前人数",
        "debug_target_score": "关联分数",
        "debug_target_motion": "目标运动速率",
        "debug_target_activity": "活动判定",
        "debug_target_reason": "状态原因",
        "debug_target_calib_fail": "校准失败：需要唯一且明确的目标轨迹",
        "debug_vision_mode": "视觉模式",
        "debug_vision_backend": "当前后端：{mode} · {backend}",
        "debug_vision_backend_notice": "{current}\n提示：{notice}",
        "debug_activity_STATIC": "静止",
        "debug_activity_MOVING": "活动中",
        "debug_activity_UNKNOWN": "未知",
        "vision_mode_compatibility": "兼容模式",
        "vision_mode_standard": "标准模式",
        "vision_mode_professional_beta": "专业模式 Beta",
        "vision_mode_compatibility_unavailable": "兼容模式不可用：缺少 MediaPipe 或 OpenCV 运行依赖。",
        "vision_mode_standard_unavailable": "标准模式不可用：缺少本地 YOLO26n-pose 权重或标准模式依赖。",
        "vision_mode_professional_unavailable": "专业模式 Beta 不可用：尚未提供 TensorRT 姿态后端。",
        "vision_mode_switch_failed": "模式切换失败，已恢复原后端：{detail}",
        "vision_compat_face_detector_fallback": (
            "BlazeFace 人脸检测不可用；当前仅使用 FaceMesh 降级路径，"
            "多脸计数和人脸框可靠性会降低。原因：{detail}"
        ),

        # ---- debug_ui: 动态 setText ----
        "debug_calib_no_sample": "还没有摄像头样本",
        "debug_calib_fail": "校准失败：没有识别到脸部或肩膀",
        "debug_calib_ok": "已校准（旧版调试）：单帧结果不代表科学校准通过",
        "debug_dual_calib_started": "舒适坐姿测量已开始：完整保持 5 秒，收到提示后再放松。",
        "debug_dual_calib_preferred": "舒适坐姿阶段：有效样本 {preferred}/5；放松阶段 {relaxed}/5。{detail}",
        "debug_dual_calib_relax_now": "舒适坐姿阶段完成，现在可以自然放松；约 1 秒过渡期间不采样。",
        "debug_dual_calib_transition": "正在等待姿势稳定：舒适坐姿 {preferred}/5；放松 {relaxed}/5。过渡样本已忽略。",
        "debug_dual_calib_relaxed": "自然放松阶段：舒适坐姿 {preferred}/5；有效样本 {relaxed}/5。{detail}",
        "debug_dual_calib_extending": "放松测量正在有限延长：舒适坐姿 {preferred}/5；有效样本 {relaxed}/5。{detail}",
        "debug_dual_calib_accepting": "当前样本有效",
        "debug_dual_calib_failed": "双锚点校准失败：{detail}",
        "debug_dual_calib_ok": "双锚点科学校准完成：舒适 {preferred} 帧，放松 {relaxed} 帧，质量 {quality:.2f}，启用特征 {features} 项。",
        "debug_dual_calib_cancelled": "已取消双锚点校准，未更改当前锚点。",
        "debug_dual_calib_active": "双锚点校准完成，正式监测已经激活。",
        "debug_stage_idle_title": "校准未运行 · IDLE",
        "debug_stage_idle_detail": "完整双锚点按钮会依次测试坐直、过渡、自然放松和监测激活。",
        "debug_stage_badge_idle": "--",
        "debug_stage_badge_preferred": "1/2",
        "debug_stage_badge_transition": "放松",
        "debug_stage_badge_relaxed": "2/2",
        "debug_stage_badge_active": "监测",
        "debug_stage_badge_validating": "复验",
        "debug_stage_badge_failed": "重试",
        "debug_stage_preferred_title": "第一段 · 现在坐直",
        "debug_stage_preferred_detail": "保持你认可的正确舒适坐姿整整 5 秒。此刻不要放松；绿色画面只记录坐直姿势。",
        "debug_stage_transition_title": "动作切换 · 现在放松",
        "debug_stage_transition_detail": "坐直姿势已经记录。现在自然放松；橙色过渡约 1 秒不采样，画面变成紫色后才开始记录放松姿势。",
        "debug_stage_camera_relax_prompt": "坐直姿势记录完成\n请现在自然放松\n紫色出现后开始第二段采样",
        "debug_stage_relaxed_title": "第二段 · 保持自然放松",
        "debug_stage_relaxed_detail": "紫色画面正在静默记录自然放松姿势。没有第二次倒计时，请保持放松直到校准完成。",
        "debug_stage_active_title": "双锚点就绪 · 正式监测中",
        "debug_stage_active_detail": "两个锚点及其区间属于个人正常范围；只有越过测量噪声带和自然动作余量的持续偏离才累计。",
        "debug_stage_validating_title": "双锚点已采集 · 正在复验正常范围",
        "debug_stage_validating_detail": "保持当前稳定姿势约 2 秒；确认目标锁定后的测量仍落在个人正常范围内，期间不累计静态暴露。",
        "debug_stage_failed_title": "双锚点校准失败",
        "debug_stage_failed_detail": "校准失败；具体原因会直接显示在这里。",
        "debug_stage_failed_reason": "原因：{detail}（坐直 {preferred}/{minimum}，放松 {relaxed}/{minimum}）",
        "debug_stage_camera_preferred_banner": "第 1 段 / 2\n现在坐直 · 不要放松\n绿色画面正在记录正确舒适坐姿",
        "debug_stage_camera_transition_banner": "停止坐直 · 现在放松\n橙色过渡不采样\n等待画面变为紫色",
        "debug_stage_camera_relaxed_banner": "第 2 段 / 2\n现在保持自然放松\n紫色画面正在静默记录放松姿势",
        "debug_stage_rail_preferred_active": "1  坐直中",
        "debug_stage_rail_preferred_done": "1  坐直完成",
        "debug_stage_rail_relaxed_next": "2  放松（随后）",
        "debug_stage_rail_relaxed_now": "2  现在放松",
        "debug_stage_rail_relaxed_active": "2  放松采集中",

        # ---- debug_ui: 指标后缀 ----
        "debug_face_suffix": "{v}  越大越近",
        "debug_face_not_used_standard": "当前帧未获得可用人脸测量",
        "vision_identity_model_unavailable": "人脸身份模型不可用：{detail}",
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
        "onb_mode_title": "Choose a monitoring mode",
        "onb_mode_sub": "You can change this later in settings",
        "onb_mode_badge_recommended": "Recommended",
        "onb_mode_badge_beta": "Beta",
        "onb_mode_badge_unavailable": "Unavailable",
        "onb_mode_compat_desc": "For older devices · Single-person scenes",
        "onb_mode_standard_desc": "More stable with groups · Newer CPU",
        "onb_mode_pro_desc": "Highest precision · Discrete GPU required",
        "onb_mode_loading": "Preparing the model",
        "onb_mode_loading_import": "Loading the posture module",
        "onb_mode_loading_model": "Model loaded · Warming up",
        "onb_mode_loading_camera": "Connecting to the camera",
        "onb_mode_loading_slow": "First launch is slower while the model loads",
        "onb_mode_failed_fallback": "This mode failed to start and fell back to Compatibility: {detail}",
        "onb_mode_failed_terminal": "Monitoring failed to start: {detail}",
        "onb_mode_autoselect": "Using {mode} automatically in {seconds}s",
        "onb_mode_persisted_hint": "Current mode: {mode}. Change it in settings.",
        "onb_mode_ready": "{mode} is ready",

        # ---- tray_app: StartupCalibrationDialog ----
        "sd_caption": "ECHOPOSTURE · PERSONAL TWO-ANCHOR CALIBRATION",
        "sd_title": "Hold your preferred comfortable posture",
        "sd_body_1": "The full 5-second countdown measures only this posture",
        "sd_body_2": "Relax only after the countdown and prompt; stay alone in view.",

        # ---- StatusPanel / SidePanel 共用 ----
        "sp_status": "Status: {status}",
        "sp_dim": "Dimming: {dim}%",
        "sp_blur": "Blur: {blur}%",
        "sp_max_dim": "Max dim: {v}%",
        "sp_blur_scale": "Blur strength: {v}%",

        # ---- tray_app: 托盘消息 ----
        "tm_worker_error": "Monitoring stopped: {exc}",
        "tm_calib_relax_now": "Preferred-posture measurement is complete. Relax naturally now; background measurement continues for about 5 seconds, so remain relaxed until completion.",
        "tm_calib_extending": "Still gathering a few more relaxed-posture samples, please hold on a moment longer…",
        "tm_calib_ok": "Two-anchor collection is complete. EchoPosture is validating your personal normal range; static exposure remains paused during this check.",
        "tm_calib_fail_startup": "Calibration failed: {details}. Face the camera and keep only one person in view.",
        "tm_recal_ok": "Two-anchor re-calibration collected; validating the personal normal range.",
        "tm_recal_fail": "Re-calibration failed: {details}.",
        "calib_missing_unknown": "no complete single-person posture sample",
        "calib_missing_complete_sample": "no complete single-person posture sample",
        "calib_missing_preferred_samples": "fewer than 5 valid samples in the 5-second preferred-posture stage",
        "calib_missing_relaxed_samples": "fewer than 5 valid samples in the background relaxed stage, including its bounded extension",
        "calib_missing_face_quality_low": "face measurement quality was too low",
        "calib_missing_pose_quality_low": "body keypoint quality was too low",
        "calib_missing_target_moving": "body motion was too high during calibration",
        "calib_missing_target_uncertain": "the calibration target was temporarily uncertain",
        "calib_missing_target_ambiguous": "the calibration target was ambiguous",
        "calib_missing_keypoints_missing": "required keypoints were missing during calibration",
        "calib_missing_no_posture_features": "no usable posture features were available",
        "calib_missing_no_common_posture_features": "no posture feature had enough valid samples in both stages",
        "calib_missing_single_person": "single-person view required",
        "calib_missing_face_detected": "face not detected",
        "calib_missing_pose_detected": "pose not detected",
        "calib_missing_interpupillary_px": "interpupillary metric missing",
        "calib_missing_signed_shoulder_diff_px": "shoulder-height metric missing",
        "calib_missing_shoulder_width_px": "shoulder-width metric missing",
        "calib_missing_trunk_lean_deg": "trunk-lean metric missing",
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
        "feature.prec.cn": "Personal Posture Deviation",
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
        "console_mode_ask_startup": "Ask for monitoring mode at startup",
        "console_mode_switching": "Switching mode",
        "console_mode_selector": "Monitoring mode",
        "console_mode_compat_short": "Compat",
        "console_mode_standard_short": "Standard",
        "console_mode_professional_short": "Pro Beta",
        "console_note_placeholder": "{name} {cn}: placeholder, cannot be toggled individually",
        "console_mods_suffix": " <span style='color:#5a5f66'>· coming soon</span>",
        "console_state_active": "Monitoring · {n} feature(s) active",
        "console_state_waiting": "Monitoring · waiting for features",

        # ---- debug_ui: STATUS_TEXT ----
        "status.GOOD": "Good",
        "status.GOOD_PART": "Partial",
        "status.MOVING": "Moving",
        "status.ADJUSTING": "Posture adjusting",
        "status.OBSERVING": "Measurement observing",
        "status.WATCH": "Posture deviation detected",
        "status.BAD": "Static exposure reminder",
        "status.CRITICAL": "High static exposure",
        "status.AWAY": "Away",
        "status.MULTI_USER": "Multi-user",
        "status.ACQUIRING": "Acquiring target",
        "status.TARGET_LOCKED": "Target locked",
        "status.MULTI_PRESENT": "Multiple people, target retained",
        "status.TARGET_OCCLUDED": "Target landmarks temporarily unavailable",
        "status.TARGET_REACQUIRING": "Rematching the body track",
        "status.IDENTITY_UNCERTAIN": "Target identity uncertain",
        "status.TARGET_AMBIGUOUS": "Target association ambiguous",
        "status.PROFILE_MISMATCH": "Profile mismatch",
        "status.UNKNOWN": "Unknown",
        "status.CALIBRATING": "Calibrating",
        "status.NEEDS_CALIB": "Needs calibration",
        "status.WAITING": "Waiting",

        # ---- debug_ui: REASON_TEXT ----
        "reason.press_calibrate": "Sit upright, then click calibrate",
        "reason.within_baseline": "Close to the personal anchor (legacy)",
        "reason.too_close": "Face too close to screen",
        "reason.shoulder_tilt": "Shoulder height offset is large",
        "reason.missing_face_or_pose": "Face or shoulders not detected",
        "reason.no_usable_metrics": "No usable visual metrics right now",
        "reason.face_within_baseline": "Face distance is normal",
        "reason.shoulder_within_baseline": "Shoulder height is normal",
        "reason.within_scientific_limits": "Personal posture deviation is within the watch range",
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
        "reason.distance_too_close": "Too close",
        "reason.distance_near": "Near",
        "reason.distance_too_far": "Too far",
        "reason.distance_far": "Far",
        "reason.shoulder_asymmetry": "Shoulder asymmetry",
        "reason.shoulder_width": "Shoulder width",
        "reason.shoulder_width_narrow": "Shoulder width clearly narrowed",
        "reason.trunk_lean": "Trunk lean",
        "reason.sustained_risk_s": "Sustained risk seconds",
        "reason.smoothed_risk_score": "Legacy smoothed score",
        "reason.risk_score": "Legacy score (compatibility alias)",
        "reason.risk_observing": "Risk observing",
        "reason.target_not_locked": "Target is not locked",
        "reason.target_observed": "Target observed",
        "reason.target_occluded": "Target landmarks temporarily unavailable",
        "reason.target_reacquiring": "Rematching the body track",
        "reason.target_missing_observing_s": "Target missing observed seconds",
        "reason.target_missing_candidate_present": "Candidate track detected; confirming the original target",
        "reason.target_missing_s": "Target missing seconds",
        "reason.target_away_s": "Target away seconds",
        "reason.ambiguous_face_body_association": "Face/body association is ambiguous",
        "reason.target_face_body_association_ambiguous": "Target face/body association is ambiguous",
        "reason.target_geometry_association_ambiguous": "Target geometry association is ambiguous",
        "reason.association_budget_exceeded": "The scene exceeds the safe association budget; target selection is paused",
        "reason.reacquired_candidate_needs_identity_confirmation": "Reacquired candidate needs identity confirmation",
        "reason.reacquired_candidate_identity_mismatch": "Reacquired candidate face identity does not match",
        "reason.other_track_present": "Another track is present",
        "reason.multi_present_observing": "Observing multiple-person state",
        "reason.multi_exit_stabilizing_s": "Multiple-person exit stabilization seconds",
        "reason.target_presence_check_disabled": "Presence checking is off; target state is tracked internally",
        "reason.dual_anchor_calibration_required": "Complete the two-anchor calibration",
        "reason.dual_anchor_calibration_collecting": "Collecting two-anchor calibration samples",
        "reason.activity_moving_exposure_paused": "Activity detected; static-exposure accumulation is paused",
        "reason.posture_adjustment_exposure_paused": "Reaching or adjusting posture; posture watching and static-exposure accumulation are paused",
        "reason.minor_posture_variation": "Normal small posture variation; static exposure is not accumulated",
        "reason.camera_drift_recalibration_required": "Camera position may have changed; recalibration is required",
        "reason.camera_roll_measurement_abstained": "The image reference direction changed; static-exposure accumulation is paused",
        "reason.camera_scale_jump_measurement_abstained": "Distance or overall scale is changing; static-exposure accumulation is paused",
        "reason.head_turn_measurement_abstained": "Head turn in progress; static-exposure accumulation is paused",
        "reason.sustained_head_direction": "Sustained large head turn",
        "reason.head_direction_quality_low": "Head-direction signal quality is too low",
        "reason.head_direction_delta": "Personal head-direction deviation",
        "reason.shared_shoulder_scale_measurement_abstained": "Shoulder measurement scale changed; static-exposure accumulation is paused",
        "reason.posture_features_unavailable": "Not enough posture-change features are available",
        "reason.posture_evidence_inconclusive": "Only one posture feature changed; static-exposure accumulation is paused",
        "reason.post_calibration_normal_range_validation": "Calibration is complete; confirming the target-locked measurement range",
        "reason.post_calibration_normal_range_validated": "Personal normal-range validation complete",
        "reason.measurement_quality_low": "Fewer posture features are currently usable; static-exposure accumulation is paused",
        "reason.within_personal_posture_range": "Within the personal two-anchor normal posture range",
        "reason.posture_deviation": "Personal posture deviation",
        "reason.exposure_seconds": "Equivalent static-exposure seconds",
        "reason.confidence": "Measurement confidence",
        "reason.static_hold_seconds": "Low-track-activity duration",
        "reason.static_hold_bonus": "Low-track-activity add-on (bounded; not posture abnormality)",

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
        "debug_dual_calibrate_btn": "Start Full Two-anchor Calibration",
        "debug_dual_cancel_btn": "Cancel Two-anchor Calibration",
        "debug_calibrate_btn": "Legacy Single-frame Calibration (Debug Only)",
        "debug_precision_cb": "Personal posture deviation (production requires two anchors)",
        "debug_performance_cb": "High-performance mode (72fps capture for smoother motion)",
        "debug_panel_title": "Vision Monitor",
        "debug_metric_face": "Face distance",
        "debug_metric_shoulder": "Shoulder tilt",
        "debug_metric_distance": "Estimated distance",
        "debug_metric_trunk": "Trunk lean",
        "debug_metric_projected_trunk_axis": "2D projected trunk axis",
        "debug_metric_projected_head_trunk": "2D head-trunk angle",
        "debug_metric_risk": "Posture deviation / combined risk / exposure / confidence",
        "debug_metric_baseline": "Current anchor",
        "debug_target_title": "P3/P4 Target Tracking",
        "debug_target_state": "Target state",
        "debug_target_track": "Locked track",
        "debug_target_count": "People present",
        "debug_target_score": "Match score",
        "debug_target_motion": "Target motion rate",
        "debug_target_activity": "Activity state",
        "debug_target_reason": "State reason",
        "debug_target_calib_fail": "Calibration failed: one clear target track is required",
        "debug_vision_mode": "Vision mode",
        "debug_vision_backend": "Current backend: {mode} · {backend}",
        "debug_vision_backend_notice": "{current}\nNotice: {notice}",
        "debug_activity_STATIC": "Static",
        "debug_activity_MOVING": "Moving",
        "debug_activity_UNKNOWN": "Unknown",
        "vision_mode_compatibility": "Compatibility mode",
        "vision_mode_standard": "Standard mode",
        "vision_mode_professional_beta": "Professional mode Beta",
        "vision_mode_compatibility_unavailable": "Compatibility mode unavailable: MediaPipe or OpenCV is missing.",
        "vision_mode_standard_unavailable": "Standard mode unavailable: the local YOLO26n-pose weight or optional dependencies are missing.",
        "vision_mode_professional_unavailable": "Professional mode Beta unavailable: no TensorRT posture backend is installed.",
        "vision_mode_switch_failed": "Mode switch failed; restored the previous backend: {detail}",
        "vision_compat_face_detector_fallback": (
            "BlazeFace detection is unavailable. FaceMesh fallback is active, so multi-face "
            "counts and face boxes are less reliable. Reason: {detail}"
        ),

        # ---- debug_ui: 动态 setText ----
        "debug_calib_no_sample": "No camera sample yet",
        "debug_calib_fail": "Calibration failed: face or shoulders not detected",
        "debug_calib_ok": "Calibrated (legacy debug): one frame is not a scientific calibration pass",
        "debug_dual_calib_started": "Preferred-posture measurement started: hold for the full 5 seconds and relax only after the prompt.",
        "debug_dual_calib_preferred": "Preferred stage: {preferred}/5 valid samples; relaxed stage {relaxed}/5. {detail}",
        "debug_dual_calib_relax_now": "Preferred stage complete. You may relax naturally now; transition samples are ignored for about 1 second.",
        "debug_dual_calib_transition": "Waiting for posture to settle: preferred {preferred}/5; relaxed {relaxed}/5. Transition samples are ignored.",
        "debug_dual_calib_relaxed": "Relaxed stage: preferred {preferred}/5; {relaxed}/5 valid samples. {detail}",
        "debug_dual_calib_extending": "Relaxed measurement is in its bounded extension: preferred {preferred}/5; relaxed {relaxed}/5. {detail}",
        "debug_dual_calib_accepting": "Current sample accepted",
        "debug_dual_calib_failed": "Two-anchor calibration failed: {detail}",
        "debug_dual_calib_ok": "Scientific two-anchor calibration complete: {preferred} preferred, {relaxed} relaxed, quality {quality:.2f}, {features} enabled features.",
        "debug_dual_calib_cancelled": "Two-anchor calibration cancelled; the current anchors were not changed.",
        "debug_dual_calib_active": "Two-anchor calibration is complete; production monitoring is active.",
        "debug_stage_idle_title": "Calibration idle",
        "debug_stage_idle_detail": "The full two-anchor control tests upright, transition, natural-relaxation, and monitoring states.",
        "debug_stage_badge_idle": "--",
        "debug_stage_badge_preferred": "1/2",
        "debug_stage_badge_transition": "RELAX",
        "debug_stage_badge_relaxed": "2/2",
        "debug_stage_badge_active": "LIVE",
        "debug_stage_badge_validating": "CHECK",
        "debug_stage_badge_failed": "RETRY",
        "debug_stage_preferred_title": "First segment · Sit upright now",
        "debug_stage_preferred_detail": "Hold the correct comfortable posture you accept for the full 5 seconds. Do not relax yet; the green view records only the upright posture.",
        "debug_stage_transition_title": "Change posture · Relax now",
        "debug_stage_transition_detail": "The upright posture is recorded. Relax naturally now; the orange transition is not sampled. Relaxed sampling starts only when the view turns purple.",
        "debug_stage_camera_relax_prompt": "Upright posture recorded\nRelax naturally now\nSegment 2 starts when the view turns purple",
        "debug_stage_relaxed_title": "Second segment · Stay naturally relaxed",
        "debug_stage_relaxed_detail": "The purple view is silently recording the relaxed posture. There is no second countdown; remain relaxed until calibration completes.",
        "debug_stage_active_title": "Two anchors ready · Monitoring active",
        "debug_stage_active_detail": "Both anchors and their interval are normal; only sustained excursion beyond the measurement-noise band and natural-movement margin accumulates.",
        "debug_stage_validating_title": "Two anchors collected · Validating normal range",
        "debug_stage_validating_detail": "Hold a stable posture for about 2 seconds. Exposure stays paused until target-locked measurements reproduce your personal normal range.",
        "debug_stage_failed_title": "Two-anchor calibration failed",
        "debug_stage_failed_detail": "Calibration failed; the specific reason is shown here.",
        "debug_stage_failed_reason": "Reason: {detail} (upright {preferred}/{minimum}, relaxed {relaxed}/{minimum})",
        "debug_stage_camera_preferred_banner": "SEGMENT 1 OF 2\nSIT UPRIGHT · DO NOT RELAX\nThe green view is recording your accepted upright posture",
        "debug_stage_camera_transition_banner": "STOP HOLDING UPRIGHT · RELAX NOW\nThe orange transition is not sampled\nWait for the view to turn purple",
        "debug_stage_camera_relaxed_banner": "SEGMENT 2 OF 2\nSTAY NATURALLY RELAXED\nThe purple view is silently recording your relaxed posture",
        "debug_stage_rail_preferred_active": "1  UPRIGHT NOW",
        "debug_stage_rail_preferred_done": "1  UPRIGHT DONE",
        "debug_stage_rail_relaxed_next": "2  RELAX NEXT",
        "debug_stage_rail_relaxed_now": "2  RELAX NOW",
        "debug_stage_rail_relaxed_active": "2  RELAXED SAMPLING",

        # ---- debug_ui: 指标后缀 ----
        "debug_face_suffix": "{v}  larger = closer",
        "debug_face_not_used_standard": "No usable face measurement is available for this frame",
        "vision_identity_model_unavailable": "Face identity model unavailable: {detail}",
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


def _notify_listeners() -> None:
    """通知所有监听器语言/模式已变更。复制一份避免迭代中增删。"""
    for cb in list(_listeners):
        try:
            cb()
        except Exception:
            # 监听器出错不能影响其他监听器或主流程
            import traceback
            traceback.print_exc()


def set_language(lang: str) -> bool:
    """切换语言并通知监听器。

    返回 True 表示语言实际变化并已通知；False 表示未变化（同语言去重，
    或 lang 非法）。调用方在"模式变化但语言未变"时需自行补通知。
    """
    global _lang
    if lang not in _TEXTS:
        return False
    if lang == _lang:
        return False
    _lang = lang
    _notify_listeners()
    return True


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

    若检测到的系统语言与当前一致（set_language 未通知），因模式已从 manual 变 auto，
    仍需补一次通知以刷新按钮文案。
    """
    global _user_override
    _user_override = None
    detected = _detect_system_language()
    notified = set_language(detected)
    if not notified:
        _notify_listeners()


def cycle_language() -> str:
    """三态循环：zh → en → auto → zh。

    返回切换后的模式名（'zh' / 'en' / 'auto'），供按钮文案使用。
    auto 模式下，current_language() 仍返回实际生效的 'zh' 或 'en'，
    但按钮会显示"跟随系统"以提示用户。

    模式变化后，若 set_language 因同语言未通知，这里补一次——
    按钮文案依赖 current_mode()，模式变了就需刷新。
    """
    global _user_override
    if _user_override is None:
        # 当前是 auto → 切到 zh
        _user_override = "zh"
        notified = set_language("zh")
        if not notified:
            _notify_listeners()
        return "zh"
    if _user_override == "zh":
        _user_override = "en"
        set_language("en")  # zh→en 必通知，无需补
        return "en"
    # 当前是 en → 切回 auto
    _user_override = None
    detected = _detect_system_language()
    notified = set_language(detected)
    if not notified:
        _notify_listeners()
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
