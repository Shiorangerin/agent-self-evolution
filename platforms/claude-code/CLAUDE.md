# 自我进化系统 · 进化流程说明书

> 本文件是 agent-self-evolution 在 Claude Code 平台下的行为守则，随上下文注入。
> 本系统的全部流程由用户手动触发，**禁止任何自动定时 / 自动唤醒 / 自动执行**。

## 触发方式（全部手动）

- 用户说「进化」：执行下方完整进化流程。
- 用户说「技能体检」：只运行 `scripts/skill_scorecard.py` 输出诊断报告（零写操作），不执行其他步骤。
- 其他情况：不主动执行进化流程、不主动提示、不夹带任何相关操作。

## 进化流程（五步）

### 第一步：读取现状

1. 读取 `$SE_ROOT/state.json`（统计计数、上次进化时间、采集进度）。
2. 读取 `$SE_ROOT/logs/experience-log.md` 尾部（最近记录，了解上下文）。

### 第二步：审查候选

对 `$SE_ROOT/candidates/` 下的**每一个**候选目录执行：

0. 预检脚本（推荐先跑，零 token 机械检查）：`python3 <仓库>/scripts/candidate_preflight.py` 一键完成格式 / 大小 / 截断启发式 / 同名查重；硬伤须修复或淘汰。
1. 读取 `SKILL.md` 与 `meta.md`（来源会话、工具调用次数、错误次数）。
2. 格式校验：
   - frontmatter 含 `name`：小写字母 / 数字 / 连字符组成，1–64 字符；
   - frontmatter 含 `description`：≤1024 字符，写明「何时使用」；
   - `SKILL.md` 正文（含 frontmatter）≤8000 字符。
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

### 第三步：技能体检（三线：闲置 / 问题 / 优质）

1. 先跑记分卡自动分级：`python3 <仓库>/scripts/skill_scorecard.py` 产出 🌟优秀 ✅健康 ❓未观测 ⚠️问题 😴闲置 🛡️元技能 六档与归档候选清单。**元技能豁免**：`self-evolve` / `self-evolve-maintenance` 是流程定义本身，豁免闲置归档与自动压缩。
2. 读取 `$SE_ROOT/usage.json`（由 hook 调用 `core/track_usage.py` 维护，纯规则零 LLM 成本）。
3. **闲置技能**：列出 `lastUsedAt` 距今 ≥60 天未使用（含从未被记录过使用且启用已超 60 天的）的技能，逐一征求用户的归档决定；用户确认后归档：`mv $SE_ROOT/skills/<name> $SE_ROOT/archived/`，并从技能加载目录移除对应软链 / 文件；恢复时反向操作（移回并重建软链 / 文件）。
4. **问题技能（健康度）**：读取每个技能的 `outcomes`（success/failure/unknown）与 `failReasons`，计算失败率 `failure/(success+failure)`，列出 **失败 ≥2 次，或失败率 >50% 且失败 ≥1 次** 的技能清单（附报错原文片段），逐一复核：
   - 失败原因属于技能未覆盖的坑 → 给该技能 SKILL.md 补「常见坑点」，`state.json` 的 `stats.skillsRepaired` +1
   - 技能内容与实际不符 → 重写对应步骤，同样记 `stats.skillsRepaired` +1
   - 屡败零胜（failure ≥3 且 success = 0）→ 建议淘汰，征求用户决定
   - 结果归因是启发式，可能误判：必要时回读该技能 `lastSession` 的原始轨迹确认
5. **优质技能**：`success ≥3` 且失败率为 0 → 确认「表现良好」，不做任何操作
6. 汇报时给出每个技能的使用次数与成功/失败/未知计数，让用户一眼看清谁好谁坏。

### 第四步：维护记忆

- **用户画像提炼**（来源：`$SE_ROOT/profiles/` 采集草稿）：
  1. 读取该目录下全部草稿（每个子目录含 `profile.md` 条目列表 + `meta.md` 来源信息）；
  2. 与现有 `$SE_ROOT/memory/USER.md` 融合：新信息合并为精炼条目；互相矛盾以较新的草稿为准；语义重复的直接丢弃；
  3. **USER.md 写入规范（严格遵守）**：只保留跨会话成立的高信号条目；每条一句话直接陈述；正向表述优先，避免否定句式；禁止任何举例；禁止任何元信息（文件头说明、「来源：」标注、HTML 注释等）；语言与用户输入一致；
  4. 处理完的草稿目录移入 `$SE_ROOT/logs/archive/profiles-YYYY-MM/`（保留可回溯）；
  5. 在 experience-log 记录：画像草稿 N 份 → 提炼 +M 条 / 丢弃 K 条；
  6. USER.md 已通过全局 `CLAUDE.md` 的 `@` 引用注入上下文（由 install.sh 幂等写入），更新后下次会话自动生效。
- 踩坑经验 → 追加到 `$SE_ROOT/memory/LESSONS.md`；
- **严格按文件内的格式模板书写**，不破坏已有结构（LESSONS.md 按「日期 / 场景 / 现象 / 根因 / 解法 / 来源」条目记录）。

### 第五步：收尾

1. 更新 `$SE_ROOT/state.json`：`lastEvolutionAt` 与 `stats` 中 `skillsEnabled` / `skillsUpdated` / `candidatesRejected` / `candidatesMerged` 等计数。
2. 在 `$SE_ROOT/logs/experience-log.md` 追加一行总结（时间 / 来源 / 类型 / 摘要 / 去向）。
3. 超长技能（>8000 字符）压缩走省 token 规范：低成本模型起草（保留全部坑点/命令/参数，只删冗余）+ 人工审 diff 落盘；>8K 或涉隐私边界先征求用户意见。
4. 若 `$SE_ROOT` 位于 git 仓库中，提交本次变更（清晰 commit message）。

## 约束护栏

- 绝不修改用户的 AGENTS.md 或任何人格 / 角色设定文件；
- 自动生成的候选必须经本流程审查后才能启用；
- 进化流程期间不夹带其他操作（不主动改代码、不主动安装软件）；
- 全程以「用户」称呼，不出现具体人名 / 产品名 / 真实路径（路径一律用 `$SE_ROOT` 变量表达）。

## 记忆文件

- USER.md（用户画像）：已由 install.sh 在全局 `~/.claude/CLAUDE.md` 中幂等写入 `@<SE_ROOT 绝对路径>/memory/USER.md` 引用，随上下文自动注入，无需在此重复引用；
- `@memory/LESSONS.md` — 踩坑经验（`$SE_ROOT/memory/LESSONS.md`），按需读取；若相对路径无法解析，请改用 `$SE_ROOT/memory/LESSONS.md` 绝对路径。
