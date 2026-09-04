# 安装指南（INSTALL.md）

> **推荐方式**：不用自己一步步操作，直接把下面的代码块复制发给你的 AI 助手（pi / Claude Code / Codex 都行），让它帮你完成安装。

## 🚀 通用安装（推荐：AI 自动检测平台）

复制以下内容发给你的 AI：

````text
请帮我安装 agent-self-evolution（一个让 AI 助手自动沉淀技能与记忆的开源系统）。

安装步骤：
1. 检测本机环境：是否安装了 pi-coding-agent（~/.pi/agent 是否存在）、claude CLI、codex CLI；确认 python3 ≥ 3.8 可用
2. 下载仓库到本地：git clone https://github.com/Shiorangerin/agent-self-evolution.git（放到 ~/agent-self-evolution 或你觉得合适的位置）
3. 根据检测结果选择平台并运行安装脚本（支持 pi / claude-code / codex / all 四个参数）：
   - 装了 pi → 运行 bash install.sh pi
   - 装了 claude → 运行 bash install.sh claude-code
   - 装了 codex → 运行 bash install.sh codex
   - 装了两个以上 → 运行 bash install.sh all
4. 安装脚本可能要求交互选择，请根据环境自动选择对应序号
5. 【重要】采集器模型选择：安装脚本会提示「采集器模型未配置」（其中 claude/codex CLI 后端会按用户登录态计费）。请把以下选项与成本影响向用户解释，由用户自己选择后写入 $SE_ROOT/config.json 的 collector 段（免费/便宜模型优先）：
   - backend: auto | custom | claude | codex | api（钉扎单一后端，推荐钉扎便宜/免费后端）
   - llmCmd: 自定义命令，{prompt} 占位（推荐）
   - apiBase / apiKey / apiModel: OpenAI 兼容 API（推荐，模型选便宜/免费）
   - models: Pi 平台自选采集模型链 [{ "provider": "...", "id": "..." }]
   若用户暂时不想选，提醒可在安装后随时编辑 $SE_ROOT/config.json
6. 完成后验证：
   - 确认 ~/.config/agent-self-evolution/ 目录已初始化（state.json、candidates/、profiles/、config.json 等存在）
   - 如果是 pi：确认 ~/.pi/agent/extensions/ 下有 self-evolve.ts 和 skill-usage.ts、~/.pi/agent/skills/self-evolve/ 存在
   - 如果是 claude-code：确认 ~/.claude/settings.json 里有 Stop hook 配置、~/.claude/hooks/ 下有 collect.sh，且 ~/.claude/CLAUDE.md 末尾有指向 ~/.config/agent-self-evolution/memory/USER.md 的 @ 引用行
   - 如果是 codex：确认 ~/.codex/hooks.json 存在、config.toml 里有 [features] codex_hooks = true
7. 把安装结果和后续使用方式（对 agent 说「总结一天的工作」触发进化）简要报告给我
````

## 手动安装（不依赖 AI）

```bash
git clone https://github.com/Shiorangerin/agent-self-evolution.git
cd agent-self-evolution
bash install.sh            # 交互式选择平台
# 或指定平台：bash install.sh pi / claude-code / codex / all
```

## 分平台安装 prompt

如果你只想装某一个平台，也可以复制对应代码块：

### 只装 Pi

````text
请帮我安装 agent-self-evolution 的 Pi 平台适配：
1. 克隆 https://github.com/Shiorangerin/agent-self-evolution.git
2. 运行 bash install.sh pi（确认 ~/.pi/agent 存在，python3 可用）
3. 验证 ~/.pi/agent/extensions/ 下有 self-evolve.ts、skill-usage.ts，~/.pi/agent/skills/self-evolve/ 存在
4. 安装脚本若提示「采集器模型未配置」，请向用户解释采集模型选项与计费风险（claude/codex CLI 按登录态计费），由用户选择后写入 $SE_ROOT/config.json；Pi 侧可在 collector.models 自选便宜/免费模型链
5. 提醒我之后在 pi 里执行 /reload 让扩展生效
````

### 只装 Claude Code

