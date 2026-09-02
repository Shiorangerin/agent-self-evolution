# agent-self-evolution — Claude Code 平台适配器

在 Claude Code 中接入自我进化系统：每次 agent 任务结束（`Stop` 事件）时，自动把本次会话轨迹归一化并交给采集器，满足条件时用 LLM 草拟技能候选写入候选区；候选不进入运行上下文，由用户手动触发「进化流程」审查启用。

## 目录结构

```
platforms/claude-code/
├── hooks/
│   ├── normalize_claude.py   # Claude Code transcript → 统一 JSONL 归一化器
│   └── collect.sh            # Stop hook 入口脚本（调用归一化器 + collect.py）
├── settings.hooks.json       # hooks 配置片段（合并进 settings.local.json 或 settings.json）
└── CLAUDE.md                 # 进化流程说明书（注入 Claude Code 上下文）
```

## 前置条件

1. **core 已安装**：运行 `python3 $SE_ROOT/core/init.py` 初始化数据目录（`$SE_ROOT` 默认 `$HOME/.config/agent-self-evolution/`，可用环境变量覆盖）。
2. **LLM 后端**（collect.py 自动探测，按优先级）：
   - 环境变量 `SE_LLM_CMD`（自定义命令，用 `{prompt}` 占位符传提示词）；
   - `claude` CLI（**推荐**：Claude Code 用户通常已登录，无需额外配置）；
   - `codex` CLI；
   - OpenAI 兼容 API（`SE_API_BASE` / `SE_API_KEY` / `SE_API_MODEL`）。

## 推荐安装方式（复制给 AI）

````text
请帮我安装 agent-self-evolution 的 Claude Code 平台适配：
1. git clone https://github.com/R03montia/agent-self-evolution.git
2. 运行 bash install.sh claude-code（若 core 未初始化会自动处理）
3. 验证 ~/.claude/settings.local.json（若存在）或 ~/.claude/settings.json 的 hooks.Stop 已注册；若 command 中是 ${CLAUDE_PROJECT_DIR} 占位符且我不用项目级配置，请改成绝对路径 ~/.claude/hooks/collect.sh
4. 确认 ~/.claude/hooks/ 下 collect.sh 与 normalize_claude.py 存在且可执行
````

以下详细步骤供 AI 执行时参考。

## 手动安装

### 方式 A：项目级（仅当前项目生效）

1. 复制 `hooks/` 下两个文件到项目 `.claude/hooks/`；
2. 把 `settings.hooks.json` 中的 `hooks` 片段合并进项目 `.claude/settings.json`；
3. 把 `CLAUDE.md` 放到项目根目录或 `.claude/CLAUDE.md`。

> `settings.hooks.json` 中 `${CLAUDE_PROJECT_DIR}` 占位符仅在项目级有效，会自动展开为项目根目录。

### 方式 B：用户级（所有项目生效）

1. 复制 `hooks/` 下两个文件到 `~/.claude/hooks/`；
2. 把 `settings.hooks.json` 中的 `hooks` 片段合并进 `~/.claude/settings.local.json`（若存在）或 `~/.claude/settings.json`，**并把 command 中的 `${CLAUDE_PROJECT_DIR}` 换成 `~/.claude/hooks/collect.sh` 的绝对路径**（用户级配置中该占位符不可用）；
3. 把 `CLAUDE.md` 放到 `~/.claude/CLAUDE.md`。

## 验证

1. **端到端**：跑一条多步骤任务（多次工具调用），结束后检查 `$SE_ROOT/candidates/` 是否出现候选目录；`$SE_ROOT/logs/experience-log.md` 与 `$SE_ROOT/state.json` 应有对应记录。
2. **手动测试 hook 脚本**：构造样例 stdin 传入（`transcript_path` 指向任意 JSONL 文件即可）：

   ```bash
   echo '{"transcript_path":"/path/to/transcript.jsonl","session_id":"test-session"}' \
     | bash collect.sh
   ```

   - 脚本应始终退出 0；归一化结果出现在 `$SE_ROOT/logs/tmp/<短名>.jsonl`；
   - 无 transcript_path 或空 stdin 时应静默退出。

## 故障排查

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| hook 不触发 | settings 语法错误或位置不对（项目级应在 `.claude/settings.json`，用户级应在 `~/.claude/settings.local.json` 或 `~/.claude/settings.json`）；hooks 片段未正确合并 | 用 `claude doctor` 或手动检查 JSON 合法性，确认 `Stop` 事件与 command 写法 |
| stdin 无 transcript_path | 事件字段缺失 / hook 版本差异 | 手动测试确认 stdin 含 `transcript_path` 字段；collect.sh 对空值会静默退出，属预期行为 |
| 无候选生成 | 工具调用次数不足（默认阈值 5 次，`SE_MIN_TOOL_CALLS` 可调）；LLM 后端缺失 | 检查 `$SE_ROOT/logs/experience-log.md` 中的采集失败记录；按上文「前置条件」配置任一 LLM 后端 |

> 采集失败不会阻塞 / 干扰主 agent：collect.sh 任何一步失败都退出 0，原因记录在经验日志中。
