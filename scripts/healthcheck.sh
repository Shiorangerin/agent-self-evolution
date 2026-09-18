#!/usr/bin/env bash
# agent-self-evolution 一键体检：核心脚本编译 / 候选预检 / 技能治理记分卡 / 流程引用完整性
#
# 用法:
#   bash scripts/healthcheck.sh           # 全量（核心脚本有改动时用）
#   bash scripts/healthcheck.sh --quick   # 只跑候选预检、记分卡与引用完整性（日常收尾用）
#
# 可用 SE_ROOT 指定数据根目录。任何一项失败即退出码 1。

set -u
SE_ROOT="${SE_ROOT:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL_UNIT="platforms/pi/skills/self-evolve/SKILL.md"
fail=0
QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

echo "== 1/4 核心脚本编译 =="
if [ "$QUICK" = "1" ]; then
	echo "已跳过（--quick：核心脚本未改动）"
elif [ ! -d "$ROOT/core" ]; then
	echo "✗ 找不到 $ROOT/core"; fail=1
else
	for f in "$ROOT"/core/*.py; do
		if python3 -m py_compile "$f" 2>/dev/null; then echo "✓ $(basename "$f")"; else echo "✗ $(basename "$f")"; fail=1; fi
	done
fi

echo "== 2/4 候选区预检 =="
DATA_ROOT="${SE_ROOT:-$HOME/.config/agent-self-evolution}"
if [ ! -f "$DATA_ROOT/state.json" ]; then
	echo "数据目录尚未初始化（${DATA_ROOT}），跳过预检与记分卡（先运行 install.sh 或 core/init.py）"
	SKIP_DATA=1
else
	SKIP_DATA=0
	if python3 "$ROOT/scripts/candidate_preflight.py"; then :; else fail=1; fi
fi

# rg 缺失时回退 grep -E，避免小结静默取不到
if command -v rg >/dev/null 2>&1; then
	match() { rg "$@"; }
else
	match() { grep -E "$@"; }
fi

echo "== 3/4 技能治理记分卡（小结）=="
if [ "$SKIP_DATA" = "1" ]; then
	echo "已跳过（数据目录未初始化）"
elif SC_OUT="$(python3 "$ROOT/scripts/skill_scorecard.py" 2>&1)"; then
	echo "$SC_OUT" | tail -1
else
	echo "✗ 记分卡运行失败"; fail=1
fi

echo "== 4/4 流程文档与脚本引用完整性 =="
SKILL_FILE=""
for cand in "$ROOT/$SKILL_UNIT" "$HOME/.pi/agent/skills/self-evolve/SKILL.md"; do
	[ -f "$cand" ] && SKILL_FILE="$cand" && break
done
if [ -z "$SKILL_FILE" ]; then
	echo "未找到进化流程技能文件，跳过（仓库内应为 ${SKILL_UNIT}）"
else
	miss=0
	refs="$(rg -o --no-filename '\$SE_ROOT/(docs|scripts)/[A-Za-z0-9_.-]+' "$SKILL_FILE" | sort -u)"
	if [ -z "$refs" ]; then
		echo "未发现 \$SE_ROOT 形式的文档或脚本引用，跳过（文件：${SKILL_FILE}）"
	fi
	for ref in $refs; do
		rel="${ref#\$SE_ROOT/}"
		# 运行期位置：数据根目录；仓库位置：docs/flow 与 scripts
		repo_rel="$rel"
		case "$rel" in docs/*) repo_rel="docs/flow/${rel#docs/}" ;; esac
		if [ -f "$ROOT/$rel" ]; then
			echo "✓ $rel"
		elif [ -f "$ROOT/$repo_rel" ]; then
			echo "✓ ${rel}（仓库中为 ${repo_rel}，安装后就位）"
		else
			echo "✗ 引用缺失：$ref"; miss=1
		fi
	done
	[ "$miss" = "1" ] && fail=1
fi

[ "$fail" -eq 0 ] && { echo ""; echo "体检全部通过 ✓"; } || { echo ""; echo "存在失败项 ✗"; exit 1; }
