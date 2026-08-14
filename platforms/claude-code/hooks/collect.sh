#!/usr/bin/env bash
# agent-self-evolution — Claude Code Stop hook 采集入口
#
# 由 Claude Code 在每次 agent 完成响应（Stop 事件）时调用：
#   stdin 收到事件 JSON（含 transcript_path / session_id / cwd 等字段）
#   1. 提取 transcript_path 与 session_id
#   2. 归一化 transcript 为统一 JSONL（normalize_claude.py）
#   3. 调用采集器 collect.py 生成技能候选
#
# 设计原则：全程容错。任何一步失败都静默退出 0，绝不阻塞 / 干扰主 agent。
set +e
set -u

SE_ROOT="${SE_ROOT:-$HOME/.config/agent-self-evolution}"
COLLECT_PY="${SE_ROOT}/core/collect.py"

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="${HOOK_DIR}/normalize_claude.py"

# 1. 读取 stdin（hook 注入的 JSON）
input="$(cat)"

# 2. 提取 transcript_path 与 session_id（单次 python 解析，逐行输出两个值）
parsed="$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
print(data.get("transcript_path") or "")
print(data.get("session_id") or "")
')"
transcript="$(printf '%s\n' "$parsed" | sed -n '1p')"
session_id="$(printf '%s\n' "$parsed" | sed -n '2p')"

# 3. transcript_path 为空或文件不存在 → 静默退出
if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
    exit 0
fi

# 4. 会话短名：优先 session_id，否则取文件名；清理为安全文件名
if [ -n "$session_id" ]; then
    short="$session_id"
else
    short="$(basename "$transcript" .jsonl)"
fi
short="$(printf '%s' "$short" | tr -c 'A-Za-z0-9._-' '_' | cut -c1-80)"

# 5. 归一化 transcript → 统一 JSONL（临时目录）
TMP_DIR="${SE_ROOT}/logs/tmp"
mkdir -p "$TMP_DIR" || exit 0
norm_file="${TMP_DIR}/${short}.jsonl"
python3 "$NORMALIZE_PY" "$transcript" > "$norm_file" 2>/dev/null || exit 0

# 6. 调用采集器（stdout 仅作日志用途）
if [ -f "$COLLECT_PY" ]; then
    python3 "$COLLECT_PY" --transcript "$norm_file" --session "$short" 2>&1
fi

# 6b. 技能使用统计（纯规则，写 usage.json，供进化流程「技能体检」使用）
TRACK_PY="${SE_ROOT}/core/track_usage.py"
if [ -f "$TRACK_PY" ]; then
    python3 "$TRACK_PY" --transcript "$norm_file" --session "$short" 2>/dev/null || true
fi

# 7. 采集失败也绝不阻塞主 agent
exit 0
