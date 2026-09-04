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
  cp -R "$REPO_DIR/core" "$SE_ROOT/core"
  python3 "$SE_ROOT/core/init.py"
  say "核心就绪（collect.py / init.py / templates）"
}

# ---------- 采集器模型选择（防止采集默认用到昂贵模型） ----------
# 首次安装且仍为默认配置时提示：交互终端提供菜单，非交互（AI 代装）输出提示供 AI 转达给用户
configure_collector_model() {
  local cfg="$SE_ROOT/config.json"
  [[ -f "$cfg" ]] || return 0

  local need_cfg
  need_cfg="$(python3 - "$cfg" <<'PY'
import json, sys
try:
    c = json.load(open(sys.argv[1], encoding="utf-8")).get("collector") or {}
except Exception:
    c = {}
used_default = (
    c.get("backend", "auto") == "auto" and not c.get("llmCmd")
    and not c.get("apiBase") and not (c.get("models") or [])
)
print("yes" if used_default else "no")
PY
)"
  [[ "$need_cfg" == "yes" ]] || return 0

  if [[ -t 0 ]]; then
    cat <<'EOF'

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 采集器模型选择（防止采集默认用到昂贵模型）                ┃
┃ 采集器每次任务结束会用所选后端调用 LLM（技能候选+用户画像）┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
  1) OpenAI 兼容 API   —— 自己指定便宜/免费模型（推荐）
  2) 自定义命令        —— 完全自控，{prompt} 占位（推荐）
  3) claude CLI        —— 复用 Claude Code 登录态（按用量计费！）
  4) codex CLI         —— 复用 Codex 登录态（按用量计费！）
  5) auto              —— 保持默认探测（可能命中计费 CLI）
  6) 暂不配置          —— 稍后自行编辑 config.json
EOF
    local mchoice
    read -rp "输入序号 [1-6，回车=6]: " mchoice
    mchoice="${mchoice:-6}"
    local backend="" api_base="" api_key="" api_model="" llm_cmd=""
    case "$mchoice" in
      1) backend="api"
         read -rp "API Base（如 https://api.example.com/v1）: " api_base
         read -rp "API Key: " api_key
         read -rp "模型名（建议选便宜/免费模型）: " api_model ;;
      2) backend="custom"
         read -rp "命令（用 {prompt} 占位，如 my-llm \"{prompt}\"）: " llm_cmd ;;
      3) backend="claude" ;;
      4) backend="codex" ;;
      5) backend="auto" ;;
      *) say "跳过模型配置（可稍后编辑 $cfg）"; return 0 ;;
    esac
    python3 - "$cfg" "$backend" "$api_base" "$api_key" "$api_model" "$llm_cmd" <<'PY'
import json, sys
cfg_path, backend, api_base, api_key, api_model, llm_cmd = sys.argv[1:7]
try:
    cfg = json.load(open(cfg_path, encoding="utf-8"))
except Exception:
    cfg = {}
c = cfg.setdefault("collector", {})
c["backend"] = backend
if api_base: c["apiBase"] = api_base
if api_key: c["apiKey"] = api_key
if api_model: c["apiModel"] = api_model
if llm_cmd: c["llmCmd"] = llm_cmd
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY
    say "已把采集器后端（$backend）写入 $cfg"
  else
    cat <<'EOF'
[install] ⚠️  采集器模型未配置：当前默认探测顺序为 自定义命令 → claude CLI → codex CLI → OpenAI 兼容 API。
[install]    其中 claude/codex CLI 会按你的登录态计费，采集可能产生费用！
[install]    请让 AI 助手把以下选项与成本影响解释给你，由你选择后写入 $SE_ROOT/config.json 的 collector 段：
[install]      - backend:  auto | custom | claude | codex | api（钉扎单一后端；推荐钉扎便宜/免费后端）
[install]      - llmCmd:   自定义命令，{prompt} 占位（推荐）
[install]      - apiBase / apiKey / apiModel: OpenAI 兼容 API（推荐，模型选便宜/免费）
[install]      - models:   Pi 平台自选采集模型链 [{ "provider": "...", "id": "..." }]
EOF
  fi
}

