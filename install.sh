#!/usr/bin/env bash
# agent-self-evolution 一键安装脚本（交互式、幂等）
#
# 用法: bash install.sh [platform]
#   platform: pi | claude-code | codex | all（缺省交互式选择）

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SE_ROOT="${SE_ROOT:-$HOME/.config/agent-self-evolution}"

say()  { printf '\033[1;36m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[警告]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[错误]\033[0m %s\n' "$*"; exit 1; }

# ---------- 0. 环境检查 ----------
command -v python3 >/dev/null 2>&1 || die "需要 python3（≥3.8），请先安装"

# ---------- 1. 选择平台 ----------
PLATFORM="${1:-}"
if [[ -z "$PLATFORM" ]]; then
  echo "请选择要安装的平台："
  echo "  1) pi           —— pi-coding-agent（扩展 + 技能）"
  echo "  2) claude-code  —— Claude Code（Stop hook + CLAUDE.md）"
  echo "  3) codex        —— OpenAI Codex CLI（Stop hook + AGENTS.md）"
  echo "  4) all          —— 全部安装"
  read -rp "输入序号 [1/2/3/4]: " choice
  case "$choice" in
    1) PLATFORM="pi" ;;
    2) PLATFORM="claude-code" ;;
    3) PLATFORM="codex" ;;
    4) PLATFORM="all" ;;
    *) die "无效选择" ;;
  esac
fi

# ---------- 2. 安装核心（数据目录 + core 脚本） ----------
install_core() {
  say "安装核心到 $SE_ROOT"
  mkdir -p "$SE_ROOT"
  mkdir -p "$SE_ROOT/core"
  cp -R "$REPO_DIR/core/." "$SE_ROOT/core/"
  python3 "$SE_ROOT/core/init.py"
  say "核心就绪（collect.py / init.py / templates）"
}

# ---------- 3. 各平台安装 ----------
install_pi() {
  say "安装 Pi 适配…"
  local pi_dir="$HOME/.pi/agent"
  [[ -d "$pi_dir/extensions" ]] || die "未找到 $pi_dir/extensions，请确认已安装 pi-coding-agent"
  cp "$REPO_DIR/platforms/pi/extensions/self-evolve.ts"   "$pi_dir/extensions/"
  cp "$REPO_DIR/platforms/pi/extensions/skill-usage.ts"   "$pi_dir/extensions/"
  mkdir -p "$pi_dir/skills/self-evolve"
  cp "$REPO_DIR/platforms/pi/skills/self-evolve/SKILL.md" "$pi_dir/skills/self-evolve/SKILL.md"
  say "Pi 扩展与技能已复制到 $pi_dir，请在 pi 里执行 /reload 生效"
}

install_claude_code() {
  say "安装 Claude Code 适配…"
  local dst="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
  mkdir -p "$dst/hooks"
  cp "$REPO_DIR/platforms/claude-code/hooks/collect.sh"          "$dst/hooks/collect.sh"
  cp "$REPO_DIR/platforms/claude-code/hooks/normalize_claude.py" "$dst/hooks/normalize_claude.py"
  chmod +x "$dst/hooks/collect.sh"
  # CLAUDE.md（若不存在则复制，存在则提示）
  if [[ ! -f "$dst/CLAUDE.md" ]]; then
    cp "$REPO_DIR/platforms/claude-code/CLAUDE.md" "$dst/CLAUDE.md"
  else
    warn "$dst/CLAUDE.md 已存在，跳过（请手动合并 platforms/claude-code/CLAUDE.md 的内容）"
  fi
  # 注册 Stop hook（若已有 settings.local.json 则优先使用它，避免与 settings.json 重复执行）
  local settings_file="$dst/settings.json"
  if [[ -f "$dst/settings.local.json" ]]; then
    settings_file="$dst/settings.local.json"
  fi
  if [[ -f "$settings_file" ]]; then
    python3 - "$settings_file" "$REPO_DIR/platforms/claude-code/settings.hooks.json" "$dst/hooks/collect.sh" <<'PY'
import json, sys
settings_path, hooks_path, hook_abs = sys.argv[1], sys.argv[2], sys.argv[3]
with open(settings_path, "r", encoding="utf-8") as f:
    settings = json.load(f)
with open(hooks_path, "r", encoding="utf-8") as f:
    hooks_block = json.load(f)
settings.setdefault("hooks", {})
merged = False
for event, groups in hooks_block.get("hooks", {}).items():
    existing = settings["hooks"].setdefault(event, [])
    for group in groups:
        for h in group.get("hooks", []):
            cmd = h.get("command", "")
            if cmd.startswith("bash ${CLAUDE_PROJECT_DIR}/.claude/hooks/collect.sh"):
                h["command"] = "bash " + hook_abs
                cmd = h["command"]
            if any(cmd in json.dumps(x) for x in existing):
                continue
            existing.append(group)
            merged = True
with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(settings, f, ensure_ascii=False, indent=2)
print("已注册 Stop hook" if merged else "Stop hook 已存在，跳过")
PY
  else
    # 用户级 settings.json：command 必须用绝对路径（${CLAUDE_PROJECT_DIR} 占位符在此处不可靠）
    python3 - "$REPO_DIR/platforms/claude-code/settings.hooks.json" "$dst/settings.json" "$dst/hooks/collect.sh" <<'PY'
import json, sys
src, dst, hook_abs = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src, "r", encoding="utf-8") as f:
    cfg = json.load(f)
