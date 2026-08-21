#!/usr/bin/env python3
"""
agent-self-evolution — 技能使用统计（平台无关核心，纯规则零 LLM 成本）

给启用技能补上「使用反馈回路」。每次 agent 运行结束（由各平台 hook 触发）时，
用纯规则扫描本次会话的统一 JSONL 轨迹，记录哪些技能被「疑似使用」，
并对强信号技能做「结果归因」（成功/失败/未知），数据写入 <SE_ROOT>/usage.json，
供进化流程报告「长期未使用技能」与「问题技能」给用户决定处置。

本脚本是 Pi 平台 skill-usage.ts 扩展的 Python 等价实现，供
Claude Code / Codex 等无法加载 TS 扩展的平台在 hook 中调用。

信号定义（启发式，仅供参考，最终决策权在用户）：
- 强信号：轨迹中读取/触碰了 <SE_ROOT>/skills/<name> 路径（如 read <name>/SKILL.md）
- 弱信号：技能 slug（如 brew-cleanup-optimize）出现在轨迹文本中（用户消息/助手文本/工具参数）

结果归因（仅对强信号技能，弱信号不归因——可能只是闲聊提及）：
- 只统计「技能文件第一次被读取之后」的错误与用户反馈，避免误伤
- 失败信号：该位置之后出现 isError；或该位置之后用户最后一条消息含负面语义
- 成功信号：该位置之后无任何错误，且用户最后消息含正面语义
- 其余情况：unknown（不强行判定）
- 判定是启发式，可能误判；进化时需回读原始轨迹复核

同一会话去重：按会话短名记录，同一会话多次触发只计数一次。
所有失败静默处理，绝不阻塞主 agent。

用法（一般由平台 hook 调用）：
  track_usage.py --transcript <统一 JSONL 路径> --session <会话短名>
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

SE_ROOT = Path(os.environ.get("SE_ROOT", Path.home() / ".config" / "agent-self-evolution"))
USAGE_FILE = SE_ROOT / "usage.json"
SKILLS_DIR = SE_ROOT / "skills"

# 负面语义词表（启发式：用于结果归因的失败信号，进化时人工复核）
NEGATIVE_WORDS = [
    "失败", "不行", "没用", "还是错", "不对", "坏了", "算了", "放弃", "不弄",
    "崩溃", "打不开", "报错", "出错", "卡住", "没成功", "搞不定", "解决不了",
    "有问题", "假的", "骗人", "没有用", "白费", "退回", "删了吧",
]

# 正面语义词表（启发式：用于结果归因的成功信号）
POSITIVE_WORDS = [
    "好了", "搞定", "成功", "可以了", "能用了", "完美", "感谢", "谢谢",
    "赞", "没问题", "行了", "完成", "好用", "厉害", "棒", "nice", "great",
]

# 审查/盘点类会话的强信号阈值：一次性批量读取大量 SKILL.md 时跳过结果归因
ATTRIBUTION_SKIP_STRONG_HITS = 5


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def list_skill_names() -> list:
    """读取已启用技能 slug 列表（<SE_ROOT>/skills/<name>/SKILL.md 存在才计入）。"""
    names = []
    if not SKILLS_DIR.is_dir():
        return names
    try:
        for entry in sorted(SKILLS_DIR.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if (entry / "SKILL.md").is_file():
                names.append(entry.name)
    except Exception:
        pass
    return names


def read_usage() -> dict:
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"updatedAt": None, "skills": {}}


def write_usage(usage: dict) -> None:
    try:
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(usage, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def entry_text(e: dict) -> str:
    """提取单条 entry 的全部文本（用于定位技能文件被读取的位置）。"""
    parts = []
    role = e.get("role", "")
    if role in ("user", "assistant"):
        text = e.get("text")
        if text:
            parts.append(str(text))
        tc = e.get("toolCall")
        if isinstance(tc, dict):
            parts.append(str(tc.get("name") or ""))
            try:
                parts.append(json.dumps(tc.get("args") or {}, ensure_ascii=False))
            except Exception:
                pass
    elif role == "toolResult":
        text = e.get("text")
        if text:
            parts.append(str(text))
    elif role == "bashExecution":
        cmd = e.get("command")
        if cmd:
            parts.append(str(cmd))
    return "\n".join(parts)


def build_trace_text(entries: list) -> str:
    """收集本次会话轨迹的全部文本（用户消息 + 助手文本 + 工具调用名/参数）。"""
    parts = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        role = e.get("role", "")
        if role == "user":
            text = (e.get("text") or "").strip()
            if text and not text.startswith("/"):
                parts.append(text)
        elif role == "assistant":
            text = (e.get("text") or "").strip()
            if text:
                parts.append(text)
            tc = e.get("toolCall")
            if isinstance(tc, dict):
                parts.append(str(tc.get("name") or ""))
                try:
                    parts.append(json.dumps(tc.get("args") or {}, ensure_ascii=False))
                except Exception:
                    pass
    return "\n".join(parts)


def judge_outcome(entries: list, from_index: int) -> tuple:
    """
    结果归因：只看 [from_index..] 的轨迹（技能文件被读取之后）。
    @returns (outcome, reasons)：outcome ∈ success/failure/unknown；failure 时附原因（最多 3 条）
    """
    has_error = False
    reasons = []
    last_user_text = ""

    for e in entries[from_index:]:
        if not isinstance(e, dict):
            continue
        role = e.get("role", "")
        if role == "toolResult" and e.get("isError"):
            has_error = True
            t = (e.get("text") or "").strip()[:200]
            if t and len(reasons) < 3:
                reasons.append(t)
        elif role == "user":
            t = (e.get("text") or "").strip()
            if t and not t.startswith("/"):
                last_user_text = t

    if has_error:
        return "failure", reasons
    if last_user_text:
        if any(w in last_user_text for w in NEGATIVE_WORDS):
            return "failure", [f"用户反馈: {last_user_text[:100]}"]
        if any(w in last_user_text for w in POSITIVE_WORDS):
            return "success", []
    return "unknown", []


def track(transcript: str, session: str) -> str:
    """扫描统一 JSONL 轨迹，更新 usage.json。"""
    skill_names = list_skill_names()
    if not skill_names:
        return "无已启用技能"

    entries = []
    try:
        with open(transcript, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        return f"无法读取轨迹: {e}"
    if not entries:
        return "会话无可分析内容"

    text = build_trace_text(entries)
    if not text.strip():
        return "会话无可分析内容"

    usage = read_usage()
    skills = usage.get("skills") or {}

    # 补齐旧条目缺失的 outcomes/failReasons（防止进化体检 KeyError）
    for key in list(skills.keys()):
        s = skills[key]
        if not isinstance(s, dict):
            continue
        if not isinstance(s.get("outcomes"), dict):
            s["outcomes"] = {"success": 0, "failure": 0, "unknown": 0}
        if not isinstance(s.get("failReasons"), list):
            s["failReasons"] = []

    # 先统计强信号技能数量：进化审查/盘点类会话会批量读取大量 SKILL.md，
    # 之后会话内任何无关错误都不该被归因到单个技能，故跳过结果归因。
    strong_hits = 0
    for slug in skill_names:
        for e in entries:
            if f"skills/{slug}/SKILL.md" in entry_text(e) or f"skills/{slug}/" in entry_text(e):
                strong_hits += 1
                break
    # 盘点/审查类会话只是批量读取技能做体检，不代表任务使用：
    # 计数、lastUsedAt、归因全部跳过，防止 count 膨胀与 lastUsedAt 污染
    if strong_hits >= ATTRIBUTION_SKIP_STRONG_HITS:
        return f"盘点/审查类会话（强信号 {strong_hits} 个技能被批量读取），跳过记录"

    hit = 0
    for slug in skill_names:
        prev = skills.get(slug)
        if prev and prev.get("lastSession") == session:
            continue  # 会话去重

        # 强信号：定位技能文件路径第一次出现的 entry 位置（用于结果归因）
        strong_index = -1
        for i, e in enumerate(entries):
            t = entry_text(e)
            if f"skills/{slug}/SKILL.md" in t or f"skills/{slug}/" in t:
                strong_index = i
                break
        strong = strong_index >= 0
        weak = (not strong) and slug in text

        if strong or weak:
            entry = {
                "count": (prev.get("count", 0) if prev else 0) + 1,
                "lastUsedAt": now_iso(),
                "lastSession": session,
                "signal": "strong" if strong else "weak",
                "outcomes": (prev.get("outcomes") if prev else None)
                or {"success": 0, "failure": 0, "unknown": 0},
                "failReasons": (prev.get("failReasons") if prev else None) or [],
            }
            # 结果归因：仅强信号技能（真读取了技能文件），且非审查/盘点类会话
            if strong:
                outcome, reasons = judge_outcome(entries, strong_index)
                entry["outcomes"][outcome] = entry["outcomes"].get(outcome, 0) + 1
                if reasons:
                    entry["failReasons"] = (entry["failReasons"] + reasons)[-3:]
            skills[slug] = entry
            hit += 1

    if hit == 0:
        return "无技能使用信号"
    usage["updatedAt"] = now_iso()
    usage["skills"] = skills
    write_usage(usage)
    return f"已记录 {hit} 个技能使用信号"


def main() -> None:
    parser = argparse.ArgumentParser(description="agent-self-evolution 技能使用统计")
    parser.add_argument("--transcript", required=True, help="统一 JSONL 轨迹文件路径")
    parser.add_argument("--session", required=True, help="会话短名（用于去重）")
    args = parser.parse_args()
    try:
        print(track(args.transcript, args.session))
    except Exception as e:
        print(f"采集异常: {str(e)[:200]}")
        sys.exit(0)


if __name__ == "__main__":
    main()
