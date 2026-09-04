# Pi 平台适配（pi-coding-agent）

Pi 平台通过两个扩展 + 一个技能接入 agent-self-evolution：

| 组件 | 作用 |
| --- | --- |
| `extensions/self-evolve.ts` | 经验采集器：每次任务结束（`agent_settled`）后台分析轨迹，满足条件时用低成本 LLM 并行发起两路独立采集（失败互不影响）：① 技能候选 → `$SE_ROOT/candidates/`；② 用户画像草稿 → `$SE_ROOT/profiles/` |
| `extensions/skill-usage.ts` | 技能使用统计：纯规则扫描轨迹，记录技能使用信号到 `$SE_ROOT/usage.json`，供进化流程做「长期未使用技能」体检 |
| `skills/self-evolve/SKILL.md` | 进化流程说明书：用户说「总结一天的工作」/「进化」时，指导 agent 执行候选审查、技能更新、记忆维护、git 提交 |

## 推荐安装方式（复制给 AI）

````text
请帮我安装 agent-self-evolution 的 Pi 平台适配：
1. git clone https://github.com/Shiorangerin/agent-self-evolution.git
2. 运行 bash install.sh pi（确认 ~/.pi/agent 存在，python3 可用）
3. 验证 ~/.pi/agent/extensions/ 下有 self-evolve.ts、skill-usage.ts，~/.pi/agent/skills/self-evolve/ 存在
4. 提醒我之后在 pi 里执行 /reload 让扩展生效
````

以下详细步骤供 AI 执行时参考。

## 手动安装

### 1. 初始化数据目录

```bash
python3 core/init.py
# 或直接运行仓库根目录的 install.sh（交互式）
```

默认数据目录：`~/.config/agent-self-evolution/`（可用环境变量 `SE_ROOT` 覆盖）。

### 2. 安装扩展

```bash
cp platforms/pi/extensions/self-evolve.ts ~/.pi/agent/extensions/
cp platforms/pi/extensions/skill-usage.ts ~/.pi/agent/extensions/
```

然后在 pi 里执行 `/reload` 热重载（无需重启）。确认方式：完成任务后看 `$SE_ROOT/state.json` 的 `lastSeenAt` 是否更新。

### 3. 安装进化技能

```bash
mkdir -p ~/.pi/agent/skills/self-evolve
cp platforms/pi/skills/self-evolve/SKILL.md ~/.pi/agent/skills/self-evolve/SKILL.md
```

`/reload` 后，pi 即可识别 `self-evolve` 技能。之后对 pi 说「总结一天的工作」或「进化」即可触发。

### 4. LLM 后端

Pi 扩展默认使用内置**免费模型链**（按序降级），无需额外配置；采集使用 `reasoningEffort: "low"` 与受限 `maxTokens` 控制成本。

内置链模型须存在于你的 `~/.pi/agent/models.json`，否则会被过滤；若你的环境没有这些模型，或想换成自己的便宜/免费模型，在 `$SE_ROOT/config.json` 的 `collector.models` 配置自选链（优先生效）：

```json
{
  "collector": {
    "models": [{ "provider": "your-provider", "id": "your-cheap-model" }]
  }
}
```

⚠️ 不要把昂贵模型填进采集链：采集是高频后台调用。

## 使用

- **自动采集**：无需操作，扩展在每次任务结束后安静沉淀候选（不打扰、不进上下文）。采用增量采集——同一会话可多次采集，每次只分析上次采集点之后的新内容。
- **每日总结 + 进化**：对 pi 说「总结一天的工作」「总结今天的工作」→ 先总结当天工作，再执行进化流程。
- **纯进化**：说「进化」或运行 `/skill:self-evolve`。
- **手动采集**：`/evolve-collect`（绕过节流，立即分析当前会话并草拟候选）。

## 验证

1. 完成一个多步骤任务（工具调用 ≥5 次）后，检查 `$SE_ROOT/candidates/` 是否出现新候选目录
2. `cat $SE_ROOT/state.json` 查看 `stats` 计数是否增长
3. 说「进化」走一遍审查流程，看候选是否能正常启用（mkdir + cp + 软链三步）

## 常见问题

| 问题 | 排查 |
| --- | --- |
| 扩展不生效 | 检查文件是否在 `~/.pi/agent/extensions/`，执行 `/reload`；`bun build <file> --no-bundle --target=bun` 做语法检查 |
| 候选区不增长 | 检查 `$SE_ROOT/state.json` 的 `rejections`（记录了不满足条件/LLM 拒绝的原因）；`logs/experience-log.md` 有每次采集的流水 |
| 提示模型凭证问题 | Pi 扩展依赖 pi 的登录模型（`modelRegistry`），确认 pi 本身可用 |
| 技能不生效 | 启用技能的流程是「源文件 + 软链」两步：`$SE_ROOT/skills/<name>/SKILL.md` 与 `~/.pi/agent/skills/<name>` 软链缺一不可 |
