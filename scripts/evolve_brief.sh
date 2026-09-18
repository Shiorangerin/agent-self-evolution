#!/usr/bin/env bash
# evolve_brief.sh —— 进化流程一次性探测
#
# 把进化流程各步需要的机械信息一次输出（状态摘要 / 候选清单 / 启用区计数与超长清单 /
# 待处理画像草稿 / 经验日志尾部 / 记分卡 / 异常提示），让整个流程只跑一次探测，
# 而不是每步各扫一遍。只读脚本，不修改任何文件。
#
# 用法:
#   bash scripts/evolve_brief.sh                # 全量
#   bash scripts/evolve_brief.sh --no-scorecard # 跳过记分卡（已单独跑过时）
#   bash scripts/evolve_brief.sh --candidates   # 只看候选区详情
#
# 数据根目录按此顺序确定：SE_ROOT → EVOLUTION_ROOT → 脚本上级目录（数据与脚本同根时）→
# 公共默认 ~/.config/agent-self-evolution。

set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-/usr/bin/python3}"
[ -x "$PY" ] || PY="python3"

if [ -n "${SE_ROOT:-}" ]; then
  ROOT="$SE_ROOT"
elif [ -n "${EVOLUTION_ROOT:-}" ]; then
  ROOT="$EVOLUTION_ROOT"
elif [ -f "$SELF_DIR/../state.json" ]; then
  ROOT="$(cd "$SELF_DIR/.." && pwd)"
else
  ROOT="$HOME/.config/agent-self-evolution"
fi

# 同名脚本优先取数据根下的 scripts/，否则取本脚本所在目录
script_of() {
  if [ -f "$ROOT/scripts/$1" ]; then echo "$ROOT/scripts/$1"; else echo "$SELF_DIR/$1"; fi
}

SKIP_SCORE=0
ONLY_CAND=0
for a in "$@"; do
  case "$a" in
    --no-scorecard) SKIP_SCORE=1 ;;
    --candidates) ONLY_CAND=1 ;;
  esac
done

hr() { printf '\n== %s ==\n' "$1"; }

if [ ! -f "$ROOT/state.json" ]; then
  echo "找不到 $ROOT/state.json。请设置数据根目录后重试，例如："
  echo "  SE_ROOT=/path/to/agent-self-evolution bash $0"
  exit 1
fi

if [ "$ONLY_CAND" = "1" ]; then
  "$PY" - "$ROOT" <<'PY'
import os, re, sys
root = sys.argv[1]
cand = os.path.join(root, "candidates")
slugs = sorted(d for d in os.listdir(cand) if os.path.isdir(os.path.join(cand, d))) if os.path.isdir(cand) else []
print(f"候选数: {len(slugs)}")
for s in slugs:
    d = os.path.join(cand, s)
    sk = os.path.join(d, "SKILL.md")
    size = os.path.getsize(sk) if os.path.exists(sk) else -1
    desc = ""
    if size > 0:
        txt = open(sk, encoding="utf-8", errors="replace").read()
        m = re.search(r"(?m)^description:\s*(.+)$", txt)
        if m:
            desc = m.group(1).strip()
    print(f"- {s} | SKILL.md {size}B | files={sorted(os.listdir(d))} | {desc[:120]}")
PY
  exit 0
fi

hr "1. 系统状态摘要"
"$PY" - "$ROOT" <<'PY'
import json, os, sys
root = sys.argv[1]
s = json.load(open(os.path.join(root, "state.json")))
print("stats:", json.dumps(s.get("stats", {}), ensure_ascii=False))
print("lastEvolutionAt:", s.get("lastEvolutionAt"), "| lastCollectionAt:", s.get("lastCollectionAt"))
print("lastEvolution:", json.dumps(s.get("lastEvolution", {}), ensure_ascii=False))
print("rejections:", len(s.get("rejections", [])), "| collectorUnavailable:", s.get("collectorUnavailable", False))
PY

hr "2. 候选区"
bash "$0" --candidates

hr "3. 启用区与超长技能"
"$PY" - "$ROOT" <<'PY'
import json, os, sys
root = sys.argv[1]
skdir = os.path.join(root, "skills")
names = sorted(d for d in os.listdir(skdir) if os.path.isdir(os.path.join(skdir, d))) if os.path.isdir(skdir) else []
stats = json.load(open(os.path.join(root, "state.json"))).get("stats", {})
print(f"实测目录数: {len(names)} | stats.skillsEnabled: {stats.get('skillsEnabled')} | 上限: 40")
meta = {"self-evolve", "self-evolve-maintenance"}
long_ = []
for n in names:
    p = os.path.join(skdir, n, "SKILL.md")
    if not os.path.exists(p):
        print(f"!! {n} 缺 SKILL.md")
        continue
    size = os.path.getsize(p)
    if size > 8000:
        if n in meta:
            print(f"[元技能-豁免] {n} {size}B：仅提示，不处置")
        else:
            long_.append((size, n))
print("超长(>8000B，元技能除外):", ", ".join(f"{n}={b}B" for b, n in sorted(long_, reverse=True)) or "无")
PY

hr "4. 待处理画像草稿"
"$PY" - "$ROOT" <<'PY'
import os, re, sys
root = sys.argv[1]
pd = os.path.join(root, "profiles")
dirs = sorted(d for d in os.listdir(pd) if os.path.isdir(os.path.join(pd, d))) if os.path.isdir(pd) else []
print(f"草稿份数: {len(dirs)}")
for d in dirs:
    base = os.path.join(pd, d)
    meta, prof = os.path.join(base, "meta.md"), os.path.join(base, "profile.md")
    created = ""
    if os.path.exists(meta):
        m = re.search(r"(?m)^profile-created:\s*(.+)$", open(meta, encoding="utf-8", errors="replace").read())
        created = m.group(1).strip() if m else ""
    n = len([l for l in open(prof, encoding="utf-8", errors="replace") if l.strip()]) if os.path.exists(prof) else 0
    print(f"- {d} | created={created} | 条目={n}")
PY

hr "5. 经验日志尾部"
tail -n 15 "$ROOT/logs/experience-log.md"
printf '\n[experience-log 总行数 %s，超 100 行需归档；日志与记忆体量]\n' "$(wc -l < "$ROOT/logs/experience-log.md" | tr -d ' ')"
wc -c "$ROOT/logs/experience-log.md" "$ROOT/memory/USER.md" "$ROOT/memory/LESSONS.md" 2>/dev/null | sed 's/^/  /'

hr "6. 技能记分卡"
if [ "$SKIP_SCORE" = "1" ]; then
  echo "已跳过（--no-scorecard）"
else
  SC="$(script_of skill_scorecard.py)"
  if [ -f "$SC" ]; then "$PY" "$SC"; else echo "!! 找不到 skill_scorecard.py"; fi
fi

hr "7. 异常与待办提示"
REPO="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$REPO" ]; then
  REL="${ROOT#"$REPO"/}"
  cd "$REPO" || exit 0
  git status --porcelain -- "$REL" | head -20
  DELETED="$(git status --porcelain -- "$REL/profiles" 2>/dev/null | rg '^ ?D' || true)"
  if [ -n "$DELETED" ]; then
    echo "!! profiles 存在被删除的已跟踪文件，须向用户求证后再提炼（禁止自动恢复）："
    echo "$DELETED"
  fi
else
  echo "数据根目录不在 git 仓库内，跳过版本状态检查"
fi