for groups in cfg.get("hooks", {}).values():
    for group in groups:
        for h in group.get("hooks", []):
            if "command" in h:
                h["command"] = "bash " + hook_abs
with open(dst, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
PY
    say "已创建 $settings_file（Stop hook 已指向绝对路径 $dst/hooks/collect.sh）"
  fi
  say "Claude Code 适配完成。$(basename "$settings_file") 中的 command 已指向 $dst/hooks/collect.sh（项目级安装可自行改用 \${CLAUDE_PROJECT_DIR} 占位符）"
}

install_codex() {
  say "安装 Codex 适配…"
  # hooks 复制到 SE_ROOT（自包含：克隆目录删除后仍可用）
  local hooks_dst="$SE_ROOT/platforms/codex/hooks"
  mkdir -p "$hooks_dst"
  cp "$REPO_DIR/platforms/codex/hooks/collect.sh"          "$hooks_dst/collect.sh"
  cp "$REPO_DIR/platforms/codex/hooks/normalize_codex.py"  "$hooks_dst/normalize_codex.py"
  chmod +x "$hooks_dst/collect.sh"
  local dst="$HOME/.codex"
  mkdir -p "$dst/hooks"
  cp "$hooks_dst/collect.sh"          "$dst/hooks/collect.sh"
  cp "$hooks_dst/normalize_codex.py"  "$dst/hooks/normalize_codex.py"
  chmod +x "$dst/hooks/collect.sh"
  # Codex 0.147+ 从 config.toml 读取 hooks；hooks.json 在该版本不会被加载。
  local cfg="$dst/config.toml"
  python3 - "$cfg" "$hooks_dst/collect.sh" <<'PY'
import sys
from pathlib import Path

path, hook_abs = Path(sys.argv[1]), sys.argv[2]
text = path.read_text(encoding="utf-8") if path.exists() else ""
cmd = f"bash {hook_abs}"

if cmd in text:
    print("Stop hook 已存在，跳过")
else:
    block = f"""

[[hooks.Stop]]
hooks = [
  {{ type = "command", command = "{cmd}", async = false }}
]
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(block)
    print("已在 config.toml 注册 Stop hook")
PY
  # 开启当前 feature flag（0.147+ 使用 hooks；旧名 codex_hooks 已废弃）
  if command -v codex >/dev/null 2>&1; then
    CODEX_HOME="$dst" codex features enable hooks >/dev/null
  else
    warn "未找到 codex CLI，请手动在 $cfg 的 [features] 中加入 hooks = true"
  fi

  # 迁移旧安装遗留的 hooks.json；若其中含用户自定义 hook，则保留并提示迁移。
  if [[ -f "$dst/hooks.json" ]]; then
    if grep -q 'agent-self-evolution/platforms/codex/hooks/collect.sh' "$dst/hooks.json"; then
      rm "$dst/hooks.json"
      say "已移除旧版 $dst/hooks.json（Codex 0.147+ 不再读取该文件）"
    else
      warn "$dst/hooks.json 可能包含其他 hook，Codex 0.147+ 不会读取它，请手动迁移到 $cfg"
    fi
  fi
  # AGENTS.md
  if [[ ! -f "$dst/AGENTS.md" ]]; then
    cp "$REPO_DIR/platforms/codex/AGENTS.md" "$dst/AGENTS.md"
  else
    warn "$dst/AGENTS.md 已存在，跳过（请手动合并 platforms/codex/AGENTS.md 的内容）"
  fi
  say "Codex 适配完成。首次运行 hooks 时 Codex 会要求 trust 确认，请允许。"
}

# ---------- 执行 ----------
install_core
case "$PLATFORM" in
  pi)          install_pi ;;
  claude-code) install_claude_code ;;
  codex)       install_codex ;;
  all)
    install_pi || warn "Pi 安装失败（可忽略，若未安装 pi）"
    install_claude_code
    install_codex
    ;;
  *) die "未知平台: $PLATFORM" ;;
esac

say "全部完成 🎉"
say "下一步：跑一个多步骤任务 → 检查 $SE_ROOT/candidates/ 是否有候选 → 对 agent 说「进化」触发审查流程"
