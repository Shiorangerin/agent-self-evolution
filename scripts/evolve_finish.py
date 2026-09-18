#!/usr/bin/env python3
"""
evolve_finish.py —— 进化流程收尾一条命令

把原先要分四到五次工具往返完成的收尾动作合并为一次调用：
  1. 更新 state.json（计数 + lastEvolution 快照，顺带修剪 rejections）
  2. 经验日志例行维护（超 100 数据行时归档旧条目）并追加本轮总结行
  3. 运行 healthcheck（默认 --quick）
  4. git 提交数据根目录（不在 git 仓库内则跳过）

只接受显式参数，不做任何猜测；--dry-run 可先看计划。

用法:
  python3 evolve_finish.py --candidates 0 --enabled 0 --rejected 0 --merged 0 \
      --updated 1 --repaired 0 --memory 10 [--summary "一句话"] [--full] [--dry-run]

数据根目录解析顺序：SE_ROOT → EVOLUTION_ROOT → 脚本上级目录（数据与脚本同根）→ ~/.config/agent-self-evolution
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SELF_DIR = Path(__file__).resolve().parent


def resolve_root() -> Path:
    for env in ("SE_ROOT", "EVOLUTION_ROOT"):
        if os.environ.get(env):
            return Path(os.environ[env]).expanduser().resolve()
    if (SELF_DIR.parent / "state.json").exists():
        return SELF_DIR.parent.resolve()
    return (Path.home() / ".config" / "agent-self-evolution").resolve()


def sibling(root: Path, name: str) -> Path | None:
    for cand in (root / "scripts" / name, SELF_DIR / name):
        if cand.exists():
            return cand
    return None


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def count_skills(root: Path) -> int:
    d = root / "skills"
    if not d.is_dir():
        return 0
    return sum(1 for e in d.iterdir() if e.is_dir() and not e.name.startswith("."))


def rotate_log(root: Path, keep: int = 40, limit: int = 100) -> str:
    """经验日志数据行超过 limit 时，把旧条目归档到 logs/archive/，主文件只留最近 keep 条。

    表头定义为「首条仅由 | - : 空格组成的分隔行」及其之前的内容，数据行为其后的非空行。"""
    log = root / "logs" / "experience-log.md"
    if not log.exists():
        return "日志不存在，跳过维护"
    lines = log.read_text(encoding="utf-8").splitlines(keepends=True)
    sep = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("|") and set(s) <= set("|-: "):
            sep = i
            break
    if sep is None:
        header, data = [], [l for l in lines if l.strip()]
    else:
        header = lines[: sep + 1]
        data = [l for l in lines[sep + 1 :] if l.strip()]
    if len(data) <= limit:
        return f"日志 {len(data)} 行，未超 {limit}，无需归档"
    old, recent = data[:-keep], data[-keep:]
    arch = root / "logs" / "archive" / f"experience-log-{datetime.now():%Y-%m}.md"
    arch.parent.mkdir(parents=True, exist_ok=True)
    with arch.open("a", encoding="utf-8") as f:
        f.writelines(old)
    log.write_text("".join(header + recent), encoding="utf-8")
    return f"日志归档 {len(old)} 行 → {arch.relative_to(root)}，主文件保留 {len(recent)} 行"


def main() -> int:
    ap = argparse.ArgumentParser(description="进化流程收尾一条命令")
    ap.add_argument("--candidates", type=int, default=0, help="本轮审查的候选数")
    ap.add_argument("--enabled", type=int, default=0, help="新启用技能数")
    ap.add_argument("--rejected", type=int, default=0, help="淘汰候选数")
    ap.add_argument("--merged", type=int, default=0, help="并入候选数")
    ap.add_argument("--updated", type=int, default=0, help="更新的现有技能数")
    ap.add_argument("--repaired", type=int, default=0, help="修复或补注意点的技能数")
    ap.add_argument("--memory", type=int, default=0, help="新增记忆条目数")
    ap.add_argument("--summary", default="", help="日志行摘要，缺省按计数生成")
    ap.add_argument("--message", default="", help="git commit message，缺省按摘要生成")
    ap.add_argument("--git-name", default="", help="提交作者名（缺省用仓库配置）")
    ap.add_argument("--git-email", default="", help="提交作者邮箱（缺省用仓库配置）")
    ap.add_argument("--full", action="store_true", help="healthcheck 跑全部检查项（默认 --quick）")
    ap.add_argument("--no-healthcheck", action="store_true", help="跳过体检")
    ap.add_argument("--no-commit", action="store_true", help="跳过 git 提交")
    ap.add_argument("--force-commit", action="store_true", help="体检失败也照常提交")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写入")
    args = ap.parse_args()

    root = resolve_root()
    if not (root / "state.json").exists():
        print(f"找不到 {root}/state.json，请设置 SE_ROOT 或 EVOLUTION_ROOT 后重试")
        return 1

    now = datetime.now()
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S")
    log_stamp = now.strftime("%Y/%m/%d %H:%M:%S")
    summary = args.summary or (
        f"审查{args.candidates}候选：启用{args.enabled}/淘汰{args.rejected}/并入{args.merged}；"
        f"更新技能{args.updated}；记忆+{args.memory}"
    )
    message = args.message or f"self-evolve: {log_stamp} 进化——{summary}"

    # ---- 1. state.json ----
    state = load_json(root / "state.json")
    stats = state.setdefault("stats", {})
    actual = count_skills(root)
    before = {
        "skillsEnabled": stats.get("skillsEnabled"),
        "evolutions": stats.get("evolutions", 0),
        "skillsUpdated": stats.get("skillsUpdated", 0),
    }
    stats["skillsEnabled"] = actual
    stats["evolutions"] = stats.get("evolutions", 0) + 1
    stats["skillsUpdated"] = stats.get("skillsUpdated", 0) + args.updated
    if args.repaired:
        stats["skillsRepaired"] = stats.get("skillsRepaired", 0) + args.repaired
    if args.rejected:
        stats["candidatesRejected"] = stats.get("candidatesRejected", 0) + args.rejected
    if args.merged:
        stats["candidatesMerged"] = stats.get("candidatesMerged", 0) + args.merged
    state["lastEvolutionAt"] = stamp
    state["lastEvolution"] = {
        "at": stamp,
        "candidatesReviewed": args.candidates,
        "enabled": args.enabled,
        "rejected": args.rejected,
        "merged": args.merged,
        "skillsUpdated": args.updated,
        "skillsRepaired": args.repaired,
        "memoryAdded": args.memory,
    }
    pruned = 0
    if len(state.get("rejections", [])) > 20:
        pruned = len(state["rejections"]) - 10
        state["rejections"] = state["rejections"][-10:]

    print(f"数据根: {root}")
    print(
        f"state.json: skillsEnabled {before['skillsEnabled']} → {actual}"
        f" | evolutions {before['evolutions']} → {stats['evolutions']}"
        f" | skillsUpdated {before['skillsUpdated']} → {stats['skillsUpdated']}"
        + (f" | 修剪 rejections {pruned} 条" if pruned else "")
    )
    print(f"日志行: | {log_stamp} | - | 进化 | {summary} | - |")

    # ---- 2. 日志 ----
    rotate_note = rotate_log(root) if not args.dry_run else "（dry-run 未执行）"
    print(f"日志维护: {rotate_note}")
    if not args.dry_run:
        log = root / "logs" / "experience-log.md"
        with log.open("a", encoding="utf-8") as f:
            f.write(f"| {log_stamp} | - | 进化 | {summary} | - |\n")
        write_json_atomic(root / "state.json", state)

    if args.dry_run:
        print("（dry-run：未写入 state.json 与日志、未体检、未提交）")
        return 0

    # ---- 3. healthcheck ----
    hc_failed = False
    if args.no_healthcheck:
        print("healthcheck: 已跳过（--no-healthcheck）")
    else:
        hc = sibling(root, "healthcheck.sh")
        if hc is None:
            print("healthcheck: 找不到 healthcheck.sh，跳过")
        else:
            cmd = ["bash", str(hc)] + ([] if args.full else ["--quick"])
            env = dict(os.environ, SE_ROOT=str(root))
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", env=env)
            tail = [l for l in proc.stdout.strip().splitlines() if l.strip()][-4:]
            print("healthcheck " + (" ".join(cmd[2:]) or "全量") + ": " + " / ".join(tail))
            hc_failed = proc.returncode != 0

    # ---- 4. git commit ----
    if args.no_commit:
        print("git: 已跳过（--no-commit）")
        return 2 if hc_failed else 0
    if hc_failed and not args.force_commit:
        print("git: 体检未通过，已跳过提交（确认无误可用 --force-commit 强制提交）")
        return 2

    top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if top.returncode != 0:
        print("git: 数据根目录不在 git 仓库内，跳过提交")
        return 0
    repo = Path(top.stdout.strip())
    rel = os.path.relpath(root, repo)
    ident = []
    if args.git_name:
        ident += ["-c", f"user.name={args.git_name}"]
    if args.git_email:
        ident += ["-c", f"user.email={args.git_email}"]
    subprocess.run(["git", "-C", str(repo), "add", "--", rel], check=False)
    commit = subprocess.run(["git", *ident, "-C", str(repo), "commit", "-q", "-m", message],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if commit.returncode != 0:
        print(f"git: 没有需要提交的改动或提交失败：{(commit.stderr or commit.stdout).strip()[:200]}")
        return 2 if hc_failed else 0
    head = subprocess.run(["git", "-C", str(repo), "log", "-1", "--oneline"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    print(f"git: {head}")
    return 2 if hc_failed else 0


if __name__ == "__main__":
    sys.exit(main())
