"""全局 i18n 模块的纯逻辑烟雾测试（不创建 QApplication、不开 GUI）。

验证：
- zh / en 两个语言包键集合完全一致（缺键会导致切换后某些控件文字不变）。
- 所有文本非空。
- set_language 只接受已知语言，未知值忽略。
- 切换后 _t 返回对应语言的字符串。
- 多次来回切换结果稳定。
- 三态循环：auto → zh → en → auto → zh ...（跟随系统功能）。
- lang_button_text() 在各模式下返回正确的按钮文案。

运行：python smoke_i18n.py
"""

from __future__ import annotations

import i18n


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def test_keys_match() -> None:
    print("[1] zh / en 键集合一致")
    zh = set(i18n._TEXTS["zh"].keys())
    en = set(i18n._TEXTS["en"].keys())
    _assert(zh == en, f"zh==en 键集合（共 {len(zh)} 个键）")
    missing_in_en = zh - en
    missing_in_zh = en - zh
    _assert(not missing_in_en, f"en 缺键: {sorted(missing_in_en)}")
    _assert(not missing_in_zh, f"zh 缺键: {sorted(missing_in_zh)}")


def test_no_empty_strings() -> None:
    print("[2] 所有文本非空")
    for lang, table in i18n._TEXTS.items():
        for k, v in table.items():
            _assert(isinstance(v, str) and v.strip() != "",
                    f"[{lang}].{k} 非空 -> {v!r}")


def test_set_language_known_only() -> None:
    print("[3] set_language 只接受已知语言")
    i18n.set_language("zh")
    _assert(i18n.current_language() == "zh", "set_language('zh') 生效")
    i18n.set_language("en")
    _assert(i18n.current_language() == "en", "set_language('en') 生效")
    before = i18n.current_language()
    i18n.set_language("fr")  # 未知，应忽略
    _assert(i18n.current_language() == before,
            f"未知语言 'fr' 被忽略，保持 {before!r}")
    i18n.set_language("")  # 空串，应忽略
    _assert(i18n.current_language() == before, "空串被忽略")


def test_t_returns_correct_language() -> None:
    print("[4] _t 在切换后返回对应语言文本")
    i18n.set_language("zh")
    _assert(i18n._t("exit") == "退出本程序",
            f"zh exit -> {i18n._t('exit')!r}")
    _assert(i18n._t("recalibrate") == "立即重新校准",
            f"zh recalibrate -> {i18n._t('recalibrate')!r}")
    i18n.set_language("en")
    _assert(i18n._t("exit") == "Exit",
            f"en exit -> {i18n._t('exit')!r}")
    _assert(i18n._t("recalibrate") == "Recalibrate Now",
            f"en recalibrate -> {i18n._t('recalibrate')!r}")


def test_toggle_roundtrip_stable() -> None:
    print("[5] 多次来回切换结果稳定")
    expected_zh_exit = i18n._TEXTS["zh"]["exit"]
    expected_en_exit = i18n._TEXTS["en"]["exit"]
    for i in range(5):
        i18n.set_language("zh")
        _assert(i18n._t("exit") == expected_zh_exit,
                f"round {i} zh exit 稳定 -> {i18n._t('exit')!r}")
        i18n.set_language("en")
        _assert(i18n._t("exit") == expected_en_exit,
                f"round {i} en exit 稳定 -> {i18n._t('exit')!r}")


def test_three_state_cycle() -> None:
    """三态循环：auto → zh → en → auto → zh ..."""
    print("[6] 三态循环 cycle_language()")
    # 起点：重置到 auto 模式
    i18n.set_auto_language()
    _assert(i18n.current_mode() == "auto", "重置后回到 auto 模式")
    # 跑 2 个完整循环（auto → zh → en → auto → zh → en → auto）
    expected = ["zh", "en", "auto", "zh", "en", "auto"]
    for i, want in enumerate(expected):
        got = i18n.cycle_language()
        _assert(got == want, f"cycle {i}: 期望 {want!r}，得到 {got!r}")
        _assert(i18n.current_mode() == want,
                f"cycle {i}: current_mode() == {want!r}")


def test_lang_button_text() -> None:
    """语言按钮文案在各模式下都正确。"""
    print("[7] lang_button_text() 在各模式下返回正确文案")
    # auto + 系统 zh：当前生效 zh
    i18n.set_auto_language()
    sys_lang = i18n.system_detected_language()
    eff = i18n.effective_language()
    _assert(eff == sys_lang,
            f"auto 模式下 effective_language == system_detected_language ({sys_lang!r})")
    text = i18n.lang_button_text()
    expected_key = f"lang_button_auto_{eff}"
    _assert(text == i18n._t(expected_key),
            f"auto + {eff}: 按钮文案 -> {text!r}")
    # 显式 zh
    i18n.set_language("zh")
    i18n._user_override = "zh"  # 模拟 cycle 第一步
    text = i18n.lang_button_text()
    _assert(text == i18n._t("lang_button_zh"),
            f"显式 zh: 按钮文案 -> {text!r}")
    # 显式 en
    i18n._user_override = "en"
    i18n.set_language("en")
    text = i18n.lang_button_text()
    _assert(text == i18n._t("lang_button_en"),
            f"显式 en: 按钮文案 -> {text!r}")


def test_placeholder_formatting() -> None:
    """占位符格式化正确（{name} 形式）。"""
    print("[8] 占位符格式化")
    i18n.set_language("zh")
    s = i18n._t("sp_status", status="正常")
    _assert(s == "当前状态：正常", f"sp_status -> {s!r}")
    s = i18n._t("console_state_active", n=3)
    _assert(s == "监测中 · 3 项功能已启用", f"console_state_active -> {s!r}")
    i18n.set_language("en")
    s = i18n._t("sp_status", status="Good")
    _assert(s == "Status: Good", f"en sp_status -> {s!r}")
    s = i18n._t("console_state_active", n=2)
    _assert(s == "Monitoring · 2 feature(s) active",
            f"en console_state_active -> {s!r}")


if __name__ == "__main__":
    test_keys_match()
    test_no_empty_strings()
    test_set_language_known_only()
    test_t_returns_correct_language()
    test_toggle_roundtrip_stable()
    test_three_state_cycle()
    test_lang_button_text()
    test_placeholder_formatting()
    # 恢复默认（跟随系统）
    i18n.set_auto_language()
    print("\nALL I18N LOGIC TESTS PASSED")
