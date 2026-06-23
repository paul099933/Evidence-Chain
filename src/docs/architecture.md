# 架构决策记录

## 决策：路径 B（Plugin 代码级）而非路径 A（PROMPT 驱动）

- 日期：2026-06-14
- 状态：已采纳

### 背景
v0.1 使用 4 个 SOUL.md 协作完成 Runner→Verifier→Fixer 循环，retry 计数在 prompt 中，模型可绕过。

### 决策
采用 Hermes Plugin 机制，将循环逻辑收敛到 `plugins/evidence-chain/pipeline.py`：
- retry 计数在 Python 代码中，不可绕过
- branch 决策（pass/fail）由代码判断，非模型判断
- 单入口 `pipeline_start`，后续全自动

### 源码依据
Hermes `plugins.py:1053 discover_and_load()` 和 `registry.py:390 dispatch` 支持 Plugin 注册与同步 Polling。