#!/usr/bin/env python3
"""技能记分卡：量化「谁优秀、谁差劲」，产出归档/淘汰候选清单

三维度评分（数据源 usage.json，由 track_usage.py 维护）：
  新鲜度 40 分  lastUsedAt 距今天数越近越高；无记录/标记不可信 → 0 并标「未观测」
  使用度 30 分  count 归一化（≥10 次满档）；弱信号为主减半（提及≠使用）
  可靠性 30 分  success/(success+failure)；failure≥2 且失败率>30% 直接判问题技能

分级：
  🌟 优秀   score ≥ 70 且近期真实使用且无失败嫌疑
  ✅ 健康   其余正常技能
  ⚠️ 问题   失败率高（附 failReasons，需人工复核是否假失败）
  😴 闲置   可信记录显示 ≥60 天未用 → 归档候选
  ❓ 未观测 无可信使用记录（含历史污染清洗后的观察期条目）

只读不改：本脚本绝不修改任何文件，归档/淘汰决策权在用户。
用法：python3 skill_scorecard.py [--all]   # 缺省只列非健康项，--all 列全量
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SE_ROOT = Path(os.environ.get("SE_ROOT", Path.home() / ".config" / "agent-self-evolution"))
USAGE_FILE = SE_ROOT / "usage.json"
SKILLS_DIR = SE_ROOT / "skills"
MAX_SKILL_CHARS = 8000

# 元技能豁免区：定义进化流程本身的技能。
# 淘汰/归档/自动压缩对它们一律不适用——规则不得吃掉自己的元规则；
# 超长问题仅提示，结构优化（拆分/瘦身）须用户决策后人工执行。
EXEMPT = {"self-evolve", "self-evolve-maintenance"}



IDLE_DAYS = 60          # 闲置阈值（与 self-evolve SKILL.md 体检标准一致）
FRESH_DAYS = 14         # 「近期使用」阈值
EXCELLENT_SCORE = 70    # 优秀分数线


def days_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds() / 86400
    except ValueError:
        return None


def load() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"skills": {}}


def enabled_skills() -> list[str]:
    if not SKILLS_DIR.exists():
        return []
    return sorted(
        e.name for e in SKILLS_DIR.iterdir()
        if not e.name.startswith(".") and (e / "SKILL.md").exists()
    )


def score_one(name: str, info: dict | None) -> dict:
    info = info if isinstance(info, dict) else {}
    count = info.get("count", 0)
    signal = info.get("signal", "weak")
    outcomes = info.get("outcomes") or {}
    succ = outcomes.get("success", 0)
    fail = outcomes.get("failure", 0)
    judged = succ + fail
    fail_rate = fail / judged if judged else 0.0
    days = days_since(info.get("lastUsedAt"))
    unreliable = bool(info.get("recencyUnreliable")) or days is None

    sk_file = SKILLS_DIR / name / "SKILL.md"
    size = sk_file.stat().st_size if sk_file.exists() else 0

    # --- 三维度打分 ---
    # 新鲜度 40：≤3 天 40 分，线性衰减到 IDLE_DAYS 归零
    if unreliable:
        freshness = 0.0
    elif days <= 3:
        freshness = 40.0
    elif days >= IDLE_DAYS:
        freshness = 0.0
    else:
        freshness = 40.0 * (1 - (days - 3) / (IDLE_DAYS - 3))
    # 使用度 30：count ≥10 满档；弱信号为主按一半计（提及≠使用）
    usage = min(count / 10, 1.0) * 30.0
    if signal == "weak":
        usage *= 0.5
    # 可靠性 30：判定样本不足给及格线 15，避免新技能被冤枉
    reliability = 15.0 if judged < 2 else 30.0 * (succ / judged)
    total = round(freshness + usage + reliability)

    # --- 分级（硬规则优先于分数）---
    notes = []
    grade = "✅ 健康"
    if name in EXEMPT:
        grade = "🛡️ 元技能"
        notes.append("流程定义文件：豁免闲置归档与自动压缩")
        if size > MAX_SKILL_CHARS:
            notes.append(f"超长 {size} > {MAX_SKILL_CHARS}：结构优化须用户决策，不自动执行")
    elif fail >= 2 and fail_rate > 0.3:
        grade = "⚠️ 问题"
        notes.append(f"失败率 {fail_rate:.0%}（{fail}/{judged}），复核 failReasons 是否假失败")
    elif unreliable:
        grade = "❓ 未观测"
        notes.append("无可信使用时间（观察期，等待修复后的扩展重新积累）")
    elif days is not None and days >= IDLE_DAYS:
        grade = "😴 闲置"
        notes.append(f"{days:.0f} 天未用 → 归档候选")
    elif total >= EXCELLENT_SCORE and days is not None and days <= FRESH_DAYS and fail == 0:
        grade = "🌟 优秀"
    if signal == "weak" and count >= 10:
        notes.append("弱信号高频：可能只是常被提及，从未真读（count 含水分）")
    if size > MAX_SKILL_CHARS and grade != "🛡️ 元技能":
        notes.append(f"超长 {size} > {MAX_SKILL_CHARS} 字符，列入压缩候选")

    return {
        "name": name, "grade": grade, "total": total,
        "count": count, "days": days, "signal": signal,
        "succ": succ, "fail": fail, "fail_rate": fail_rate,
        "size": size, "notes": notes,
        "failReasons": (info.get("failReasons") or [])[:2],
    }


def main() -> int:
    show_all = "--all" in sys.argv[1:]
    usage = load().get("skills", {})
    rows = [score_one(n, usage.get(n)) for n in enabled_skills()]
    order = {"⚠️ 问题": 0, "😴 闲置": 3, "❓ 未观测": 4, "🌟 优秀": 5, "✅ 健康": 6}
    rows.sort(key=lambda r: (order[r["grade"]], -r["total"]))

    shown = rows if show_all else [r for r in rows if r["grade"] != "✅ 健康"]
    print(f"技能记分卡：启用 {len(rows)} 个 | 显示 {'全量' if show_all else '非健康项'}\n")
    for r in shown:
        d = f"{r['days']:.0f}天前" if r["days"] is not None else "无记录"
        print(f"{r['grade']} {r['total']:>3}分  {r['name']}  "
              f"[{r['signal'][:1]}信号 {r['count']}次 / 最近 {d} / 失败{r['fail']}]")
        for n in r["notes"]:
            print(f"        - {n}")
        for fr in r["failReasons"]:
            print(f"        · {fr[:80]}")

    archive = [r["name"] for r in rows if r["grade"] == "😴 闲置"]
    problem = [r["name"] for r in rows if r["grade"] == "⚠️ 问题"]
    from collections import Counter
    cnt = Counter(r["grade"] for r in rows)
    labels = ["🌟 优秀", "✅ 健康", "❓ 未观测", "⚠️ 问题", "😴 闲置", "🛡️ 元技能"]
    print("\n小结：" + " / ".join(f"{lab} {cnt.get(lab, 0)}" for lab in labels))
    if archive:
        print("\n归档候选（逐项征求用户决策后才可执行，绝不自行删除）：")
        for n in archive:
            print(f"  - {n}")
    if problem:
        print("\n问题技能（人工复核假失败后再定处置）：")
        for n in problem:
            print(f"  - {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
