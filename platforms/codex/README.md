# agent-self-evolution — Codex 平台适配器

让 Codex CLI 接入 agent-self-evolution：每次任务结束（`Stop` 事件）自动采集会话轨迹，
满足条件时用 LLM 并行发起两路独立采集（失败互不影响）：技能候选写入候选区；
用户画像草稿写入 `profiles/`，待用户手动触发进化流程审查启用 / 提炼进 USER.md。

```
platforms/codex/
├── hooks/
│   ├── normalize_codex.py   # Codex transcript → 统一 JSONL 归一化器（兼容新旧格式）
│   └── collect.sh           # Stop hook 入口：定位轨迹 → 归一化 → 调 core/collect.py
├── hooks.json               # hooks 配置样例（合并到 ~/.codex/hooks.json）
├── AGENTS.md                # 进化流程说明书（Codex 自动加载）
└── README.md                # 本文件
```

## 推荐安装方式（复制给 AI）

````text
请帮我安装 agent-self-evolution 的 Codex 平台适配：
1. git clone https://github.com/Shiorangerin/agent-self-evolution.git
2. 运行 bash install.sh codex
3. 验证 ~/.codex/hooks.json 存在且合法、~/.codex/config.toml 有 [features] codex_hooks = true、~/.codex/hooks/ 下文件存在
4. 提醒我：Codex 首次运行 hooks 时可能要求 trust 确认，需要允许
````

以下详细步骤供 AI 执行时参考。

## 安装

### ① 确认 core 已就绪

先完成核心系统初始化（在项目根目录）：

```bash
python3 core/init.py
```

初始化会创建 `$SE_ROOT`（默认 `~/.config/agent-self-evolution/`）的完整目录结构与
初始文件（candidates / skills / memory / logs / state.json / usage.json）。幂等，可重复执行。

### ② 安装 hooks 配置

把 `hooks.json` 的内容合并到 `~/.codex/hooks.json`（文件不存在则直接创建）：

```json
{
  "hooks": {
    "Stop": [
      { "command": "bash $HOME/.config/agent-self-evolution/platforms/codex/hooks/collect.sh" }
    ]
  }
}
```

**注意**：`command` 中的路径是默认安装位置的样例，请按实际安装位置调整。
如果 `$HOME` 在你的环境中不展开，请换成不含用户名的绝对路径。
（也可以不用 hooks.json，改在 `~/.codex/config.toml` 的 `[hooks]` 段配置同样的 Stop 命令。）

### ③ 开启 hooks 功能开关

Codex 需要显式开启 hooks 特性。编辑 `~/.codex/config.toml`，确保包含：

```toml
[features]
codex_hooks = true
```

幂等说明：如果已有 `[features]` 段，只补上 `codex_hooks = true` 一行即可；
重复写入相同配置无害。

### ④ 信任 hooks（首次运行）

Codex 对 hook 命令有 trust 机制：首次触发 `Stop` 事件时会询问是否信任该 hook，
选择允许（trust）即可。修改 hook 脚本后若再次询问，同样选择允许。
若未信任，hook 不会执行，属于正常防护行为。

### ⑤ 验证

1. 跑一个**多步骤任务**（≥5 次工具调用，或出现错误并修复），正常结束会话；
2. 检查候选区：

```bash
ls "$HOME/.config/agent-self-evolution/candidates/"
```

   应能看到本次会话草拟的候选技能目录；若未生成，查看
   `$SE_ROOT/logs/experience-log.md` 与 `$SE_ROOT/state.json` 中的 rejection 记录。

3. 也可以绕过 Codex 直接手动测试 hook：

```bash
echo '{"session_id":"test123","cwd":"/tmp","hook_event_name":"Stop","transcript_path":"/tmp/your-session.jsonl"}' \
  | bash platforms/codex/hooks/collect.sh
```

   正常应输出采集结果（生成候选 / 条件不满足 / 拒绝原因），且退出码恒为 0。

## LLM 后端

`core/collect.py` 解析 LLM 后端（优先级：环境变量 > `$SE_ROOT/config.json` > 内置顺序）：

0. **config.json `collector` 段（推荐）**：钉扎便宜/免费后端，见 README「采集器模型选择」；
1. `SE_LLM_CMD` / `collector.llmCmd` — 自定义命令，用 `{prompt}` 占位符传入提示词
2. `claude` CLI — 复用 Claude Code 登录态（⚠️ 按登录态计费）
3. `codex` CLI — 复用 Codex 登录态（`codex exec`；⚠️ 按登录态计费）
4. OpenAI 兼容 API — config.json 或环境变量（推荐指定便宜/免费模型）：

```bash
export SE_API_BASE="https://api.example.com/v1"
export SE_API_KEY="sk-..."
export SE_API_MODEL="your-cheap-model"
```

`collector.backend` 可钉扎到 `custom` / `claude` / `codex` / `api` 单一后端；钉扎后若该后端不可用会明确报错，不会静默降级到其他可能计费的后端。
也可在 `~/.codex/config.toml` 中为 hook 命令注入环境变量（见 Codex 文档的 env 配置）。

## 故障排查

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| hook 完全不触发 | 功能开关未开 | 确认 `~/.codex/config.toml` 有 `[features] codex_hooks = true` |
| hook 不触发 | hooks.json 位置/格式错误 | 确认文件在 `~/.codex/hooks.json` 且是合法 JSON（可 `python3 -m json.tool` 校验） |
| hook 不触发 | 未信任 hook | 触发一次任务结束，在弹出的信任询问中选择允许 |
| 无候选生成 | transcript 定位失败 | 手动检查 `~/.codex/sessions/` 下的会话文件；hook 输入若无 `transcript_path`，脚本按 `session_id` 与最近 10 分钟兜底查找 |
| 无候选生成 | 条件不满足 | 工具调用 <5 次且无错误时不值得沉淀，属正常行为（见 experience-log.md） |
| 无候选生成 | LLM 后端缺失 | 安装/登录 codex 或 claude CLI，或配置 SE_API_BASE / SE_API_KEY / SE_API_MODEL |
| agent 任务被阻塞 | — | 不应发生：collect.sh 全脚本容错、恒 exit 0，采集失败绝不影响任务 |

## 隐私与安全

- 采集只在本地进行；候选技能写入 `$SE_ROOT/candidates/`，不进入运行上下文
- 用户隐私信息不会出现在任何公开内容中
- 所有进化动作（启用/归档/记忆更新）均需用户手动触发或确认
