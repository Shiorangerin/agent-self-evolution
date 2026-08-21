#!/usr/bin/env bash
# agent-self-evolution 一键体检：核心编译 / 候选预检 / 技能治理记分卡
# 用法：bash scripts/healthcheck.sh   （可用 SE_ROOT 指定数据根目录）
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fail=0

echo "== 1/3 核心脚本编译 =="
for f in "$ROOT"/core/*.py; do
	if python3 -m py_compile "$f" 2>/dev/null; then echo "✓ $(basename "$f")"; else echo "✗ $(basename "$f")"; fail=1; fi
done

echo "== 2/3 候选区预检 =="
if python3 "$ROOT/scripts/candidate_preflight.py"; then :; else fail=1; fi

echo "== 3/3 技能治理记分卡（小结）=="
if SC_OUT="$(python3 "$ROOT/scripts/skill_scorecard.py" 2>&1)"; then
	echo "$SC_OUT" | tail -1
else
	echo "✗ 记分卡运行失败"; fail=1
fi

[ "$fail" -eq 0 ] && { echo ""; echo "体检全部通过 ✓"; } || { echo ""; echo "存在失败项 ✗"; exit 1; }
