# CHANGELOG

## v1.2 — 仓库重组 + deploy.sh（2026-06-23）
**项目**：Evidence-Chain 仓库结构标准化
**增加**：
- `src/` 统一构建源（profiles/、evidence-tools/、plugins/、docs/）
- `archive/v0/` 历史基线归档
- `deploy.sh` 单向同步脚本（dry-run / --exec，SHA 校验，尸体清理）
- 补全所有 config.yaml 部署（orchestrator/runner/fixer/verifier）
**修改原因**：仓库根目录混乱（v0 与 v1 混排）、profile SOUL.md 从未正式部署、无自动化 deploy。Plugin 从 orchestrator/ 死副本迁移到 deepseek profile。
**删除**：orchestrator/plugins/ 死副本、ghost home/ 目录

## v1.1 — 修复循环 + 对抗性审查（2026-06-19）
**项目**：Evidence-Chain 自动修复循环
**增加**：Plugin 内 retry 计数（Python 变量）、状态机、自动创建 Fixer + 新 Runner
**增加**：Verifier 审计门控（adversarial audit，默认不 pass）
**增加**：nonce 双向绑定（L2 防线）、Evidence JSON 文件系统证据
**修改原因**：v1.0 只有单次闭环。v1.1 实现失败→修复→重测的完整循环，retry 上限由代码强制，模型不可绕过。

## v1.0 — Plugin 骨架（2026-06-15）
**项目**：Evidence-Chain Plugin 代码级 Pipeline 编排器
**增加**：`plugins/pipeline/`（plugin.yaml + __init__.py），`pipeline_start` 工具
**修改原因**：把循环逻辑从 4 个 SOUL.md 收敛到 1 个 Plugin。代码级创建 Runner、Polling 等待、代码判定 pass/fail。解决"模型不可靠"问题。

## v0.1 — 基线归档（2026-06-14）
**项目**：Evidence-Chain PROMPT 驱动版本
**增加**：run-test.sh、test-sfp.sh、test-manifest.yaml、orchestrator/runner/verifier/fixer SOUL.md
**修改原因**：当前代码分散在 4 个 SOUL.md 中，靠模型协作完成 Runner→Verifier→Fixer 循环。retry 计数在 prompt 中，模型可绕过。先归档作为基线。
