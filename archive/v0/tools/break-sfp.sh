#!/bin/bash
# break-sfp.sh — 提交一个 BREAK commit 到 main
# 验证修复循环用

set -e
SFP_IN="/home/agent/.hermes/profiles/deepseek/skills/safe-file-processor/scripts/sfp-in"

# 检查是否已有 BREAK commit
cd /home/agent/.hermes/profiles/deepseek/skills/safe-file-processor
if git log --oneline -1 | grep -q "BREAK:"; then
    echo "⚠️ 已有 BREAK commit 存在，跳过"
    exit 0
fi

# 注入 bug：移除文件不存在检查
python3 -c "
p = 'scripts/sfp-in'
with open(p) as f: c = f.read()
c = c.replace(
    '''if [ ! -e \"\$SOURCE\" ]; then
    echo \"MIGRATE_FAIL: reason=\\\\\"文件不存在\\\\\" path=\\\\\"\$1\\\\\"\"
    exit 1
fi''',
    '''# BUG-INJECTED: file existence check removed
echo \"MIGRATE_FAIL_BUG: reason=\\\\\"文件不存在\\\\\" path=\\\\\"\$1\\\\\"\"
exit 0'''
)
with open(p, 'w') as f: f.write(c)
"

git add scripts/sfp-in
git commit -m "BREAK: disable file existence check in sfp-in (test fix-loop)"

echo "✅ BREAK commit 已提交"
echo "   修复循环: hermes -p orchestrator -z '调 pipeline_start ...'"
