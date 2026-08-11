#!/usr/bin/env python3
"""
agent-self-evolution — 经验采集器（平台无关核心）

每次 agent 运行结束（由各平台适配器的 hook 触发）时，后台轻量分析本次会话轨迹：
- 统计工具调用次数、错误修复次数
- 满足触发条件（工具调用 ≥5 次 / 出现错误并修复）时，
  用低成本 LLM 调用草拟一份 SKILL.md 候选，写入 <SE_ROOT>/candidates/
- 候选区不进入运行上下文，待用户手动触发「进化流程」时审查启用

设计原则：
- 采集完全被动：本脚本只负责安静地记录候选，不做任何自动唤醒 / 定时触发。
- 增量采集：同一会话可多次采集，每次只分析上次采集点之后的新内容（按 transcript 行数记录），
  长程对话也不漏；被节流挡住的只会延迟、不会丢失。
- 省 token：轨迹摘要截断、低推理强度、输出预算受限；所有失败静默处理并记录原因。
- 零第三方依赖：仅用 Python 标准库（python3 ≥ 3.8）。

LLM 后端选择（按优先级）：
1. 环境变量 SE_LLM_CMD   —— 用户自定义命令，用 {prompt} 占位符传入提示词
2. claude CLI             —— `claude -p`（复用 Claude Code 登录态）
3. codex CLI              —— `codex exec`（复用 Codex 登录态）
4. OpenAI 兼容 API        —— SE_API_BASE / SE_API_KEY / SE_API_MODEL

用法（一般由平台 hook 调用，也可手动执行）：
  collect.py --transcript <jsonl 路径> --session <会话名> [--force]
  collect.py --transcript <路径> --session <名> --offset <行数> --toolcalls N --errors N --summary <文本>
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------

SE_ROOT = Path(os.environ.get("SE_ROOT", Path.home() / ".config" / "agent-self-evolution"))
CANDIDATES_DIR = SE_ROOT / "candidates"
SKILLS_DIR = SE_ROOT / "skills"
LOGS_DIR = SE_ROOT / "logs"
MEMORY_DIR = SE_ROOT / "memory"
STATE_FILE = SE_ROOT / "state.json"
USAGE_FILE = SE_ROOT / "usage.json"
LOG_FILE = LOGS_DIR / "experience-log.md"
REJECTED_DRAFTS_DIR = LOGS_DIR / "rejected-drafts"

MIN_TOOL_CALLS = int(os.environ.get("SE_MIN_TOOL_CALLS", "5"))   # 工具调用触发阈值
MAX_CANDIDATES = int(os.environ.get("SE_MAX_CANDIDATES", "20"))  # 候选区堆积上限
MAX_TRACE_CHARS = int(os.environ.get("SE_MAX_TRACE_CHARS", "2500"))
MAX_OUTPUT_TOKENS = int(os.environ.get("SE_MAX_OUTPUT_TOKENS", "2000"))
THROTTLE_MS = int(os.environ.get("SE_THROTTLE_MS", "0"))          # 默认关闭节流（增量采集不丢数据）

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower())
    slug = re.sub(r"^-+|-+$", "", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:60] or "untitled-skill"


def read_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"stats": {"sessionsAnalyzed": 0, "candidatesCreated": 0}}


def write_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def append_log(line: str) -> None:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def record_rejection(state: dict, session: str, reason: str) -> None:
    rejections = state.get("rejections") or []
    rejections.append({
        "at": now_iso(),
        "session": session,
        "reason": reason[:300],
    })
    state["rejections"] = rejections[-20:]


def save_draft_dump(session: str, tool_calls: int, errors: int, raw: str, extra: str = "") -> str:
    try:
        REJECTED_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REJECTED_DRAFTS_DIR / f"{int(time.time() * 1000)}.md"
        path.write_text(
            f"# 被拒草稿（{now_iso()}）\n"
            f"来源会话: {session}\n"
            f"工具调用: {tool_calls} 次 / 错误: {errors} 次\n"
            f"{('备注: ' + extra + chr(10)) if extra else ''}"
            f"--- 以下为 LLM 原始输出 ---\n\n{raw or '（空）'}",
            encoding="utf-8",
        )
        return str(path)
    except Exception:
        return ""


def list_enabled_skills() -> list:
    """读取已启用技能清单（name + 一句话描述），供查重。"""
    skills = []
    if not SKILLS_DIR.is_dir():
        return skills
    for entry in sorted(SKILLS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.is_file():
            continue
        try:
            content = skill_file.read_text(encoding="utf-8")[:3000]
        except Exception:
            continue
        name_m = re.search(r"^name\s*:\s*[\"']?([^\"'\r\n]+)[\"']?\s*$", content, re.M)
        desc_m = re.search(r"^description\s*:\s*(.+)$", content, re.M)
        name = name_m.group(1).strip() if name_m else entry.name
        desc = re.sub(r"\s+", " ", desc_m.group(1).strip())[:120] if desc_m else ""
        skills.append({"name": name, "desc": desc})
    return skills


# ---------------------------------------------------------------------------
# 轨迹解析（各平台 transcript 的差异在平台 hook 里归一化，这里只接收统一格式）
# ---------------------------------------------------------------------------

def parse_transcript(path: str, offset: int = 0) -> tuple:
    """
    解析统一 JSONL 轨迹。每行格式（平台 hook 负责归一化）：
      {"role": "user"|"assistant"|"toolResult"|"bashExecution",
       "text": "...",            # 文本内容
       "toolCall": {"name": "...", "args": {...}}  # assistant 工具调用
       "isError": bool,          # toolResult 是否错误
       "command": "..."}         # bashExecution 命令
    返回 (新行数, 用户请求列表, 工具调用数, 错误数, 轨迹摘要文本)
    """
    user_parts, bash_parts, error_parts = [], [], []
    tool_calls = 0
    errors = 0
    lines = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return offset, [], 0, 0, f"（无法读取轨迹: {e}）"

    new_lines = lines[offset:] if offset > 0 else lines
    for line in new_lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        role = e.get("role", "")
        text = (e.get("text") or "").strip()
        if role == "user":
            if text and not text.startswith("/"):
                user_parts.append(text[:300])
        elif role == "assistant":
            tc = e.get("toolCall")
            if tc:
                tool_calls += 1
                name = (tc.get("name") or "").lower()  # 平台工具名大小写不一（Bash/bash），统一小写匹配
                args = tc.get("args") or {}
                if name in ("bash", "bash_command", "command"):
                    cmd = str(args.get("command") or args.get("cmd") or "")
                    if cmd:
                        bash_parts.append(cmd[:200])
                elif name in ("edit", "write", "read"):
                    p = str(args.get("path") or "")
                    if p:
                        bash_parts.append(f"{name} {p}")
            if text:
                bash_parts.append(text[:200])
        elif role == "toolResult":
            if e.get("isError"):
                errors += 1
                error_parts.append(text[:400])
        elif role == "bashExecution":
            cmd = e.get("command")
            if cmd and not e.get("cancelled"):
                bash_parts.append(cmd[:200])

    lines_out = []
    if user_parts:
        lines_out.append("【用户请求】\n" + "\n".join(user_parts[-5:]))
    if bash_parts:
        lines_out.append("【执行操作】\n" + "\n".join(bash_parts[-25:]))
    if error_parts:
        lines_out.append("【出现的错误】\n" + "\n---\n".join(error_parts[-3:]))
    summary = "\n\n".join(lines_out)[:MAX_TRACE_CHARS]
    return len(lines), user_parts, tool_calls, errors, summary


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------

def build_prompt(summary: str, tool_calls: int, errors: int) -> str:
    skills_block = ""
    enabled = list_enabled_skills()
    if enabled:
        lines = ["【已启用技能清单（查重参考）】以下技能已存在于系统中："]
        lines += [f"- {s['name']}：{s['desc']}" if s["desc"] else f"- {s['name']}" for s in enabled]
        lines.append("若本次轨迹与其中任何一个语义重复（同类流程/同类场景/同类坑点），必须输出 SKIP: 与已有技能 <name> 重复，禁止重复生成。")
        skills_block = "\n".join(lines)

    return "\n".join([
        "你是「agent-self-evolution 经验采集器」。根据下面这次任务的执行轨迹，判断是否值得沉淀为一个可复用的技能（SKILL.md）。",
        "",
        "值得沉淀的标准（至少满足一条）：",
        "1. 这类任务以后会重复出现（部署、排错、特定工具链、特定流程、多步骤操作）",
        "2. 轨迹里有明确的步骤、经验、坑点可以复用",
        "3. 不是一次性的琐碎问答或闲聊",
        "",
        skills_block,
        "",
        "输出格式（严格遵守，不要输出其他内容）：",
        "- 如果值得沉淀：直接输出完整 SKILL.md 全文，不要用代码块包裹，不要加任何解释。",
        "- frontmatter 必须以此开头：第一行 --- ，第二行必须是 name: <小写字母数字连字符>（不带引号，冒号后直接跟值），第三行 description: <中文，≤1024字符，写明『何时使用』>，最后一行 --- 结束。",
        "- 正文用中文，包含适用场景、步骤流程、常见坑点与修复方法；总长 ≤ 5000 字符。",
        "- 如果不值得沉淀：只输出一行，以 SKIP: 开头并说明原因。",
        "- 如果与已启用技能清单中的技能语义重复：必须输出 SKIP: 与已有技能 <name> 重复（严禁重复生成）。",
        "",
        "执行轨迹如下：",
        "---",
        summary,
        "---",
    ])


def call_llm(prompt: str) -> str:
    """按优先级调用 LLM 后端，返回原始输出文本。"""
    env = os.environ

    # 1. 自定义命令
    custom = env.get("SE_LLM_CMD")
    if custom:
        cmd = custom.replace("{prompt}", prompt)
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
        if out.returncode == 0:
            return out.stdout.strip()
        raise RuntimeError(f"SE_LLM_CMD 退出码 {out.returncode}: {out.stderr[:200]}")

    # 2. claude CLI
    if _which("claude"):
        out = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=600,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
        raise RuntimeError(f"claude CLI 失败（{out.returncode}）: {out.stderr[:200]}")

    # 3. codex CLI（prompt 用 `-` 从 stdin 读，避免多行参数问题）
    if _which("codex"):
        out = subprocess.run(
            ["codex", "exec", "--full-auto", "-C", str(Path.cwd()), "-"],
            input=prompt, capture_output=True, text=True, timeout=600,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
        raise RuntimeError(f"codex CLI 失败（{out.returncode}）: {out.stderr[:200]}")

    # 4. OpenAI 兼容 API
    api_base = env.get("SE_API_BASE")
    api_key = env.get("SE_API_KEY")
    api_model = env.get("SE_API_MODEL")
    if api_base and api_key and api_model:
        import urllib.request
        body = json.dumps({
            "model": api_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": MAX_OUTPUT_TOKENS,
        }).encode("utf-8")
        req = urllib.request.Request(
            api_base.rstrip("/") + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (data["choices"][0]["message"]["content"] or "").strip()

    raise RuntimeError(
        "未找到可用的 LLM 后端：请设置 SE_LLM_CMD，或安装 claude/codex CLI，或配置 SE_API_BASE/SE_API_KEY/SE_API_MODEL"
    )


def _which(name: str) -> bool:
    from shutil import which
    return which(name) is not None


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def collect(transcript: str, session: str, offset: int = None,
            tool_calls: int = None, errors: int = None, summary: str = None, force: bool = False) -> str:
    state = read_state()
    state.setdefault("stats", {})

    # 增量采集：offset 未显式指定时，自动从上次记录位置继续
    if offset is None:
        offset = state.get("collectedUpTo", {}).get(session, 0)

    # 候选区堆积检查
    try:
        candidate_count = len(list(CANDIDATES_DIR.iterdir())) if CANDIDATES_DIR.is_dir() else 0
    except Exception:
        candidate_count = 0
    if candidate_count >= MAX_CANDIDATES:
        return f"候选区已满（{candidate_count} 个），请先运行进化流程审查"

    # 全局节流
    if not force and THROTTLE_MS > 0:
        last = state.get("lastCollectionAt")
        if last:
            try:
                last_ts = datetime.fromisoformat(last).timestamp() * 1000
                if time.time() * 1000 - last_ts < THROTTLE_MS:
                    wait_min = int((THROTTLE_MS - (time.time() * 1000 - last_ts)) / 60000)
                    return f"节流中（{wait_min} 分钟后可再触发）"
            except Exception:
                pass

    # 解析轨迹（未显式传参时）
    if summary is None or tool_calls is None or errors is None:
        offset, _, tc, er, sm = parse_transcript(transcript, offset)
        tool_calls = tool_calls if tool_calls is not None else tc
        errors = errors if errors is not None else er
        summary = sm if summary is None else summary
    if not summary or not summary.strip():
        return "会话无可分析内容"

    state["stats"]["sessionsAnalyzed"] = state["stats"].get("sessionsAnalyzed", 0) + 1

    # 触发条件
    if tool_calls < MIN_TOOL_CALLS and errors == 0:
        _advance(state, session, offset, transcript)
        write_state(state)
        return f"条件不满足（工具调用 {tool_calls} 次、无错误），不值得调用 LLM"

    # 草拟候选
    prompt = build_prompt(summary, tool_calls, errors)
    try:
        raw = call_llm(prompt)
    except Exception as e:
        # 暂时性失败（后端缺失/网络/超时）：不推进采集点，修复后可重试补采
        reason = f"LLM 调用异常: {str(e)[:200]}"
        state["stats"]["candidatesRejected"] = state["stats"].get("candidatesRejected", 0) + 1
        state["lastCollectionAt"] = now_iso()
        record_rejection(state, session, reason)
        write_state(state)
        append_log(f"| {now_local()} | {session} | 采集失败 | {reason[:100]} | - |")
        return f"❌ {reason}"

    if not raw:
        # 暂时性失败：不推进采集点，可重试
        reason = "LLM 返回空内容"
        state["stats"]["candidatesRejected"] = state["stats"].get("candidatesRejected", 0) + 1
        state["lastCollectionAt"] = now_iso()
        record_rejection(state, session, reason)
        write_state(state)
        append_log(f"| {now_local()} | {session} | 采集失败 | {reason} | - |")
        return f"❌ {reason}"

    # SKIP 处理
    if raw.startswith("SKIP:"):
        reason = raw[5:].strip() or "未提供原因"
        state["lastCollectionAt"] = now_iso()
        state["stats"]["candidatesRejected"] = state["stats"].get("candidatesRejected", 0) + 1
        record_rejection(state, session, reason)
        _advance(state, session, offset, transcript)
        write_state(state)
        append_log(f"| {now_local()} | {session} | 拒绝沉淀 | {reason[:100]} | - |")
        return f"拒绝沉淀: {reason}"

    # 解析 name
    raw_clean = re.sub(r"```(?:ya?ml|markdown)?\s*", "", raw).strip()
    name_m = re.search(r"^name\s*:\s*[\"']?([^\"'\r\n]+)[\"']?\s*$", raw_clean, re.M)
    name = name_m.group(1).strip() if name_m else ""
    slug = slugify(name or "untitled-skill")

    def reject(reason: str) -> str:
        draft = save_draft_dump(session, tool_calls, errors, raw, reason)
        state["stats"]["candidatesRejected"] = state["stats"].get("candidatesRejected", 0) + 1
        state["lastCollectionAt"] = now_iso()
        record_rejection(state, session, f"{reason}{'（原始草稿已存: ' + draft + '）' if draft else ''}")
        _advance(state, session, offset, transcript)
        write_state(state)
        append_log(f"| {now_local()} | {session} | 拒绝沉淀 | {reason[:100]} | - |")
        return f"❌ {reason}"

    if not name:
        return reject("LLM 草稿缺少合法 name（frontmatter 格式不符）")

    # 代码层查重保险丝
    if any(s["name"] == slug for s in list_enabled_skills()):
        return reject(f"与已启用技能 {slug} 完全同名（查重拦截，LLM 未遵守查重规则）")

    # 写入候选
    try:
        target = CANDIDATES_DIR / slug
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_text(raw, encoding="utf-8")
        (target / "meta.md").write_text(
            "\n".join([
                "---",
                f"candidate-source-session: {session}",
                f"candidate-tool-calls: {tool_calls}",
                f"candidate-errors: {errors}",
                f"candidate-created: {now_iso()}",
                "---",
                "",
            ]), encoding="utf-8",
        )
    except Exception as e:
        return f"❌ 写入候选失败: {str(e)[:200]}"

    state["stats"]["candidatesCreated"] = state["stats"].get("candidatesCreated", 0) + 1
    state["lastCollectionAt"] = now_iso()
    _advance(state, session, offset, transcript)
    write_state(state)
    append_log(f"| {now_local()} | {session} | 候选生成 | 工具{tool_calls}次/错误{errors}次 → {slug} | candidates/{slug}/ |")
    return f"🎉 已生成候选技能: {slug}（工具{tool_calls}次/错误{errors}次）"


def _advance(state: dict, session: str, offset: int, transcript: str) -> None:
    """推进采集位置（增量采集核心）。offset=0 表示已读完全部行。"""
    collected = state.setdefault("collectedUpTo", {})
    collected[session] = offset if offset > 0 else _line_count(transcript)


def _line_count(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="agent-self-evolution 经验采集器")
    parser.add_argument("--transcript", required=True, help="统一 JSONL 轨迹文件路径")
    parser.add_argument("--session", required=True, help="会话标识（文件名即可）")
    parser.add_argument("--offset", type=int, default=None, help="上次已处理的行数（缺省自动从 state.json 读取）")
    parser.add_argument("--toolcalls", type=int, default=None, help="工具调用次数（缺省自动统计）")
    parser.add_argument("--errors", type=int, default=None, help="错误次数（缺省自动统计）")
    parser.add_argument("--summary", default=None, help="轨迹摘要（缺省自动生成）")
    parser.add_argument("--force", action="store_true", help="强制采集（跳过 busy 检查）")
    args = parser.parse_args()

    result = collect(
        transcript=args.transcript,
        session=args.session,
        offset=args.offset,
        tool_calls=args.toolcalls,
        errors=args.errors,
        summary=args.summary,
        force=args.force,
    )
    print(result)


if __name__ == "__main__":
    main()
