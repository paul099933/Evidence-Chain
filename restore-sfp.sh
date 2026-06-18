#!/bin/bash
# restore-sfp.sh — revert 最近的 BREAK commit

set -e
cd /home/agent/.hermes/profiles/deepseek/skills/safe-file-processor

BREAK_HASH=$(git log --oneline --grep="BREAK:" -1 | awk '{print $1}')
if [ -z "$BREAK_HASH" ]; then
    echo "✅ 未找到 BREAK commit，无需恢复"
    exit 0
fi

git revert --no-edit "$BREAK_HASH"
echo "✅ BREAK commit 已 revert: $BREAK_HASH"
