Evidence-Chain 产品愿景完整规划
1. 产品定位
Evidence-Chain 是一个自然语言驱动的自动化测试-修复循环系统。
核心目标：用户用日常语言描述"测什么、优化方向、验收标准"，系统在隔离环境中自动执行测试、捕获真实证据、失败时修复、循环重测，直到验收通过。
2. 核心设计原则
原则	含义
自然语言优先	用户只说意图和预期行为，Agent 翻译为执行计划
Agent 受限自主	Agent 是翻译官和执行器，不是出题人或决策者
通用框架	不限定技术栈，任何可验证的项目都能接入
物理证据	所有测试必须留下 SHA-256 + JUnit XML + evidence.json
隔离执行	Runner/Verifier/Fixer 各自在独立 worktree 中工作
3. 用户交互范式
标准入口：完全自然语言（A）
"测一下 SFP 的文件迁移功能，确保空文件和不存在文件都被拒绝，最多允许 0 个失败。"
Orchestrator 解析为：
- 测试内容：sfp-in 正常迁移、空文件拒绝、不存在文件拒绝
- 验收标准：max_failed = 0
- 优化方向：如有失败，从 sfp-in 入手修复
精确控制入口：半结构化（B）
"测试场景：T1=sfp-in 正常迁移，T2=sfp-in 文件不存在必须返回 MIGRATE_FAIL。验收：max_failed=0。"
仅在用户需要精确控制时使用，不强制。
4. 核心循环流程
用户自然语言输入
    ↓
Orchestrator 解析意图 → 生成执行计划 + Scope
    ↓
创建 Runner task
    ↓
Runner 在 worktree 中执行测试 → 生成 evidence
    ↓
创建 Verifier task
    ↓
Verifier 按用户标准验收
    ↓
┌─────────────┬─────────────┐
│   通过      │   失败      │
│  cleanup    │  创建 Fixer │
│  保留 branch│  修复代码   │
└─────────────┴──────┬──────┘
                     ↓
              创建新 Runner task
                     ↓
                   循环
5. 四大 Agent 职责
Agent	角色	能做什么
Orchestrator	需求翻译	把用户语言翻译成测试计划、Scope、验收标准
Runner	测试执行	在 worktree 中执行测试、生成 JUnit XML、计算 SHA-256
Verifier	证据验收	按 Scope 中的标准分层验收、决定 pass/fail
Fixer	代码修复	在范围和方向约束内修改代码、commit、创建新 Runner
6. 通用性边界
通用性 = 任何有代码、有行为可验证的项目都能接入。
框架不关心：
- 项目语言（Python/Node/Go/Shell 均可）
- 测试框架（pytest/jest/go test/自定义命令 均可）
- 项目类型（SFP、记忆点系统、求职系统等均可）
框架只关心通用流程：
用户定义测试 → Agent 隔离执行 → 证据链验收 → 循环修复
7. 证据链机制
每次测试必须产生：
文件	作用
report.xml	JUnit XML，机器可读测试结果
output.log	原始 stdout/stderr
evidence.json	结构化证据：sha256、passed、failed、errors、skipped、timestamp、tests[]
~/.hermes/evidence-archive/${TASK_ID}/	持久化归档，防销毁
证据权威来源：
- 短期：Kanban DB 的 task_runs.metadata
- 长期：~/.hermes/evidence-archive/
8. 安全与隔离
机制	目的
git worktree	每个 Agent 独立工作目录，防止交叉污染
SHA-256	证明测试真实跑过，非 Agent 编造
Scope 约束	allow_edit / deny_edit / max_diff_lines 限制 Fixer
Verifier 独立	写代码的不能给自己发合格证
关键控制点摘要	用户看到 Fixer 改了什么、当前 retry 次数
9. 明确不支持的行为
为了坚持产品定位，以下行为被禁止：
- Agent 擅自创建用户未要求的测试场景
- Agent 擅自决定修复策略或扩大修复范围
- Agent 跳过测试直接声称"已修复"
- Agent 销毁或篡改 evidence 文件
- 用户需要写 YAML/shell/结构化脚本才能使用
10. 成功指标
指标	定义
自然语言启动率	用户用纯语言成功启动测试循环的比例
新项目接入成本	新项目接入是否需要修改框架代码 → 目标：0 修改
证据完整率	每次 Runner 执行是否生成了完整 evidence → 目标：100%
循环收敛率	失败 → 修复 → 通过的成功率
用户专注度	用户是否只需关注"测什么"和"怎么算过"