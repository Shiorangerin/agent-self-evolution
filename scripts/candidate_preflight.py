#!/usr/bin/env python3
"""候选技能审查预检脚本（进化流程第二步的机械检查自动化）

对 evolution/candidates/ 下每个候选做一键体检：
  ① 格式：首行 --- / frontmatter 闭合 / name 合法且与目录一致 / description 存在
  ② 大小：SKILL.md ≤ 8000 字符
  ③ 截断启发式：代码围栏不闭合、尾部中断于标点（LESSONS 2026-08-17 截断坑）
  ④ 查重：name 与已启用技能完全同名；description 高相似度提示

刻意只用标准库 + 正则解析 frontmatter，绝不 import yaml
（brew python 无 pyyaml，见 LESSONS 2026-08-16）。
输出仅供参考：预检通过不代表值得启用，价值评估与启用决策仍由人工进化审查决定。

用法：python3 candidate_preflight.py [候选目录名 ...]   # 缺省检查全部
"""

import difflib
import os
import re
import sys
from pathlib import Path

SE_ROOT = Path(os.environ.get("SE_ROOT", Path.home() / ".config" / "agent-self-evolution"))
CANDIDATES_DIR = SE_ROOT / "candidates"
SKILLS_DIR = SE_ROOT / "skills"
MAX_SKILL_CHARS = 8000

# 尾部以这些字符结尾且不以正常收束符结尾 → 疑似被 maxTokens 剪断
TRUNC_TAILS = ("→", "：", ":", "、", "，", "；", "-", "|", "*", "(", "（", "【", "《", "…")
OK_TAILS = ("。", "）", ")", "」", "】", "》", '"', "`")


def enabled_skills() -> dict[str, str]:
    """已启用技能 {name: description前80字}（正则解析，不用 yaml）"""
    out: dict[str, str] = {}
    if not SKILLS_DIR.exists():
        return out
    for d in sorted(SKILLS_DIR.iterdir()):
        f = d / "SKILL.md"
        if not f.exists():
            continue
        text = f.read_text(errors="replace")[:3000]
        m = re.search(r'^name\s*:\s*["\']?([^"\'\r\n]+)["\']?\s*$', text, re.M)
        desc = re.search(r"^description\s*:\s*(.+)$", text, re.M)
        out[(m.group(1).strip() if m else d.name)] = desc.group(1).strip()[:80] if desc else ""
    return out


def check_candidate(cand: Path, enabled: dict[str, str]) -> tuple[list[str], list[str]]:
    """返回 (issues, warnings)；issues=硬伤（对应淘汰/修复），warnings=需人工确认"""
    issues: list[str] = []
    warns: list[str] = []

    sk = cand / "SKILL.md"
    if not sk.exists():
        return ["缺少 SKILL.md"], []
    if not (cand / "meta.md").exists():
        warns.append("缺少 meta.md（来源记录缺失）")

    raw = sk.read_text(errors="replace")
    lines = raw.splitlines()

    # ① 格式
    if not lines or lines[0].strip() != "---":
        issues.append("首行非 ---（frontmatter 缺失）")
        fm_body: list[str] = []
    else:
        fm_end = None
        for i, l in enumerate(lines[1:], 1):
            if l.strip() == "---":
                fm_end = i
                break
        if fm_end is None:
            issues.append("frontmatter 未闭合（无第二个 ---）")
            fm_body = []
        else:
            fm_body = lines[1:fm_end]

    name = None
    has_desc = False
    for l in fm_body:
        m = re.match(r'^name\s*:\s*["\']?([^"\'\r\n]+)["\']?\s*$', l)
        if m:
            name = m.group(1).strip()
        if re.match(r"^description\s*:\s*\S", l):
            has_desc = True
    if name is None:
        issues.append("缺 name 字段")
    elif not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        issues.append(f"name 含非法字符（须小写字母数字连字符）: {name}")
    if not has_desc:
        issues.append("缺 description 字段")

    # ② 大小
    size = len(raw)
    if size > MAX_SKILL_CHARS:
        issues.append(f"超长 {size} > {MAX_SKILL_CHARS} 字符")

    # ③ 截断启发式
    if raw.count("```") % 2:
        issues.append("代码围栏不闭合（疑似截断）")
    nonempty = [l.rstrip() for l in lines if l.strip()]
    if nonempty:
        last = nonempty[-1]
        if last.endswith(TRUNC_TAILS) and not last.endswith(OK_TAILS):
            warns.append(f"尾部疑似截断: …{last[-30:]}")

    # 目录名一致性
    if name and cand.name != name:
        warns.append(f"目录名 {cand.name} ≠ name {name}")

    # ④ 查重
    desc = ""
    for l in fm_body:
        m2 = re.match(r"^description\s*:\s*(.+)$", l)
        if m2:
            desc = m2.group(1).strip()
            break
    if name and name in enabled:
        issues.append(f"与已启用技能完全同名: {name}")
    else:
        best_name, best_ratio = None, 0.0
        best_desc, best_desc_ratio = None, 0.0
        for ename, edesc in enabled.items():
            ratio = difflib.SequenceMatcher(None, name, ename).ratio()
            if ratio > best_ratio:
                best_name, best_ratio = ename, ratio
            if desc and edesc:
                dr = difflib.SequenceMatcher(None, desc[:300], edesc[:300]).ratio()
                if dr > best_desc_ratio:
                    best_desc, best_desc_ratio = ename, dr
        if best_ratio >= 0.8:
            warns.append(f"name 与已启用技能 {best_name} 高相似（{best_ratio:.0%}），人工判断是否同源")
        if best_desc_ratio >= 0.55:
            warns.append(f"description 与已启用技能 {best_desc} 相似度 {best_desc_ratio:.0%}，人工判断是否语义重复（零 token 预查，最终以人工审读为准）")

    return issues, warns


def main() -> int:
    targets = sys.argv[1:]
    if not CANDIDATES_DIR.exists():
        print("candidates 目录不存在")
        return 1
    dirs = sorted(d for d in CANDIDATES_DIR.iterdir() if d.is_dir() and not d.name.startswith("."))
    if targets:
        dirs = [d for d in dirs if d.name in targets]
    if not dirs:
        print("候选区为空，无需预检 ✓")
        return 0

    enabled = enabled_skills()
    total_issues = 0
    print(f"候选预检：{len(dirs)} 个候选 | 已启用技能 {len(enabled)} 个\n")
    for cand in dirs:
        issues, warns = check_candidate(cand, enabled)
        total_issues += len(issues)
        status = "✅ 通过" if not issues else "❌ 有硬伤"
        print(f"== {cand.name} — {status}")
        for msg in issues:
            print(f"   [硬伤] {msg}")
        for msg in warns:
            print(f"   [警示] {msg}")
        if not issues and not warns:
            print("   （机械检查全部通过，待人工价值评估）")
    print(f"\n小结：{len(dirs)} 个候选，{total_issues} 个硬伤。硬伤须修复或淘汰；警示项人工复核。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
