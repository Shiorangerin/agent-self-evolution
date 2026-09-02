# 安装指南（INSTALL.md）

> **推荐方式**：不用自己一步步操作，直接把下面的代码块复制发给你的 AI 助手（pi / Claude Code / Codex 都行），让它帮你完成安装。

## 🚀 通用安装（推荐：AI 自动检测平台）

复制以下内容发给你的 AI：

````text
请帮我安装 agent-self-evolution（一个让 AI 助手自动沉淀技能与记忆的开源系统）。

安装步骤：
1. 检测本机环境：是否安装了 pi-coding-agent（~/.pi/agent 是否存在）、claude CLI、codex CLI；确认 python3 ≥ 3.8 可用
2. 下载仓库到本地：git clone https://github.com/R03montia/agent-self-evolution.git（放到 ~/agent-self-evolution 或你觉得合适的位置）
3. 根据检测结果选择平台并运行安装脚本（支持 pi / claude-code / codex / all 四个参数）：
   - 装了 pi → 运行 bash install.sh pi
   - 装了 claude → 运行 bash install.sh claude-code
   - 装了 codex → 运行 bash install.sh codex
   - 装了两个以上 → 运行 bash install.sh all
4. 安装脚本可能要求交互选择，请根据环境自动选择对应序号
5. 完成后验证：
   - 确认 ~/.config/agent-self-evolution/ 目录已初始化（state.json、candidates/ 等存在）
   - 如果是 pi：确认 ~/.pi/agent/extensions/ 下有 self-evolve.ts 和 skill-usage.ts、~/.pi/agent/skills/self-evolve/ 存在
   - 如果是 claude-code：确认 ~/.claude/settings.local.json（若存在）或 ~/.claude/settings.json 里有 Stop hook 配置、~/.claude/hooks/ 下有 collect.sh
   - 如果是 codex：确认 ~/.codex/config.toml 里有 [[hooks.Stop]] 和 [features] hooks = true
6. 把安装结果和后续使用方式（对 agent 说「总结一天的工作」触发进化）简要报告给我
````

## 手动安装（不依赖 AI）

```bash
git clone https://github.com/R03montia/agent-self-evolution.git
cd agent-self-evolution
bash install.sh            # 交互式选择平台
# 或指定平台：bash install.sh pi / claude-code / codex / all
```

## 分平台安装 prompt

如果你只想装某一个平台，也可以复制对应代码块：

### 只装 Pi

````text
请帮我安装 agent-self-evolution 的 Pi 平台适配：
1. 克隆 https://github.com/R03montia/agent-self-evolution.git
2. 运行 bash install.sh pi（确认 ~/.pi/agent 存在，python3 可用）
3. 验证 ~/.pi/agent/extensions/ 下有 self-evolve.ts、skill-usage.ts，~/.pi/agent/skills/self-evolve/ 存在
4. 提醒我之后在 pi 里执行 /reload 让扩展生效
````

### 只装 Claude Code

````text
请帮我安装 agent-self-evolution 的 Claude Code 平台适配：
1. 克隆 https://github.com/R03montia/agent-self-evolution.git
2. 运行 bash install.sh claude-code
3. 验证 ~/.claude/settings.local.json（若存在）或 ~/.claude/settings.json 的 hooks.Stop 已注册（若 command 里是 ${CLAUDE_PROJECT_DIR} 占位符且我不用项目级配置，请改成绝对路径 ~/.claude/hooks/collect.sh）
4. 检查 ~/.claude/hooks/ 下 collect.sh 与 normalize_claude.py 存在且可执行
````

### 只装 Codex

````text
请帮我安装 agent-self-evolution 的 Codex 平台适配：
1. 克隆 https://github.com/R03montia/agent-self-evolution.git
2. 运行 bash install.sh codex
3. 验证 ~/.codex/config.toml 里有 [[hooks.Stop]] 和 [features] hooks = true、~/.codex/hooks/ 下文件存在
4. 提醒我：Codex 首次运行 hooks 时可能要求 trust 确认，需要允许
````

## 安装后

1. **正常使用**：跑一个多步骤任务（工具调用 ≥5 次），然后检查 `~/.config/agent-self-evolution/candidates/` 是否出现候选；
2. **触发进化**：对你的 agent 说 **「总结一天的工作」** 或 **「进化」**；
3. **LLM 后端**：采集需要一种 LLM 后端（自动探测：`SE_LLM_CMD` → `claude` CLI → `codex` CLI → OpenAI 兼容 API 环境变量）。没配的话采集会静默失败并记录原因，不影响 agent 正常使用。

## 验证清单

| 检查项 | 命令 | 期望 |
| --- | --- | --- |
| 数据目录 | `ls ~/.config/agent-self-evolution/` | candidates/ skills/ memory/ logs/ state.json 存在 |
| 采集器可运行 | `python3 ~/.config/agent-self-evolution/core/collect.py --help` | 打印帮助 |
| Pi 扩展 | `ls ~/.pi/agent/extensions/` | 含 self-evolve.ts、skill-usage.ts |
| Claude Code hook | `python3 -m json.tool ~/.claude/settings.local.json`（若不存在则检查 `settings.json`） | hooks.Stop 存在 |
| Codex hook | `grep -A4 'hooks.Stop' ~/.codex/config.toml` | type/command/async 齐全 |

## 卸载

1. 删除 hook 配置：Claude Code 的 `~/.claude/settings.local.json`（若不存在则 `settings.json`）中 hooks.Stop 条目；Codex 的 `~/.codex/config.toml` 中 [[hooks.Stop]] 条目；
2. 删除 Pi 扩展：`~/.pi/agent/extensions/self-evolve.ts`、`skill-usage.ts` 与 `~/.pi/agent/skills/self-evolve/`；
3. 删除数据目录：`rm -rf ~/.config/agent-self-evolution/`；
4. 删除克隆的仓库目录。

无残留进程、无后台服务。更多细节见各平台 README 与 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。
