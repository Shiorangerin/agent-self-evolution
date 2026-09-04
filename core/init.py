#!/usr/bin/env python3
"""
agent-self-evolution — 数据目录初始化

创建 <SE_ROOT>（默认 ~/.config/agent-self-evolution/）的完整目录结构与初始文件：
  candidates/   候选技能区（采集器写入，进化流程审查）
  profiles/     用户画像草稿区（采集器写入，进化流程提炼进 USER.md）
  skills/       已启用技能源文件
  memory/       长期记忆（USER.md 用户画像 / LESSONS.md 踩坑经验）
  logs/         经验日志、每日总结、被拒草稿
  state.json    系统状态与统计
  usage.json    技能使用统计

幂等：已存在的文件不会覆盖。
"""

import json
import os
import shutil
import sys
from pathlib import Path

SE_ROOT = Path(os.environ.get("SE_ROOT", Path.home() / ".config" / "agent-self-evolution"))
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

STRUCTURE = [
    "candidates",
    "profiles",
    "skills",
    "memory",
    "logs/session-summaries",
    "logs/archive",
]


def copy_template(name: str, dest: Path) -> None:
    src = TEMPLATES_DIR / name
    if not src.exists():
        print(f"  ! 模板缺失: {src}", file=sys.stderr)
        return
    if not dest.exists():
        shutil.copyfile(src, dest)
        print(f"  ✓ {dest.relative_to(SE_ROOT)}")


def main() -> None:
    print(f"初始化数据目录: {SE_ROOT}")
    for d in STRUCTURE:
        (SE_ROOT / d).mkdir(parents=True, exist_ok=True)
    print("  ✓ 目录结构已就绪")

    copy_template("state.json", SE_ROOT / "state.json")
    copy_template("usage.json", SE_ROOT / "usage.json")
    copy_template("experience-log.md", SE_ROOT / "logs" / "experience-log.md")
    copy_template("LESSONS.md", SE_ROOT / "memory" / "LESSONS.md")
    copy_template("USER.md", SE_ROOT / "memory" / "USER.md")

    # 填充 state.json 的创建时间
    state_file = SE_ROOT / "state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if state.get("createdAt") == "INIT_TIME":
                from datetime import datetime
                state["createdAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
                state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    print("完成。下一步：")
    print("  1. 安装平台适配器（见 platforms/<平台>/README.md）")
    print("  2. 手动运行一次: python3 core/collect.py --transcript <轨迹文件> --session test --force 验证 LLM 后端")


if __name__ == "__main__":
    main()
