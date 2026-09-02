#!/usr/bin/env python3
"""
agent-self-evolution — Codex transcript → 统一 JSONL 归一化器

读取 Codex CLI 会话轨迹（argv[1]，JSONL），输出统一 JSONL 到 stdout。
统一格式是 core/collect.py 唯一能解析的协议，每行一个 JSON：

  {"role": "user", "text": "..."}
  {"role": "assistant", "text": "..."}
  {"role": "assistant", "toolCall": {"name": "...", "args": {...}}}
  {"role": "toolResult", "isError": true, "text": "..."}

兼容新旧两代 Codex transcript 结构（v0.14x 前后并存，同一文件里也可能混用）：

- 新式：{"type": "response_item", "payload": {"type": "message", "role": ..., "content": [...]}}
  content block 类型：input_text / output_text / tool_call / tool_result
  payload.type 也可能是 function_call / custom_tool_call / tool_result / reasoning
- 旧式：{"type": "message", "message": {"role": ..., "content": [...]}}
  content block 类型：text / tool_use / tool_result

处理规则：
- role=developer 的文本属于系统注入，跳过，不计入用户请求
- reasoning（payload.type == "reasoning"）跳过
- session_meta / event_msg / world_state / turn_context / agent_message 等其他行跳过
- tool_call 的 arguments 可能是对象或字符串 JSON：字符串先尝试 json.loads，失败则原样保留字符串
- tool_result 的 isError 取自 is_error；content 可能是字符串或数组，数组则提取其中各块的 text
- 逐行 try/except：任何单行解析失败都跳过该行，绝不抛异常；保持行顺序

用法：
  python3 normalize_codex.py <codex-transcript.jsonl> > unified.jsonl
"""

import json
import sys


# ---------------------------------------------------------------------------
# 文本提取
# ---------------------------------------------------------------------------

def text_of(block):
    """从 content block / 字符串 / 数组 中宽容提取文本。"""
    if block is None:
        return ""
    if isinstance(block, str):
        return block
    if isinstance(block, list):
        parts = []
        for item in block:
            t = text_of(item)
            if t:
                parts.append(t)
        return "\n".join(parts)
    if isinstance(block, dict):
        t = block.get("text")
        if t is None:
            t = block.get("content")  # 部分版本的 tool_result 内容嵌在 content 字段里
        return text_of(t)
    return ""


def emit(out, **fields):
    try:
        out.write(json.dumps(fields, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 工具调用 / 工具结果
# ---------------------------------------------------------------------------

def tool_call_of(block):
    """从 tool_call / function_call / custom_tool_call 提取 {name, args}。"""
    name = block.get("name") or ""
    args = block.get("arguments")
    if args is None:
        args = block.get("args")
    if args is None:
        args = block.get("input")
    if isinstance(args, str):
        try:
            args = json.loads(args)  # arguments 可能是字符串 JSON
        except Exception:
            args = {"input": args}  # 解析失败时包一层，避免下游把字符串当 dict
    if args is None:
        args = {}
    return {"name": name, "args": args}


def emit_tool_result(out, block):
    text = text_of(block.get("content"))
    if not text.strip():
        return
    emit(out, role="toolResult", isError=bool(block.get("is_error")), text=text)


def emit_call_output(out, item):
    """兼容新式 function_call_output / custom_tool_call_output。"""
    text = text_of(item.get("output") or item.get("content"))
    if not text.strip():
        return
    emit(out, role="toolResult", isError=False, text=text)


# ---------------------------------------------------------------------------
# 新式结构：{"type": "response_item", "payload": {...}}
# ---------------------------------------------------------------------------

def handle_new_message(payload, out):
    """新式 message：role + content blocks（可混含文本与工具调用/结果）。"""
    role = payload.get("role", "")
    blocks = payload.get("content") or []
    if not isinstance(blocks, list):
        return
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype in ("input_text", "output_text"):
            text = (block.get("text") or "").strip()
            if not text or role == "developer":
                continue  # developer 为系统注入，跳过
            if role == "user":
                emit(out, role="user", text=text)
            elif role == "assistant":
                emit(out, role="assistant", text=text)
        elif btype == "tool_call":
            emit(out, role="assistant", toolCall=tool_call_of(block))
        elif btype == "tool_result":
            emit_tool_result(out, block)
        elif btype == "function_call_output":
            emit_call_output(out, block)
        elif btype == "custom_tool_call_output":
            emit_call_output(out, block)


def handle_new_payload(payload, out):
    ptype = payload.get("type")
    if ptype == "message":
        handle_new_message(payload, out)
    elif ptype in ("function_call", "custom_tool_call"):
        emit(out, role="assistant", toolCall=tool_call_of(payload))
    elif ptype in ("function_call_output", "custom_tool_call_output"):
        emit_call_output(out, payload)
    elif ptype == "tool_result":
        emit_tool_result(out, payload)
    else:
        # reasoning / session_meta / event_msg / world_state /
        # turn_context / agent_message 等：内容可跳过
        pass


# ---------------------------------------------------------------------------
# 旧式结构：{"type": "message", "message": {"role": ..., "content": [...]}}
# ---------------------------------------------------------------------------

def handle_old_message(msg, out):
    role = msg.get("role", "")
    blocks = msg.get("content")
    if isinstance(blocks, str):
        # 极少数版本 content 直接是字符串
        text = blocks.strip()
        if not text or role == "developer":
            return
        if role == "user":
            emit(out, role="user", text=text)
        elif role == "assistant":
            emit(out, role="assistant", text=text)
        return
    if not isinstance(blocks, list):
        return
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = (block.get("text") or "").strip()
            if not text or role == "developer":
                continue
            if role == "user":
                emit(out, role="user", text=text)
            elif role == "assistant":
                emit(out, role="assistant", text=text)
        elif btype == "tool_use":
            emit(out, role="assistant",
                 toolCall={"name": block.get("name") or "", "args": block.get("input") or {}})
        elif btype == "tool_result":
            emit_tool_result(out, block)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        sys.stderr.write("用法: normalize_codex.py <transcript.jsonl>\n")
        sys.exit(1)
    path = sys.argv[1]
    try:
        f = open(path, "r", encoding="utf-8", errors="replace")
    except OSError as e:
        sys.stderr.write(f"normalize_codex: 无法读取 {path}: {e}\n")
        sys.exit(1)

    out = sys.stdout
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    continue
                payload = entry.get("payload")
                if isinstance(payload, dict):
                    handle_new_payload(payload, out)
                elif isinstance(entry.get("message"), dict):
                    handle_old_message(entry["message"], out)
                # 其他未知行类型：跳过
            except Exception:
                continue
    out.flush()


if __name__ == "__main__":
    main()
