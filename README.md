# Evidence-Chain

通用 Agent 驱动的迭代测试框架。用户通过自然语言描述"测什么、优化方向、验收标准"，系统在隔离 worktree 中自动执行测试、捕获 SHA-256 签名证据、失败时自动修复、循环重测，直到验收通过或重试耗尽。

当前版本：v1.3 — pipeline_core 模块化 + 声明式测试引擎

## 核心机制：4-Agent 闭环

Orchestrator -> Runner -> Fixer -> Verifier -> (循环重测直到通过)

- Orchestrator：需求翻译 + 生成验收标准，调用 pipeline_start
- Runner：执行测试，输出 JUnit XML + SHA-256 证据
- Fixer：基于证据修复代码，受 scope 硬约束（allow_edit / deny_edit / max_diff_lines）
- Verifier：修复后审计，默认不通过，有明确证据才放行

## 目录结构

    src/
      pipeline_core/      # Python 核心库（acceptance / diff_guard / evidence / git_utils / schema）
      plugins/pipeline/   # Hermes 插件（pipeline_start）
      profiles/           # 4 个 Agent 配置（orchestrator / runner / fixer / verifier）
      evidence-tools/     # 声明式测试引擎（test-runner.sh / generate.sh / feedback.sh）
      docs/               # 文档（product-vision / architecture / CHANGELOG）
    tests/                # 单元测试
    archive/v0/           # v0.1 基线归档
    deploy.sh             # 一键部署

## 快速开始

    git clone git@github.com:paul099933/Evidence-Chain.git
    cd Evidence-Chain
    pytest tests/
    ./deploy.sh

## 版本记录

    v1.3 (2026-07-08): pipeline_core 模块化、声明式测试引擎、diff_guard 代码级防线
    v1.2: 端到端验证通过，防造假四层防线（L0-L3）生效
    v0.1: 基线归档（PROMPT 驱动版本）

完整记录见 src/CHANGELOG.md

## 文档索引

- src/docs/product-vision.md
- src/docs/architecture.md
- src/CHANGELOG.md

## 许可证

MIT
