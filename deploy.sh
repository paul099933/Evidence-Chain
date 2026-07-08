#!/bin/bash
# deploy.sh — 单向同步 evidence-chain 仓库 → Hermes 运行环境
#
# 用法:  ./deploy.sh          # 预览模式（dry-run）
#        ./deploy.sh --exec   # 实际执行
#
# 源: src/                     (git 仓库)
# 目标: ~/.hermes/profiles/   (Hermes profile 目录)
#       ~/.hermes/evidence-tools/
#
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
SRC="${REPO}/src"

DRY_RUN=true
if [ "${1:-}" = "--exec" ]; then
    DRY_RUN=false
fi

log()  { echo "  $*"; }
warn() { echo "  [WARN] $*" >&2; }
die()  { echo "  [FAIL] $*" >&2; exit 1; }

if $DRY_RUN; then
    echo "=== DRY RUN — 未做任何修改 ==="
    echo "  加 --exec 参数执行:  ./deploy.sh --exec"
    echo
else
    echo "=== 部署开始 ==="
fi

# ---------------------------------------------------------------------------
# 检查源文件完整性
# ---------------------------------------------------------------------------
REQUIRED=(
    "${SRC}/profiles/orchestrator/SOUL.md"
    "${SRC}/profiles/runner/SOUL.md"
    "${SRC}/profiles/fixer/SOUL.md"
    "${SRC}/profiles/verifier/SOUL.md"
    "${SRC}/profiles/orchestrator/config.yaml"
    "${SRC}/profiles/runner/config.yaml"
    "${SRC}/profiles/fixer/config.yaml"
    "${SRC}/profiles/verifier/config.yaml"
    "${SRC}/evidence-tools/run-test.sh"
)
for f in "${REQUIRED[@]}"; do
    [ -f "$f" ] || die "缺失源文件: $f"
done

# ---------------------------------------------------------------------------
# 定义复制任务: (源相对路径, 目标绝对路径)
# ---------------------------------------------------------------------------
TASKS=()

# Profile SOUL.md + config.yaml
for role in orchestrator runner fixer verifier; do
    TASKS+=("profiles/${role}/SOUL.md:${HOME}/.hermes/profiles/${role}/SOUL.md")
    TASKS+=("profiles/${role}/config.yaml:${HOME}/.hermes/profiles/${role}/config.yaml")
done


# Evidence tools
for tool in run-test.sh generate.sh feedback.sh test-sfp-desktop.sh test-runner.sh; do
    src_path="${SRC}/evidence-tools/${tool}"
    if [ -f "$src_path" ]; then
        TASKS+=("evidence-tools/${tool}:${HOME}/.hermes/evidence-tools/${tool}")
    fi
done

# Pipeline core library (imported by the plugin)
for f in $(find "${SRC}/pipeline_core" -type f -name '*.py' | sort); do
    rel="${f#${SRC}/}"
    TASKS+=("${rel}:${HOME}/.hermes/${rel}")
done

# Pipeline plugin — 部署到 deepseek profile（config 在此启用 pipeline）
TASKS+=("plugins/pipeline/__init__.py:${HOME}/.hermes/profiles/deepseek/plugins/pipeline/__init__.py")
TASKS+=("plugins/pipeline/plugin.yaml:${HOME}/.hermes/profiles/deepseek/plugins/pipeline/plugin.yaml")

# ---------------------------------------------------------------------------
# 执行 / 预览
# ---------------------------------------------------------------------------
COPIED=0
CHECKED=0
FAILED=0

for task in "${TASKS[@]}"; do
    src_rel="${task%%:*}"
    dst="${task##*:}"
    src="${SRC}/${src_rel}"

    # 跳过不存在的源文件（如 test-sfp-desktop.sh）
    [ -f "$src" ] || continue

    if $DRY_RUN; then
        printf "  cp %-50s → %s\n" "${src_rel}" "${dst}"
        continue
    fi

    # 确保目标目录存在
    mkdir -p "$(dirname "$dst")"

    # 复制
    cp "$src" "$dst"
    COPIED=$((COPIED + 1))

    # SHA 校验
    src_sha=$(sha256sum "$src" | cut -d' ' -f1)
    dst_sha=$(sha256sum "$dst" 2>/dev/null | cut -d' ' -f1 || echo "")
    if [ "$src_sha" = "$dst_sha" ]; then
        CHECKED=$((CHECKED + 1))
    else
        warn "SHA mismatch: ${src_rel} → ${dst}"
        FAILED=$((FAILED + 1))
    fi
done

# ---------------------------------------------------------------------------
# 清理尸体
# ---------------------------------------------------------------------------

# 1. Ghost deepseek/home 目录
GHOST="${HOME}/.hermes/profiles/deepseek/home"
if [ -d "$GHOST" ]; then
    if $DRY_RUN; then
        echo "  [GHOST DETECTED] rm -rf ${GHOST}"
    else
        rm -rf "$GHOST"
        log "已删除 ghost 目录: ${GHOST}"
    fi
fi

# 2. Dead orchestrator plugin copy（权威在 deepseek profile）
DEAD_PLUGIN="${HOME}/.hermes/profiles/orchestrator/plugins"
if [ -d "$DEAD_PLUGIN" ]; then
    if $DRY_RUN; then
        echo "  [DEAD COPY DETECTED] rm -rf ${DEAD_PLUGIN}"
    else
        rm -rf "$DEAD_PLUGIN"
        log "已删除 orchestrator plugin 死副本: ${DEAD_PLUGIN}"
    fi
fi

# ---------------------------------------------------------------------------
# 总结
# ---------------------------------------------------------------------------
if $DRY_RUN; then
    echo
    echo "=== DRY RUN 完成 — 共 ${#TASKS[@]} 个文件待同步 ==="
    echo "  执行 ./deploy.sh --exec 以实际部署"
else
    echo
    echo "=== 部署完成 ==="
    echo "  复制:  ${COPIED} 个文件"
    echo "  校验:  ${CHECKED}/${COPIED} SHA 匹配"
    [ "$FAILED" -gt 0 ] && warn "${FAILED} 个文件校验失败"
    echo
    echo "用 git diff 检查之后可以:"
    echo "  git tag -f v1.2  # 更新部署 tag"
fi
