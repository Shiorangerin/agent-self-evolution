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

# ---------- platform docs ----------
merge_platform_doc() {
  local dst="$1"
  local src="$2"
  local detect="$3"
  local marker="agent-self-evolution"
  mkdir -p "$(dirname "$dst")"
  touch "$dst"
  if grep -Eq "BEGIN ${marker}|${detect}" "$dst"; then
    say "平台说明已存在于 $(basename "$dst")，跳过"
    return
  fi
  {
    echo ''
    echo "# BEGIN ${marker}"
    local repo_escaped="${REPO_DIR//\\/\\\\}"
    repo_escaped="${repo_escaped//&/\\&}"
    repo_escaped="${repo_escaped//|/\\|}"
    sed "s|<仓库>|${repo_escaped}|g" "$src"
    echo "# END ${marker}"
  } >> "$dst"
  say "已合并平台说明到 $dst"
}

# ---------- 0. 环境检查 ----------
command -v python3 >/dev/null 2>&1 || die "需要 python3（≥3.8），请先安装"
mkdir -p "$SE_ROOT"
SE_ROOT="$(cd "$SE_ROOT" && pwd)"

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
  mkdir -p "$dst/hooks/agent-self-evolution"
  dst="$(cd "$dst" && pwd)"
  cp "$REPO_DIR/platforms/claude-code/hooks/collect.sh"          "$dst/hooks/agent-self-evolution/collect.sh"
  cp "$REPO_DIR/platforms/claude-code/hooks/normalize_claude.py" "$dst/hooks/agent-self-evolution/normalize_claude.py"
  chmod +x "$dst/hooks/agent-self-evolution/collect.sh"
  # CLAUDE.md（若不存在则复制，存在则提示）
  if [[ ! -f "$dst/CLAUDE.md" ]]; then
    cp "$REPO_DIR/platforms/claude-code/CLAUDE.md" "$dst/CLAUDE.md"
  else
    merge_platform_doc "$dst/CLAUDE.md" "$REPO_DIR/platforms/claude-code/CLAUDE.md" '自我进化系统.*进化流程说明书'
  fi
  local settings_rc=0
  # 注册 Stop hook；统一检查两个用户级配置，避免 settings.json 和 settings.local.json 双注册。
  python3 "$REPO_DIR/scripts/hook_config.py" claude "$dst" || settings_rc=$?
  if [[ "$settings_rc" -eq 2 ]]; then
    warn "Claude settings JSON 存在解析错误，已跳过自动注册；请手动检查后重试"
  elif [[ "$settings_rc" -ne 0 ]]; then
    warn "Claude Stop hook 注册失败，已保留现有配置"
  fi
  say "Claude Code 适配完成。Stop hook 指向 $dst/hooks/agent-self-evolution/collect.sh（项目级安装可自行改用 \${CLAUDE_PROJECT_DIR} 占位符）"
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
  mkdir -p "$dst"
  dst="$(cd "$dst" && pwd)"
  local codex_rc=0
  # Codex 0.147+ 从 config.toml 读取 hooks；hooks.json 在该版本不会被加载。
  local cfg="$dst/config.toml"
  python3 "$REPO_DIR/scripts/hook_config.py" codex "$cfg" "$hooks_dst/collect.sh" || codex_rc=$?
  if [[ "$codex_rc" -eq 2 ]]; then
    warn "检测到旧式 hooks.Stop 配置，已保留原文件；请手动迁移后再运行安装"
  elif [[ "$codex_rc" -ne 0 ]]; then
    warn "Codex Stop hook 注册失败，已保留原配置"
  fi
  # 开启当前 feature flag（0.147+ 使用 hooks；旧名 codex_hooks 已废弃）
  if command -v codex >/dev/null 2>&1; then
    if CODEX_HOME="$dst" codex features enable hooks; then
      say "已启用 Codex hooks feature"
    else
      warn "codex features enable hooks 失败，请手动在 $cfg 的 [features] 中加入 hooks = true"
    fi
  else
    warn "未找到 codex CLI，请手动在 $cfg 的 [features] 中加入 hooks = true"
  fi

  # Codex 0.147+ 不读取 hooks.json；保留文件，避免破坏用户自定义 hook。
  if [[ -f "$dst/hooks.json" ]]; then
    warn "$dst/hooks.json 已保留；Codex 0.147+ 不会读取它，请手动核对并迁移其中仍需要的 hook"
  fi
  # AGENTS.md
  if [[ ! -f "$dst/AGENTS.md" ]]; then
    cp "$REPO_DIR/platforms/codex/AGENTS.md" "$dst/AGENTS.md"
  else
    merge_platform_doc "$dst/AGENTS.md" "$REPO_DIR/platforms/codex/AGENTS.md" 'agent-self-evolution.*Codex 平台进化流程'
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
