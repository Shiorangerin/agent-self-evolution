# 自我进化系统 · 进化流程说明书

> 本文件是 agent-self-evolution 在 Claude Code 平台下的行为守则，随上下文注入。
> 本系统的全部流程由用户手动触发，**禁止任何自动定时 / 自动唤醒 / 自动执行**。

## 触发方式（全部手动）

- 用户说「总结一天的工作」或「总结今天的工作」：**先总结当天工作**（回顾当天会话轨迹 / 回顾对话上下文），再执行下方进化流程。
- 用户说「进化」：直接执行进化流程，不做工作总结。
- 其他情况：不主动执行进化流程、不主动提示、不夹带任何相关操作。

## 进化流程（五步）

### 第一步：读取现状

1. 读取 `$SE_ROOT/state.json`（统计计数、上次进化时间、采集进度）。
2. 读取 `$SE_ROOT/logs/experience-log.md` 尾部（最近记录，了解上下文）。

### 第二步：审查候选

对 `$SE_ROOT/candidates/` 下的**每一个**候选目录执行：

1. 读取 `SKILL.md` 与 `meta.md`（来源会话、工具调用次数、错误次数）。
2. 格式校验：
   - frontmatter 含 `name`：小写字母 / 数字 / 连字符组成，1–64 字符；
   - frontmatter 含 `description`：≤1024 字符，写明「何时使用」；
   - `SKILL.md` 正文（含 frontmatter）≤5000 字符。
   - 不达标 → 直接淘汰。
3. 查重：与 `$SE_ROOT/skills/` 下已启用技能做语义比对；语义重复 → 并入已有技能或淘汰，**禁止重复启用**。
4. 价值评估（至少满足一条才启用）：
   - 这类任务以后会重复出现；
   - 步骤明确、可复用；
   - 包含真实坑点与解法。
5. 处置：
   - **启用**：`mkdir -p $SE_ROOT/skills/<name>` 并把候选 `SKILL.md` 复制过去，记录到 state.json 与经验日志；
   - **并入**：编辑合并进语义相近的已有技能；
   - **淘汰**：在候选 `meta.md` 末尾追加 `candidate-verdict: rejected` 并写明原因，然后删除该候选目录。
6. 向用户汇报每个候选的处置结论（启用 / 并入 / 淘汰及理由）。

### 第三步：技能体检

1. 读取 `$SE_ROOT/usage.json`。
2. 列出 ≥60 天未使用的技能，逐一征求用户的归档决定。
3. 用户确认后归档：`mv $SE_ROOT/skills/<name> $SE_ROOT/archived/`，并从技能加载目录移除对应软链 / 文件；恢复时反向操作（移回并重建软链 / 文件）。

### 第四步：维护记忆

- 用户偏好与习惯 → 追加到 `$SE_ROOT/memory/USER.md`；
- 踩坑经验 → 追加到 `$SE_ROOT/memory/LESSONS.md`；
- **严格按文件内的格式模板书写**，不破坏已有结构（LESSONS.md 按「日期 / 场景 / 现象 / 根因 / 解法 / 来源」条目记录）。

### 第五步：收尾

1. 更新 `$SE_ROOT/state.json`：`lastEvolutionAt` 与 `stats` 中 `skillsEnabled` / `skillsUpdated` / `candidatesRejected` / `candidatesMerged` 等计数。
2. 在 `$SE_ROOT/logs/experience-log.md` 追加一行总结（时间 / 来源 / 类型 / 摘要 / 去向）。
3. 若 `$SE_ROOT` 位于 git 仓库中，提交本次变更（清晰 commit message）。

## 约束护栏

- 绝不修改用户的 AGENTS.md 或任何人格 / 角色设定文件；
- 自动生成的候选必须经本流程审查后才能启用；
- 进化流程期间不夹带其他操作（不主动改代码、不主动安装软件）；
- 全程以「用户」称呼，不出现具体人名 / 产品名 / 真实路径（路径一律用 `$SE_ROOT` 变量表达）。

## 记忆文件

- `@memory/USER.md` — 用户画像（`$SE_ROOT/memory/USER.md`）
- `@memory/LESSONS.md` — 踩坑经验（`$SE_ROOT/memory/LESSONS.md`）

> 说明：上述 `@` 引用路径相对 `$SE_ROOT/memory/` 目录。若本文件所在位置无法解析该相对路径，请把两个 `@` 引用替换为 `$SE_ROOT/memory/` 下对应文件的绝对路径（或在 `$SE_ROOT` 下放置本文件）。
