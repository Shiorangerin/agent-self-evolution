#!/usr/bin/env python3
"""
evolve_finish.py —— 进化流程收尾一条命令

把原先要分四到五次工具往返完成的收尾动作合并为一次调用：
  1. 体检（默认按改动范围自动决定 quick 或 full，失败则拒绝继续）
  2. 更新 state.json（计数 + lastEvolution 快照，顺带修剪 rejections，唯一临时文件原子写入）
  3. 经验日志例行维护（超 100 数据行时归档旧条目，带去重）并追加本轮总结行
  4. git 提交数据根目录（严格校验范围，拒绝把仓库根或家目录当提交范围）

全程持有数据根目录下的排他锁，避免并发运行互相踩坏 state.json。

用法:
  python3 evolve_finish.py --candidates 0 --enabled 0 --rejected 0 --merged 0 \
      --updated 1 --repaired 0 --memory 10 [--summary "一句话"] [--dry-run]

数据根目录解析顺序：SE_ROOT → EVOLUTION_ROOT → 脚本上级目录（数据与脚本同根）→ ~/.config/agent-self-evolution
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SELF_DIR = Path(__file__).resolve().parent
CODE_HINTS = ("extensions/", "core/", "lib/")


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


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", **kw)


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json_atomic(path: Path, data: dict) -> None:
    """唯一临时文件 + fsync + rename，避免并发或崩溃写出半个 JSON。"""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def count_skills(root: Path) -> int:
    d = root / "skills"
    if not d.is_dir():
        return 0
    return sum(1 for e in d.iterdir() if e.is_dir() and not e.name.startswith("."))


def rotate_log(root: Path, keep: int = 40, limit: int = 100) -> str:
    """经验日志数据行超过 limit 时归档旧条目。归档按行去重，重复运行不会写重复行。"""
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
    header = lines[: sep + 1] if sep is not None else []
    data = [l for l in (lines[sep + 1:] if sep is not None else lines) if l.strip()]
    if len(data) <= limit:
        return f"日志 {len(data)} 行，未超 {limit}，无需归档"
    old, recent = data[:-keep], data[-keep:]
    arch = root / "logs" / "archive" / f"experience-log-{datetime.now():%Y-%m}.md"
    arch.parent.mkdir(parents=True, exist_ok=True)
    known = set()
    if arch.exists():
        known = {l for l in arch.read_text(encoding="utf-8").splitlines(keepends=True) if l.strip()}
    fresh = [l for l in old if l not in known]
    with arch.open("a", encoding="utf-8") as f:
        f.writelines(fresh)
    log.write_text("".join(header + recent), encoding="utf-8")
    dup = len(old) - len(fresh)
    return (f"日志归档 {len(fresh)} 行 → {arch.relative_to(root)}，主文件保留 {len(recent)} 行"
            + (f"（跳过已归档的重复行 {dup} 行）" if dup else ""))


def ensure_log(root: Path) -> Path:
    """日志文件缺失时补一个带表头的新文件，避免收尾直接崩在半路。"""
    log = root / "logs" / "experience-log.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    if not log.exists():
        log.write_text(
            "# 经验沉淀日志（Experience Log）\n\n"
            "> 记录每次技能沉淀的来源、结论与去向，保证可追溯。\n\n"
            "| 时间 | 来源会话 | 类型 | 摘要 | 去向 |\n"
            "| --- | --- | --- | --- | --- |\n",
            encoding="utf-8",
        )
    return log


def code_changed(root: Path) -> bool:
    """本轮是否改过扩展/核心代码：是则体检必须跑全量，避免坏代码被 --quick 放行。

    数据根不在 git 仓库内时无从判断，按未改动处理（用 --full 可强制全量）。
    """
    top = run(["git", "-C", str(root), "rev-parse", "--show-toplevel"])
    if top.returncode != 0:
        return False
    repo = Path(top.stdout.strip()).resolve()
    rel = os.path.relpath(root, repo)
    out = run(["git", "-C", str(repo), "status", "--porcelain", "--", rel])
    if out.returncode != 0:
        return True
    for line in out.stdout.splitlines():
        path = line[3:].strip().strip('"')
        if any(h in path for h in CODE_HINTS):
            return True
    return False


def git_target(root: Path) -> tuple[str, Path | None, str]:
    """返回 (状态, 仓库根, 相对路径)。

    状态取值：ok（可提交） / root（数据根等于仓库根，默认拒绍） / outside（不在仓库内）。
    """
    top = run(["git", "-C", str(root), "rev-parse", "--show-toplevel"])
    if top.returncode != 0:
        return "outside", None, ""
    repo = Path(top.stdout.strip()).resolve()
    if root == repo:
        return "root", repo, "."
    rel = os.path.relpath(root, repo)
    if rel.startswith(".."):
        return "outside", repo, rel
    return "ok", repo, rel


def main() -> int:
    ap = argparse.ArgumentParser(description="进化流程收尾一条命令")
    ap.add_argument("--candidates", type=int, default=0)
    ap.add_argument("--enabled", type=int, default=0)
    ap.add_argument("--rejected", type=int, default=0)
    ap.add_argument("--merged", type=int, default=0)
    ap.add_argument("--updated", type=int, default=0)
    ap.add_argument("--repaired", type=int, default=0)
    ap.add_argument("--memory", type=int, default=0)
    ap.add_argument("--summary", default="")
    ap.add_argument("--message", default="")
    ap.add_argument("--git-name", default="")
    ap.add_argument("--git-email", default="")
    ap.add_argument("--full", action="store_true", help="强制全量体检")
    ap.add_argument("--no-healthcheck", action="store_true")
    ap.add_argument("--no-commit", action="store_true")
    ap.add_argument("--force-commit", action="store_true", help="体检失败也照常写入与提交")
    ap.add_argument("--allow-repo-root", action="store_true",
                    help="允许数据根目录等于仓库根（默认拒绝，防止把整个仓库或家目录加进提交）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = resolve_root()
    if not (root / "state.json").exists():
        print(f"找不到 {root}/state.json，请设置 SE_ROOT 或 EVOLUTION_ROOT 后重试")
        return 1

    lock_path = root / ".evolve.lock"
    lock_file = lock_path.open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"另一个进化收尾正在运行（锁 {lock_path}），本次退出以免写坏 state.json")
        return 3

    now = datetime.now()
    stamp, log_stamp = now.strftime("%Y-%m-%dT%H:%M:%S"), now.strftime("%Y/%m/%d %H:%M:%S")
    summary = args.summary or (
        f"审查{args.candidates}候选：启用{args.enabled}/淘汰{args.rejected}/并入{args.merged}；"
        f"更新技能{args.updated}；记忆+{args.memory}"
    )
    message = args.message or f"self-evolve: {log_stamp} 进化——{summary}"
    print(f"数据根: {root}")

    # ---- 1. 体检（先于任何写入，失败即中止，不留半完成状态）----
    hc_failed = False
    if args.no_healthcheck:
        print("healthcheck: 已跳过（--no-healthcheck）")
    else:
        hc = sibling(root, "healthcheck.sh")
        if hc is None:
            print("healthcheck: 找不到 healthcheck.sh，跳过")
        else:
            full = args.full or code_changed(root)
            cmd = ["bash", str(hc)] + ([] if full else ["--quick"])
            proc = run(cmd, env=dict(os.environ, SE_ROOT=str(root)))
            tail = [l for l in proc.stdout.strip().splitlines() if l.strip()][-3:]
            print("healthcheck " + ("全量" if full else "--quick") + ": " + " / ".join(tail))
            hc_failed = proc.returncode != 0
    if hc_failed and not args.force_commit:
        print("体检未通过，已中止：未改写 state.json、未写日志、未提交。"
              "确认无误时用 --force-commit 强制收尾。")
        return 2

    # ---- 2. state.json ----
    state = load_json(root / "state.json")
    stats = state.setdefault("stats", {})
    actual = count_skills(root)
    before = (stats.get("skillsEnabled"), stats.get("evolutions", 0), stats.get("skillsUpdated", 0))
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
        "at": stamp, "candidatesReviewed": args.candidates, "enabled": args.enabled,
        "rejected": args.rejected, "merged": args.merged, "skillsUpdated": args.updated,
        "skillsRepaired": args.repaired, "memoryAdded": args.memory,
    }
    pruned = 0
    if len(state.get("rejections", [])) > 20:
        pruned = len(state["rejections"]) - 10
        state["rejections"] = state["rejections"][-10:]

    print(f"state.json: skillsEnabled {before[0]} → {actual} | evolutions {before[1]} → {stats['evolutions']}"
          f" | skillsUpdated {before[2]} → {stats['skillsUpdated']}"
          + (f" | 修剪 rejections {pruned} 条" if pruned else ""))
    print(f"日志行: | {log_stamp} | - | 进化 | {summary} | - |")

    if args.dry_run:
        print("（dry-run：未写入 state.json 与日志、未提交）")
        return 0

    # ---- 3. 日志 + state 落盘 ----
    print(f"日志维护: {rotate_log(root)}")
    log_path = ensure_log(root)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"| {log_stamp} | - | 进化 | {summary} | - |\n")
    write_json_atomic(root / "state.json", state)

    # ---- 4. git 提交（严格校验范围）----
    if args.no_commit:
        print("git: 已跳过（--no-commit）")
        return 0
    target = git_target(root)
    status, repo, rel = target
    if status == "outside":
        print("git: 数据根目录不在 git 仓库内，跳过提交")
        return 0
    if status == "root":
        if not args.allow_repo_root:
            print("git: 数据根目录等于仓库根，拒绝自动提交（否则会把整个仓库甚至家目录加进暂存区）；"
                  "请把数据根放到子目录，或确认后用 --allow-repo-root")
            return 0
        print("!! 警告：数据根目录等于仓库根，将提交该仓库全部改动")
    preview = run(["git", "-C", str(repo), "status", "--porcelain", "--", rel]).stdout.strip()
    n = len([l for l in preview.splitlines() if l.strip()])
    print(f"git 提交范围: {repo} / {rel}（{n} 项改动）")
    ident = []
    if args.git_name:
        ident += ["-c", f"user.name={args.git_name}"]
    if args.git_email:
        ident += ["-c", f"user.email={args.git_email}"]
    run(["git", "-C", str(repo), "add", "--", rel])
    commit = run(["git", *ident, "-C", str(repo), "commit", "-q", "-m", message])
    if commit.returncode != 0:
        print(f"git: 没有需要提交的改动或提交失败：{(commit.stderr or commit.stdout).strip()[:200]}")
        return 0
    print("git: " + run(["git", "-C", str(repo), "log", "-1", "--oneline"]).stdout.strip())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("已中断")
        sys.exit(130)
    except Exception as exc:  # 任何异常都要看得见，不能静默半完成
        print(f"收尾失败：{type(exc).__name__}: {exc}")
        sys.exit(1)
