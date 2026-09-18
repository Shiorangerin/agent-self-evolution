#!/usr/bin/env python3
"""
evolve_trail.py —— 会话轨迹定点回查（替代整文件读取）

轨迹文件单条可达数 MB，整读会吃掉大量上下文。本脚本只按关键词抽取命中片段，
并强制限制命中条数与输出字符数，用于技能体检的失败归因、经验教训取证等场景。

用法:
  python3 evolve_trail.py <会话文件名或路径片段> [关键词 ...] [--max 30] [--chars 8000] [--snippet 160]

示例:
  python3 evolve_trail.py 2026-09-17T08-15 mkdate
  python3 evolve_trail.py ~/.pi/agent/sessions/xxx.jsonl "traceback" "execution error"

不指定关键词时只输出会话概览（记录数、角色分布、末条时间），不打印正文。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def search_roots() -> list[Path]:
    roots = []
    for env in ("SE_ROOT", "EVOLUTION_ROOT"):
        if os.environ.get(env):
            roots.append(Path(os.environ[env]).expanduser() / "sessions")
    roots += [
        Path.home() / ".pi" / "agent" / "sessions",
        Path.home() / ".claude" / "projects",
        Path.home() / ".codex" / "sessions",
    ]
    return [r for r in roots if r.exists()]


def resolve_session(arg: str) -> Path | None:
    p = Path(arg).expanduser()
    if p.is_file():
        return p
    hits: list[Path] = []
    for root in search_roots():
        hits += [f for f in root.rglob(f"*{arg}*") if f.is_file() and f.suffix in (".jsonl", ".json")]
    if not hits:
        return None
    return max(hits, key=lambda f: f.stat().st_mtime)


def role_of(obj: dict) -> str:
    msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
    return str(msg.get("role") or obj.get("type") or "?")


def time_of(obj: dict) -> str:
    ts = obj.get("timestamp") or (obj.get("message") or {}).get("timestamp") or ""
    return str(ts)[11:19] if len(str(ts)) >= 19 else ""


def main() -> int:
    ap = argparse.ArgumentParser(description="会话轨迹定点回查")
    ap.add_argument("session", help="会话文件路径或文件名片段")
    ap.add_argument("keywords", nargs="*", help="关键词，多个取并集；缺省只输出概览")
    ap.add_argument("--max", type=int, default=30, help="最多输出多少条命中记录（默认 30）")
    ap.add_argument("--chars", type=int, default=8000, help="输出字符上限（默认 8000）")
    ap.add_argument("--snippet", type=int, default=160, help="每条命中摘录长度（默认 160）")
    args = ap.parse_args()

    path = resolve_session(args.session)
    if path is None:
        roots = "、".join(str(r) for r in search_roots()) or "无可用搜索目录"
        print(f"找不到匹配的会话文件：{args.session}\n已搜索：{roots}")
        return 1

    size = path.stat().st_size
    print(f"会话: {path}\n大小: {size / 1024:.0f} KB")

    total = 0
    roles: dict[str, int] = {}
    last_time = ""
    matched = 0
    printed = 0
    used = 0
    kws = [k.lower() for k in args.keywords]

    with path.open(encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f):
            if not line.strip():
                continue
            total += 1
            try:
                obj = json.loads(line)
            except Exception:
                if not kws:
                    continue
                obj = {}
            roles[role_of(obj)] = roles.get(role_of(obj), 0) + 1
            t = time_of(obj)
            if t:
                last_time = t
            if not kws:
                continue
            text = json.dumps(obj, ensure_ascii=False) if obj else line
            low = text.lower()
            if not any(k in low for k in kws):
                continue
            matched += 1
            if printed >= args.max or used >= args.chars:
                continue
            # 取每个关键词首次命中的上下文
            pieces = []
            for k in kws:
                at = low.find(k)
                if at < 0:
                    continue
                start = max(0, at - args.snippet // 2)
                pieces.append(text[start : at + args.snippet // 2])
            piece = " … ".join(pieces) if pieces else text[: args.snippet]
            row = f"[{idx} {role_of(obj)} {t}] {piece}"
            if used + len(row) > args.chars:
                row = row[: max(0, args.chars - used)]
            print(row)
            used += len(row)
            printed += 1

    print(f"\n概览: 记录 {total} 条 | 角色 {roles}")
    if last_time:
        print(f"末条时间: {last_time}")
    if kws:
        print(f"命中: {matched} 条（关键词 {'、'.join(args.keywords)}），已输出 {printed} 条，约 {used} 字符")
        if matched > printed:
            print("命中过多，请收窄关键词或查看更具体的报错原文，不要整读轨迹文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