````text
请帮我安装 agent-self-evolution 的 Claude Code 平台适配：
1. 克隆 https://github.com/Shiorangerin/agent-self-evolution.git
2. 运行 bash install.sh claude-code
3. 验证 ~/.claude/settings.json 的 hooks.Stop 已注册（若 command 里是 ${CLAUDE_PROJECT_DIR} 占位符且我不用项目级配置，请改成绝对路径 ~/.claude/hooks/collect.sh）
4. 检查 ~/.claude/hooks/ 下 collect.sh 与 normalize_claude.py 存在且可执行
5. 确认 ~/.claude/CLAUDE.md 末尾被追加了指向 ~/.config/agent-self-evolution/memory/USER.md 的 @ 引用行（幂等，重复运行不应重复追加）
6. 安装脚本若提示「采集器模型未配置」，请向用户解释采集模型选项与计费风险（claude/codex CLI 按登录态计费），由用户选择后写入 $SE_ROOT/config.json 的 collector 段（推荐钉扎便宜/免费后端）
````

### 只装 Codex

````text
请帮我安装 agent-self-evolution 的 Codex 平台适配：
1. 克隆 https://github.com/Shiorangerin/agent-self-evolution.git
2. 运行 bash install.sh codex
3. 验证 ~/.codex/hooks.json 存在且合法、~/.codex/config.toml 有 [features] codex_hooks = true、~/.codex/hooks/ 下文件存在
4. 提醒我：Codex 首次运行 hooks 时可能要求 trust 确认，需要允许
5. 安装脚本若提示「采集器模型未配置」，请向用户解释采集模型选项与计费风险（codex CLI 按登录态计费），由用户选择后写入 $SE_ROOT/config.json 的 collector 段（推荐钉扎便宜/免费后端）
````

## 安装后

1. **正常使用**：跑一个多步骤任务（工具调用 ≥5 次），然后检查 `~/.config/agent-self-evolution/candidates/` 是否出现候选、`profiles/` 是否出现画像草稿；
2. **触发进化**：对你的 agent 说 **「总结一天的工作」** 或 **「进化」**；
3. **LLM 后端**：采集需要一种 LLM 后端。⚠️ 默认探测顺序为 `SE_LLM_CMD`/config.json → `claude` CLI → `codex` CLI → OpenAI 兼容 API，其中 claude/codex CLI 按登录态计费，可能产生费用；强烈建议在 `$SE_ROOT/config.json` 的 collector 段明确指定便宜/免费的采集模型（详见 README「采集器模型选择」）。没配的话采集会静默失败并记录原因，不影响 agent 正常使用。

## 验证清单

| 检查项 | 命令 | 期望 |
| --- | --- | --- |
| 数据目录 | `ls ~/.config/agent-self-evolution/` | candidates/ profiles/ skills/ memory/ logs/ state.json 存在 |
| 采集器可运行 | `python3 ~/.config/agent-self-evolution/core/collect.py --help` | 打印帮助 |
| Pi 扩展 | `ls ~/.pi/agent/extensions/` | 含 self-evolve.ts、skill-usage.ts |
| Claude Code hook | `python3 -m json.tool ~/.claude/settings.json` | hooks.Stop 存在 |
| Claude Code 画像注入 | `grep memory/USER.md ~/.claude/CLAUDE.md` | 有 @ 引用行 |
| Codex hook | `cat ~/.codex/hooks.json` | Stop 命令存在 |

## 卸载

1. 删除 hook 配置：Claude Code 的 `~/.claude/settings.json` 中 hooks.Stop 条目；Codex 的 `~/.codex/hooks.json`；
2. 删除 Claude Code 全局 `~/.claude/CLAUDE.md` 末尾指向 `memory/USER.md` 的 `@` 引用行；
3. 删除 Pi 扩展：`~/.pi/agent/extensions/self-evolve.ts`、`skill-usage.ts` 与 `~/.pi/agent/skills/self-evolve/`；
4. 删除数据目录：`rm -rf ~/.config/agent-self-evolution/`；
5. 删除克隆的仓库目录。

无残留进程、无后台服务。更多细节见各平台 README 与 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。
