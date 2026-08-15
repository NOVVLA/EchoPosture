# ADR-0003：接受 GNU AGPLv3 严格许可证

- 状态：已接受
- 日期：2026-08-14（Asia/Shanghai）
- 范围：EchoPosture 项目自有代码、源代码发行与后续网络交互部署

## 决策

EchoPosture 项目自有代码从 GNU GPLv3 切换为 **GNU Affero General Public License
v3.0 only（`AGPL-3.0-only`）**。根目录 `LICENSE` 保存 GNU 官方 AGPLv3 完整文本。

项目明确接受该严格许可证的义务，包括但不限于：发行目标代码时提供相应源码；保留许可与无担保声明；如果修改后的版本支持用户通过计算机网络远程交互，依照 AGPLv3
第 13 条向这些用户显著提供取得相应源码的机会。

该决策也解除 EchoPosture 自有代码采用 AGPL-3.0 版 Ultralytics 代码/模型时原有的
GPLv3 组合许可冲突。若未来不愿履行 AGPLv3，则必须在引入相关组件前取得适用的
Ultralytics Enterprise License，不能静默改回宽松许可。

## 明确边界

- 第三方库、模型、论文、商标和数据集仍归各自权利人所有，并继续受各自条款约束。
- 接受 AGPLv3 **不自动证明**某个预训练权重或其训练数据允许再分发、商用或打包。
- 当前本地 `models/pose/yolo26n-pose.pt` 只作为开发者提供的显式本地输入；在完成文件级来源与再分发审计前，不加入 Git、CI 缓存或发行包。
- 标准模式禁止隐式下载模型。模型路径必须已存在，并在审计记录中登记文件名、大小和 SHA256。
- 本决策不是法律意见；具体发行方式仍需按发行清单逐项复核相应源码和第三方通知。

## 当前本地开发证据

- 文件：`models/pose/yolo26n-pose.pt`
- 大小：`7,878,574` 字节
- SHA256：`EB3BB8268828AEAF515CEC23A4BFAFD793944A86FE9AF94BA7823609C14522A9`
- Git/发行状态：未跟踪、未批准再分发、不得随本次提交上传

## 依据

- GNU AGPLv3 官方全文：https://www.gnu.org/licenses/agpl-3.0.txt
- Ultralytics 许可证说明：https://www.ultralytics.com/license
- Ultralytics Pose 官方文档：https://docs.ultralytics.com/tasks/pose/
