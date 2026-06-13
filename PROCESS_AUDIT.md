# Process Audit Rules

本文件规定 EchoPosture 的开发日志、验证证据、发布记录和回滚记录如何写入 Git 可追踪文档。它补充 [ROE.md](ROE.md)，目标是让后续维护者能从仓库本身复查每次关键开发过程，而不是依赖被忽略的本地日志、口头说明或发布包目录。

## 基本要求

- Git 历史是事实来源，但不能单独作为过程审计记录。每个高风险或可观察改动都必须有可读开发日志。
- 开发日志必须写入 [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md) 或该文件明确链接的 `docs/` 文档，不能只放在 `logs/`、`dist/`、`_backups/`、`runtime/` 或聊天记录里。
- `logs/`、`dist/`、`runtime/`、`_backups/` 是本地产物目录，默认不提交。需要保留其中的证据时，只提交摘要、命令、hash、关键输出和结论，不提交整包或大日志。
- 每条开发日志必须区分事实、推断和人工判断。不能把未运行的验证写成已通过。
- 如果验证失败、跳过或只能人工判断，日志必须明确写出原因、影响范围和后续处理状态。

## 何时必须写开发日志

满足任一条件时，必须在提交前或同一提交内更新开发日志：

- 改动影响启动器、托盘运行时、视觉覆盖层、GPU 模糊宿主、摄像头读取、发布包、release、备份或恢复流程。
- 单次提交跨多个模块，或单个提交超过一个清晰子任务。
- 改动改变用户可见行为、文案、UI、托盘菜单、热键、默认配置、冻结文件规则或发布规则。
- 改动涉及 `ui/index.html` 冻结参考、`posture_console.py`、`tray_app.py`、`vision_test.py`、`native/BlurOverlayHost.cpp` 或 `launcher/EchoPostureLauncher.cs`。
- 创建、更新、替换、回滚或删除 GA、TEAM_ALPHA 包、历史 DEV 包、release 附件、备份目录或构建脚本。
- 修复先前错误文档、错误发布、错误验证结论或失败自测。

只读检查可以不写开发日志，但如果检查结果会影响后续开发判断，应在 [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md) 的“审计缺口/已知问题”中记录。

## 日志条目必须包含

每个条目至少包含：

- 日期和时区。
- 关联 commit SHA、tag、branch；提交前日志可以写 `pending`，提交后补 SHA。
- 需求来源：用户要求、缺陷、规则要求、发布需要、回滚需要或维护判断。
- 变更范围：主要文件、运行入口、用户可见行为。
- 风险点：退出、覆盖层清理、摄像头释放、GPU fallback、UI 阻塞、构建/发布、冻结文件、数据记录、依赖环境。
- 验证命令：实际运行的命令、运行目录、关键输出摘要、退出码。
- 未验证项：未运行原因、残余风险、后续补验证计划。
- 产物证据：包路径、tag、文件大小、SHA256、release URL 或 GitHub CLI 回查摘要。
- 结论：可交付、仅本地可用、需补验证、或阻塞。

## 验证证据规则

- 自测日志如果保存在 `logs/`，必须把关键结果摘要写回开发日志。
- GUI、摄像头、桌面捕获、托盘和 overlay 验证不能只写“看起来正常”；必须记录入口、操作、观察结果和失败恢复方式。
- 构建验证必须记录构建命令、输出产物路径、关键二进制大小和失败/成功结论。
- UI 验证应记录视口、截图路径或人工检查点；如果没有截图，也必须写明原因。
- 依赖或运行时验证应记录 Python 版本、关键包版本、MediaPipe 资源是否存在、Qt 插件路径和中文路径/ASCII bridge 行为。

## 发布和包审计规则

每次 GA、TEAM_ALPHA 包、历史 DEV 包或 release 相关操作都必须记录：

- 源码 commit SHA 和 tag。
- 构建时间、构建命令、构建机器路径。
- 包目录、入口 EXE、诊断 EXE、关键脚本。
- SHA256 或至少关键文件 hash；正式 release 必须记录完整附件 digest。
- `git status --short`、`git remote -v`、tag 指向和 GitHub release 回查结果。
- 仓库私密状态回查结果；如果无法回查，必须写明原因。

## 备份和回滚审计规则

- 每个 `_backups/` 子目录必须有 `BACKUP_MANIFEST.txt`。
- manifest 至少记录创建时间、来源路径、Git HEAD、`git status --short`、备份范围、创建原因。
- 如果历史备份缺少 manifest，不得补写成“当时已记录”；只能在开发日志里标记为“历史缺口”。
- 回滚优先使用 `git revert`。如果从备份恢复单文件，必须记录来源备份、目标文件、diff 摘要和验证结果。

## 当前已知审计缺口

以下缺口来自 2026-06-09 对 Git 历史和本地文件的复查，后续不能继续扩大：

- 2026-05-30 初始 MVP 和早期备份缺少完整开发日志。
- `_backups/EchoPosture-source-backup-20260530-194638` 没有 `BACKUP_MANIFEST.txt`。
- 根目录 `logs/self-test-latest.txt` 是 2026-05-31 的旧失败日志，不能证明 2026-06-07 DEV 包或后续 TEAM_ALPHA/GA 包通过验证。
- `dist/EchoPosture-DEV-20260607-144042-win-x64/logs` 当前没有可用 self-test 记录。
- 2026-06-02、2026-06-07、2026-06-08 的大提交缺少逐项验证证据、截图证据和发布 hash 记录。
- `dev-20260607-144042` tag 能证明历史源码点，但不能单独证明包内容、release 附件和本地产物完全一致。后续 TEAM_ALPHA/GA tag 也必须配套记录产物 hash 和 release 回查结果。

## 开发日志模板

```markdown
## YYYY-MM-DD - Short Title

- Source: user request / bug / release / rollback / maintenance
- Git: commit `pending` or `<sha>`, branch `<branch>`, tag `<tag or none>`
- Scope: files and behavior changed
- Risk: concrete runtime, release, UI, or data risks
- Verification:
  - Command: `<command>`
  - Result: passed / failed / skipped
  - Evidence: key output, exit code, screenshot/hash/log summary
- Artifacts: package path, file size, SHA256, release URL, if any
- Gaps: skipped checks and residual risk
- Conclusion: ready / local only / needs follow-up / blocked
```
