---
name: speckit-bugfix
version: 1.0.0
display_name: Spec Kit Bug 修复流程
display_name_en: Spec Kit Bug Fix Workflow
description: GitHub Spec Kit 的 bugfix 三段流程（assess → fix → test）入口。由 specify-cli 的 bug 扩展生成，用于对一个明确 bug 报告做定性、修复与验证，报告落盘 .specify/bugs/<slug>/。触发词：spec-kit、speckit、bug 修复流程、/speckit-bug-assess、/speckit-bug-fix、/speckit-bug-test。
agent_created: true
---

# Spec Kit Bug 修复流程（薄入口）

本 skill 只做入口映射。流程正文以项目内 spec-kit 生成的命令文件为准，不得在此复写或改写判据：

| 阶段 | 命令文件（权威正文） | 产出 |
|---|---|---|
| 评估 | `.codebuddy/commands/speckit.bug.assess.md` | `.specify/bugs/<slug>/assessment.md` |
| 修复 | `.codebuddy/commands/speckit.bug.fix.md` | `.specify/bugs/<slug>/fix.md` |
| 验证 | `.codebuddy/commands/speckit.bug.test.md` | `.specify/bugs/<slug>/test.md` |

## 使用纪律

1. 一次只跑一个阶段，跑完先让人看结果，再进下一步。三段顺序固定：assess → fix → test。
2. `test` 阶段的结论只有 `verified` / `partial` / `failed` 三种；只有 `verified` 算修好。
3. 报告统一落在 `.specify/bugs/<slug>/`，slug 为 kebab-case，不覆盖已有目录。
4. 评估阶段只读代码，不改源码；修复阶段才允许改。
5. 若 `.specify/extensions/bug/` 不存在，说明扩展未安装：在项目根执行
   `specify extension add bug`（CLI 需 Python ≥3.11）。