# ---------- 3. 各平台安装 ----------
install_pi() {
  say "安装 Pi 适配…"
  local pi_dir="$HOME/.pi/agent"
  if [[ ! -d "$pi_dir/extensions" ]]; then
    warn "未找到 $pi_dir/extensions，跳过 Pi 适配（未安装 pi-coding-agent；仅安装 all 时可忽略）"
    return 1
  fi
  cp "$REPO_DIR/platforms/pi/extensions/self-evolve.ts"   "$pi_dir/extensions/"
  cp "$REPO_DIR/platforms/pi/extensions/skill-usage.ts"   "$pi_dir/extensions/"
  mkdir -p "$pi_dir/skills/self-evolve"
  cp "$REPO_DIR/platforms/pi/skills/self-evolve/SKILL.md" "$pi_dir/skills/self-evolve/SKILL.md"
  say "Pi 扩展与技能已复制到 $pi_dir，请在 pi 里执行 /reload 生效"
}

install_claude_code() {
  say "安装 Claude Code 适配…"
  local dst="$HOME/.claude"
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
  # 注册 Stop hook（合并到 settings.json）
  if [[ -f "$dst/settings.json" ]]; then
    python3 - "$dst/settings.json" "$REPO_DIR/platforms/claude-code/settings.hooks.json" <<'PY'
import json, sys
settings_path, hooks_path = sys.argv[1], sys.argv[2]
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
    say "已创建 $dst/settings.json（Stop hook 已指向绝对路径 $dst/hooks/collect.sh）"
  fi
  say "Claude Code 适配完成。settings.json 中的 command 已指向 $dst/hooks/collect.sh（项目级安装可自行改用 \${CLAUDE_PROJECT_DIR} 占位符）"

  # 用户画像注入：在全局 CLAUDE.md 中幂等追加 @import（Claude Code 支持 @ 绝对路径引用，
  # 进化流程更新 USER.md 后下次会话自动生效）。仅追加引用行，绝不改动用户已有内容。
  local user_md="$SE_ROOT/memory/USER.md"
  local import_line="@$user_md"
  if [[ -f "$dst/CLAUDE.md" ]] && grep -Fq "$import_line" "$dst/CLAUDE.md"; then
    say "用户画像 @import 已存在于 $dst/CLAUDE.md，跳过"
  else
    printf '%s\n' "$import_line" >> "$dst/CLAUDE.md"
    say "已在 $dst/CLAUDE.md 追加用户画像 @import（→ ${user_md}）"
  fi
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
  # hooks.json
  if [[ -f "$dst/hooks.json" ]]; then
    python3 - "$dst/hooks.json" "$hooks_dst/collect.sh" <<'PY'
import json, sys
path, hook_abs = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    cfg = json.load(f)
cfg.setdefault("hooks", {}).setdefault("Stop", [])
cmd = "bash " + hook_abs
if not any(cmd in json.dumps(h) for h in cfg["hooks"]["Stop"]):
    cfg["hooks"]["Stop"].append({"command": cmd})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("已注册 Stop hook")
else:
    print("Stop hook 已存在，跳过")
PY
  else
    cat > "$dst/hooks.json" <<EOF
{
  "hooks": {
    "Stop": [
      { "command": "bash $hooks_dst/collect.sh" }
    ]
  }
}
EOF
    say "已创建 $dst/hooks.json"
  fi
  # 开启 feature flag（幂等）
  local cfg="$dst/config.toml"
  if [[ -f "$cfg" ]] && ! grep -q 'codex_hooks' "$cfg"; then
    printf '\n[features]\ncodex_hooks = true\n' >> "$cfg"
    say "已在 $cfg 追加 [features] codex_hooks = true"
  elif [[ ! -f "$cfg" ]]; then
    printf '[features]\ncodex_hooks = true\n' > "$cfg"
    say "已创建 ${cfg}（含 [features] codex_hooks = true）"
  else
    say "codex_hooks 已在 $cfg 中配置"
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
configure_collector_model
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
