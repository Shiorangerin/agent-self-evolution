#!/usr/bin/env bash
# agent-self-evolution — Codex Stop hook 入口
#
# 由 Codex hooks（~/.codex/config.toml 的 [[hooks.Stop]] 事件）在每次任务结束时调用。
# stdin 收到事件 JSON（含 session_id / cwd / hook_event_name，部分版本含 transcript_path）：
#
#   1. 读取 stdin，提取 transcript_path / session_id / cwd
#   2. 按优先级定位本次会话的 transcript 文件
#   3. 归一化为统一 JSONL（normalize_codex.py）→ $SE_ROOT/logs/tmp/<会话短名>.jsonl
#   4. 调用 core/collect.py 增量采集，满足条件时草拟 SKILL.md 候选
#   5. 结果输出到 stdout
#
# 全脚本容错：任何一步失败都静默退出 0，绝不阻塞 agent 任务。

SE_ROOT="${SE_ROOT:-$HOME/.config/agent-self-evolution}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECT_PY="${SE_ROOT}/core/collect.py"

# 1. 读取 stdin 并提取字段（输入可能为空或非法 JSON，全部容错）
input="$(cat 2>/dev/null || true)"
meta="$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    if not isinstance(d, dict):
        d = {}
except Exception:
    d = {}
print(d.get("transcript_path") or "")
print(d.get("session_id") or "")
print(d.get("cwd") or "")
' 2>/dev/null || true)"
transcript_path="$(printf '%s\n' "$meta" | sed -n '1p')"
session_id="$(printf '%s\n' "$meta" | sed -n '2p')"
# cwd 当前未使用，保留提取以备后续扩展
cwd="$(printf '%s\n' "$meta" | sed -n '3p')"

# 2. 定位 transcript（按优先级）
transcript=""
if [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
    transcript="$transcript_path"
elif [ -n "$session_id" ]; then
    transcript="$(find "$HOME/.codex/sessions" -name "*${session_id}*.jsonl" 2>/dev/null | head -1)"
fi
if [ -z "$transcript" ]; then
    # 兜底：最近 10 分钟内修改过的会话文件
    transcript="$(find "$HOME/.codex/sessions" -name "*.jsonl" -mmin -10 2>/dev/null | head -1)"
fi
if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
    exit 0
fi

# 会话短名：优先用 session_id，否则用文件名（不含扩展名）
short="$(printf '%s' "${session_id:-}" | tr -c 'a-zA-Z0-9_-' '-' | cut -c1-80)"
if [ -z "$short" ]; then
    short="$(basename "$transcript" .jsonl | tr -c 'a-zA-Z0-9_-' '-' | cut -c1-80)"
fi
if [ -z "$short" ]; then
    short="codex-session"
fi

# 3. 归一化 → $SE_ROOT/logs/tmp/<短名>.jsonl
tmp_out="${SE_ROOT}/logs/tmp/${short}.jsonl"
if ! mkdir -p "$(dirname "$tmp_out")" 2>/dev/null; then
    exit 0
fi
if ! python3 "$SCRIPT_DIR/normalize_codex.py" "$transcript" > "$tmp_out" 2>/dev/null; then
    exit 0
fi

# 4. 增量采集（collect.py 自动处理 offset）
#    Codex 0.147 的 Stop hook 会解析 stdout；默认静默，调试时可设置 SE_HOOK_VERBOSE=1
if [ ! -f "$COLLECT_PY" ]; then
    exit 0
fi
if [ -n "${SE_HOOK_VERBOSE:-}" ]; then
    python3 "$COLLECT_PY" --transcript "$tmp_out" --session "$short" 2>/dev/null || true
else
    python3 "$COLLECT_PY" --transcript "$tmp_out" --session "$short" >/dev/null 2>/dev/null || true
fi

# 4b. 技能使用统计（纯规则，写 usage.json，供进化流程「技能体检」使用）
TRACK_PY="${SE_ROOT}/core/track_usage.py"
if [ -f "$TRACK_PY" ]; then
    python3 "$TRACK_PY" --transcript "$tmp_out" --session "$short" >/dev/null 2>/dev/null || true
fi

# 5. 采集失败绝不阻塞 agent
exit 0
