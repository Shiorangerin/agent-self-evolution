#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agent-self-evolution — Claude Code transcript 归一化器

把 Claude Code 的会话 transcript（JSONL，绝对路径作为 argv[1]）转换为
统一的 JSONL 协议（collect.py 唯一能解析的格式），逐行输出到 stdout。

统一 JSONL 协议（每行一个 JSON）：
  {"role":"user","text":"..."}
  {"role":"assistant","text":"..."}
  {"role":"assistant","toolCall":{"name":"Bash","args":{"command":"..."}}}
  {"role":"toolResult","isError":true,"text":"..."}
  {"role":"bashExecution","command":"...","cancelled":false}

Claude Code transcript 格式（JSONL，每行）：
  {"type":"user"|"assistant"|"system","message":{"role":"...","content":[...]},...}
  content blocks：
    {"type":"text","text":"..."}
    {"type":"tool_use","id":"...","name":"Bash","input":{"command":"..."}}
    {"type":"tool_result","tool_use_id":"...","content":"...","is_error":true}

映射规则：
  - user 文本        → user 行
  - assistant 文本   → assistant 行
  - tool_use         → toolCall 行（name 原样、args=input）
  - tool_result      → toolResult 行（isError 取 is_error，content 为数组时提取 text 拼接）
  - 其余（system 行、无法解析的行）→ 跳过

容错：所有解析全部 try/except 包裹，任何异常只跳过对应行，绝不抛出导致
hook 失败；行顺序保持不变；退出码恒为 0。

用法：
  python3 normalize_claude.py <transcript.jsonl> > unified.jsonl
"""

import json
import sys


def extract_text(content):
    """从 tool_result 的 content 提取文本：字符串直接返回；数组拼接其中 text block 的 text。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        return "\n".join(parts)
    return ""


def normalize_event(event, out):
    """把一行 transcript 事件转换为若干统一 JSONL 行，追加到 out。"""
    if not isinstance(event, dict):
        return

    # 角色判定：优先 message.role；缺失时用顶层 type（仅 user/assistant 视为角色）
    role = None
    message = event.get("message")
    if isinstance(message, dict) and message.get("role"):
        role = message.get("role")
    else:
        event_type = event.get("type")
        if event_type in ("user", "assistant"):
            role = event_type
    if not role:
        return  # system 等行，跳过

    content = message.get("content") if isinstance(message, dict) else event.get("content")

    # content 为纯字符串（个别版本变体）
    if isinstance(content, str):
        text = content.strip()
        if text:
            out.append({"role": role, "text": text})
        return

    if not isinstance(content, list):
        return

    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = (block.get("text") or "").strip()
            if text:
                out.append({"role": role, "text": text})
        elif block_type == "tool_use":
            out.append({
                "role": "assistant",
                "toolCall": {
                    "name": block.get("name") or "",
                    "args": block.get("input") or {},
                },
            })
        elif block_type == "tool_result":
            out.append({
                "role": "toolResult",
                "isError": bool(block.get("is_error")),
                "text": extract_text(block.get("content")),
            })


def main(argv):
    if len(argv) < 2:
        return 0  # 缺参数时静默输出空，不抛异常
    path = argv[1]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return 0  # 读取失败：输出空，交由上层容错

    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue  # 无法解析的行跳过
        try:
            normalize_event(event, out)
        except Exception:
            continue  # 单行处理异常不中断整体

    for obj in out:
        print(json.dumps(obj, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
