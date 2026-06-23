# Evidence-Chain

通用 Agent 驱动迭代测试框架。

用户通过自然语言描述"测什么、优化方向、验收标准"，系统在隔离环境中自动执行测试、捕获真实证据、失败时修复、循环重测，直到验收通过。

## 当前版本

v1.2 — Plugin 代码级 Pipeline（部署状态）

## 目录结构

```
evidence-chain/
  src/                     ← 唯一构建源
    profiles/              ← Kanban 角色 SOUL.md + config.yaml
    evidence-tools/        ← 测试入口脚本（run-test.sh 等）
    docs/                  ← 架构文档
  archive/                 ← 历史版本归档
    v0/
    v0/tools/              ← SFP 测试辅助脚本
  deploy.sh                ← 单向同步脚本
  README.md
```

## 快速开始

```
./deploy.sh
```

## 文档

- [产品愿景](src/docs/product-vision.md)
- [架构决策](src/docs/architecture.md)
- [版本记录](src/CHANGELOG.md)
