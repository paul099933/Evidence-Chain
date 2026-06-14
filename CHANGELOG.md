# CHANGELOG

## v0.1 — 基线归档（2026-06-14）
**项目**：Evidence-Chain PROMPT 驱动版本  
**增加**：run-test.sh、test-sfp.sh、test-html-delivery.sh、test-manifest.yaml、orchestrator/runner/verifier/fixer.soul.md  
**修改原因**：当前代码分散在 4 个 SOUL.md 中，靠模型协作完成 Runner→Verifier→Fixer 循环。retry 计数在 prompt 中，模型可绕过；branch 决策由 Verifier 模型做，不可靠。先归档作为基线。

## v1.0 — Plugin 骨架（2026-06-XX）
**项目**：Evidence-Chain Plugin 代码级 Pipeline 编排器  
**增加**：`plugins/evidence-chain/`（plugin.yaml + __init__.py + pipeline.py），`pipeline_start` 工具  
**修改原因**：把循环逻辑从 4 个 SOUL.md 收敛到 1 个 Plugin。代码级创建 Runner、Polling 等待、代码判定 pass/fail。解决"模型不可靠"问题。

## v1.1 — 修复循环（2026-06-XX）
**项目**：Evidence-Chain 自动修复循环  
**增加**：Plugin 内 retry 计数（Python 变量）、状态机、自动创建 Fixer + 新 Runner  
**修改原因**：v1.0 只有单次闭环。v1.1 实现失败→修复→重测的完整循环，retry 上限由代码强制，模型不可绕过。

## v2.0 — 自然语言入口（2026-06-XX）
**项目**：Evidence-Chain 自然语言驱动  
**增加**：Orchestrator SOUL.md 意图解析层，`pipeline_start` 支持自然语言参数  
**修改原因**：用户只需说"测 SFP，确保空文件被拒绝，全部通过"，系统自动生成测试计划。降低使用门槛。

## v2.1 — 通用化（2026-06-XX）
**项目**：Evidence-Chain 通用测试框架  
**增加**：项目发现机制、动态测试计划生成、记忆点系统/求职系统试点  
**修改原因**：SFP 只是第一个被测对象。框架应支持任何有代码可验证的项目，不改框架代码即可接入。

## v3.0 — Retrospective（2026-06-XX）
**项目**：Evidence-Chain 自我优化  
**增加**：Retrospective Agent、learnings.md、历史模式自动应用  
**修改原因**：系统从每次循环中学习，沉淀已知修复模式，减少重复失败。