# 候选视觉模型许可证审计

- 审计日期：2026-08-10
- 审计范围：EP-LICENSE-001、EP-LICENSE-002 的候选代码、模型卡和训练数据声明
- 结论等级：`verified` 仅表示指定来源明确支持该字段；`conditional` 表示还需精确文件或使用场景确认；`blocked` 表示在证据补齐前不得集成或发行。

## 审计表

| 候选 | 官方代码来源 | 代码许可证 | 精确权重/版本 | 权重许可证 | 训练数据限制 | 当前结论 |
| --- | --- | --- | --- | --- | --- | --- |
| Ultralytics YOLO26n/l/x-pose | [Ultralytics repository](https://github.com/ultralytics/ultralytics)；[license guidance](https://www.ultralytics.com/license) | AGPL-3.0（GitHub API `license.spdx_id`） | 本地开发权重 `models/pose/yolo26n-pose.pt`；7,878,574 bytes；SHA-256 `EB3BB8268828AEAF515CEC23A4BFAFD793944A86FE9AF94BA7823609C14522A9`；未加入 Git/发行包 | 官方许可页称 Ultralytics 训练模型默认受 AGPL-3.0 覆盖；EchoPosture 已由 GPLv3 切换并接受 `AGPL-3.0-only` | 未从模型卡取得可用于本项目发行的训练数据条款 | `conditional`; 本地开发可进入原型，权重再分发与训练数据条款补证前仍不得进入 Git/CI/发行包 |
| CVLFace AdaFace ViT-Base KP-RPE | [CVLFace](https://github.com/mk-minchul/CVLface) | MIT（仓库 LICENSE，GitHub API） | `minchul/cvlface_adaface_vit_base_kprpe_webface4m`, revision `6530d73fb0af4d1d8287f31d559780c648ebd22a`; `model.safetensors` 460344344 bytes, SHA-256 `3c6d37ea874c2f38ffc9a7f0e9247efc994c3fb5c12d044759ac294e19d127f7`; `pretrained_model/model.pt` 460381841 bytes, SHA-256 `b8d5adde0a00f6482b5e866b6e37eeaa947302a40d9af31c211af72f34d38afb` | 模型卡没有给出可替代精确权重条款 | 模型卡明确要求遵守训练数据许可证；WebFace4M 的再分发/商业使用尚未核实 | `conditional`; 训练数据和精确权重许可补证前 `blocked` |
| AdaFace IR101 | [AdaFace](https://github.com/mk-minchul/AdaFace)；[CVLFace model card](https://huggingface.co/minchul/cvlface_adaface_ir101_webface4m) | MIT（仓库 LICENSE，GitHub API） | `minchul/cvlface_adaface_ir101_webface4m`, revision `f2b38d9e24bfe301490d8dd081d8924b102333dd`; `model.safetensors` 260980552 bytes, SHA-256 `21adb6220e8799a0e658f16946df9649c7269f432fe9810a7b9c4ad1241080a8`; `pretrained_model/model.pt` 261111273 bytes, SHA-256 `7a3341c3afc507fd6f50345638d2f3ef2f0e931d5b4f5aba60e15709853fcf5e` | 未核实 | README/仓库未提供本审计所需的完整训练数据再分发结论 | `conditional`; 精确 checkpoint 和数据条款补证前 `blocked` |
| CAFace 聚合器 | [CAFace](https://github.com/mk-minchul/caface) | MIT（仓库 LICENSE，GitHub API） | 未选定；无权重文件纳入本次审计 | 不适用（尚未选权重） | 未核实；仅可作为研究候选 | `conditional`; 不得进入发行包 |

## 已核实事实与限制

- GitHub 官方 API 在审计日返回：Ultralytics `AGPL-3.0`、CVLFace/AdaFace/CAFace `MIT`。这只描述仓库检测到的许可证，不替代文件级许可证或权重条款。
- Ultralytics 官方许可页写明：使用其代码、模型、架构、训练流程或训练/微调模型时，需要在 AGPL-3.0 下开源整个项目，或取得 Enterprise License；该判断必须由发行方式和法律审查最终确认。
- CVLFace 模型卡写明要引用论文并遵守训练数据许可证；因此模型卡没有明确授权时，不能把模型上传到发行包或 CI 缓存。
- 本次没有下载候选权重，也没有计算 SHA-256；所有“精确权重”字段仍是未验证项。

## 集成前必须补齐

1. 固定每个候选的下载 URL、revision/版本、文件名和 SHA-256。
2. 保存代码 LICENSE、权重 LICENSE/README 和训练数据条款的副本或稳定链接。
3. 按 EchoPosture 已接受的 `AGPL-3.0-only` 决策，定义发行包的完整相应源码、NOTICE 和用户获取方式。
4. 对 WebFace4M 及其他训练集取得再分发、商业使用和隐私边界的书面结论。
5. 将最终结论复核到发行包扫描和 GitHub Actions 缓存策略；未完成前保持 `blocked`。

## 致谢声明草案

EchoPosture 不主张对所引用的第三方模型、论文、商标或原始实现享有所有权。相关权利归各自作者和权利人所有。我们感谢 Ultralytics、Google MediaPipe、OpenCV、CVLFace、AdaFace、CAFace 及相关研究者对计算机视觉和开源生态的贡献。
