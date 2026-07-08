# Evidence-Chain

通用 Agent 驱动的迭代测试框架。用户通过自然语言描述"测什么、优化方向、验收标准"，系统在隔离 worktree 中自动执行测试、捕获 SHA-256 签名证据、失败时自动修复、循环重测，直到验收通过或重试耗尽。

> **当前版本：v1.3** — pipeline_core 模块化 + 声明式测试引擎

---

## 核心机制：4-Agent 闭环
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Orchestrator│────→│   Runner    │────→│   Fixer     │────→│  Verifier   │
│  需求翻译   │     │  执行测试   │     │  代码修复   │     │  修复审计   │
│ 生成验收标准 │     │ 输出 JUnit  │     │ scope 约束  │     │ 防造假防线  │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
↑___________________________________________________________│
(循环重测，直到 pass 或 retry 耗尽)
plain

- **Orchestrator**：将用户自然语言翻译为验收标准条目 + 声明式测试定义，确认后调用 `pipeline_start`
- **Runner**：在隔离 worktree 中执行 `test-runner.sh`，生成 JUnit XML + SHA-256 证据
- **Fixer**：基于真实失败证据修复代码，受 `allow_edit`/`deny_edit`/`max_diff_lines` 硬约束，越界自动 `drop_last_commit`
- **Verifier**：修复后审计，默认结论"不通过"，只有全部检查项有明确证据时才放行

---

## 目录结构
evidence-chain/
├── src/
│   ├── pipeline_core/          # 可独立测试的 Python 核心库（Hermes-agnostic）
│   │   ├── acceptance.py       # 验收标准评估
│   │   ├── diff_guard.py       # Fixer 修改范围硬检查
│   │   ├── evidence.py         # 证据解析、加载、校验
│   │   ├── git_utils.py        # 分支、worktree、清理工具
│   │   └── schema.py           # 证据 JSON Schema 校验
│   ├── plugins/pipeline/       # Hermes 插件入口
│   │   ├── init.py         # 注册 pipeline_start 工具
│   │   └── plugin.yaml
│   ├── profiles/               # 4 个 Agent 角色配置（config + SOUL）
│   │   ├── orchestrator/
│   │   ├── runner/
│   │   ├── fixer/
│   │   └── verifier/
│   ├── evidence-tools/         # 声明式测试引擎
│   │   ├── test-runner.sh      # 通用测试执行器（YAML 定义 → JUnit XML）
│   │   ├── generate.sh         # 证据生成（nonce + SHA-256）
│   │   └── feedback.sh
│   └── docs/
│       ├── product-vision.md
│       ├── architecture.md
│       └── CHANGELOG.md
├── tests/                      # pipeline_core 单元测试
├── archive/v0/                 # v0.1 基线归档
└── deploy.sh                   # 一键部署脚本
plain

---

## 快速开始

```bash
# 1. 克隆
git clone git@github.com:paul099933/Evidence-Chain.git
cd Evidence-Chain

# 2. 运行 pipeline_core 单元测试
pytest tests/

# 3. 部署到 Hermes（自动安装 pipeline_core + 插件 + 证据工具）
./deploy.sh
版本记录
表格
版本	时间	核心变化
v1.3	2026-07-08	pipeline_core 模块化、声明式测试引擎、diff_guard 代码级防线
v1.2	—	端到端验证通过，防造假四层防线（L0-L3）生效
v0.1	—	基线归档（PROMPT 驱动版本）
完整记录见 src/CHANGELOG.md。
文档索引
产品愿景
架构决策
版本记录
许可证
MIT
