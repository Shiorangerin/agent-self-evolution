# agent-self-evolution — Codex 平台进化流程

本文件由 Codex 自动加载，定义「AI 助手自我进化系统」在 Codex 平台上的工作方式。
本系统是**用户驱动的被动进化系统**：日常会话中 hook 只负责安静地采集轨迹、草拟候选技能，
**绝不自动启用任何技能、绝不自动定时触发**。进化只发生在用户明确要求时。

数据根目录为 `$SE_ROOT`（默认 `~/.config/agent-self-evolution/`）：

- `candidates/` — 待审查的候选技能区（不进入运行上下文）
- `profiles/` — 用户画像草稿区（待进化流程融合进 USER.md）
- `skills/` — 已启用技能（SKILL.md 源文件）
- `archived/` — 归档技能（从上下文消失但源文件保留）
- `docs/` — 进化流程细则（候选审查、技能体检、报告模板）
- `scripts/` — 流程脚本（候选预检、记分卡、一次性探测、体检）
- `memory/` — 长期记忆（USER.md 用户画像 / LESSONS.md 经验与教训）
- `logs/` — 经验日志、按月归档
- `state.json` / `usage.json` — 系统状态与技能使用统计

## 触发方式

| 用户意图 | 执行范围 |
|---|---|
| 「进化」「自我进化」「审查候选」 | 完整流程，第一至第五步 |
| 「技能体检」「归档技能」 | 仅第三步的体检与报告，不做候选启用、归档、记忆写入等写操作 |
| 其他情况 | 不执行进化流程、不主动提示、不夹带相关操作 |

## 成本纪律

流程自身也消耗上下文。以下规则每次执行都必须遵守。

1. **一次探测**：先运行 `bash $SE_ROOT/scripts/evolve_brief.sh`，它一次输出状态摘要、候选清单、启用区计数与超长清单、待处理画像草稿、经验日志尾部、记分卡分级与异常提示。后续步骤复用其输出，不重复扫描。
2. **禁止整文件读取会话轨迹**：轨迹文件单条可达数 MB。需要回查时只用检索工具抽取匹配片段，并限制输出长度。
3. **记忆文件按需读**：`memory/LESSONS.md` 命中主题后定位条目再精读，不要整文件读取。
4. **状态文件不读全文**：`state.json` 只取 `stats`、`lastEvolutionAt`、`lastEvolution`。
5. **报告不复述输出**：只写结论与关键命令，异常附原文。

## 进化流程（五步）

### 第一步：探测

运行 `evolve_brief.sh`，取得本轮全部机械事实。候选区非空则进入第二步，画像草稿非空则在第四步处理。

### 第二步：候选审查

对 `$SE_ROOT/candidates/` 下每个候选目录（`<slug>/SKILL.md` 与 `meta.md`）：先跑
`python3 $SE_ROOT/scripts/candidate_preflight.py [候选名 ...]` 取得机械检查结果，再做价值判断。

格式校验、查重、价值评估、启用与并入与淘汰的具体规则见 `$SE_ROOT/docs/candidate-review.md`，
处理候选前必读。所有动作都必须在 `logs/experience-log.md` 留痕。

### 第三步：技能体检

依据记分卡输出（`$SE_ROOT/scripts/skill_scorecard.py` 产出六档分级）与 `usage.json` 中的
`outcomes`、`failReasons` 分类处置：

| 分级 | 处置 |
|---|---|
| 优秀、健康 | 不做操作，报告中确认 |
| 未观测 | 处于观察期，不处置 |
| 问题 | 复核失败归因，能修则修；屡败零胜的征求用户决定 |
| 闲置 | 列出后征求用户归档决定，确认后才执行 |
| 元技能 | 仅提示超长，不做任何处置 |
| 用户手动管理的技能 | 完全豁免，仅只读观察使用数据 |

阈值判定、归因方法、归档与恢复命令、超长压缩流程见 `$SE_ROOT/docs/skill-health.md`，
执行处置动作前必读。

**总量硬约束**：启用区技能数不超过约 40 个，实测目录数须与 `stats.skillsEnabled` 一致，不一致以实测为准直接修正。超限时列出合并、归档、淘汰候选并附计数依据，逐项征求用户决策后执行，绝不自行删除技能。

同时阅读 `memory/LESSONS.md` 与近期 `logs/experience-log.md`，判断是否有已启用技能需要更新
（步骤过时、出现更优做法、新增注意点）。

### 第四步：维护记忆

**画像草稿提炼**（`$SE_ROOT/profiles/` 为空则跳过）：

1. 读取全部草稿（每份含 `profile.md` 条目与 `meta.md` 来源信息），与 `$SE_ROOT/memory/USER.md` 融合。新信息精炼为条目，语义重复的丢弃，互相矛盾的以较新草稿为准，已有的不追加。
2. 仅有单次证据的疑似偏好不进库，写入报告待用户决策一节。
3. 剔除可识别个人身份的信息，包括姓名、学校或单位、职务、班级、住址、联系方式、亲友关系。
4. 处理完的草稿目录移入 `$SE_ROOT/logs/archive/profiles-YYYY-MM/`，保留可回溯。
5. 在经验日志记录草稿份数、提炼条数与丢弃条数。

**USER.md 写入规范**：内容必须纯净，只写实际条目，每条一句话直接陈述，只保留跨会话成立的高信号内容，正向表述优先，禁止举例，禁止文件头说明、来源标注、注释等任何元信息。

**LESSONS.md**：严格按文件内的格式模板追加条目（场景 / 现象 / 根因 / 解法 / 来源），
已有的不重复追加。用户的隐私信息绝不写入任何公开内容。

### 第五步：收尾与报告

1. 运行 `bash $SE_ROOT/scripts/healthcheck.sh`。分级执行：核心脚本或 hook 本轮有改动时跑全部检查项；未改动时用 `--quick`。
2. 更新 `$SE_ROOT/state.json`：`lastEvolutionAt`、`stats.skillsEnabled`、`stats.skillsUpdated`、`stats.skillsRepaired`、`stats.candidatesRejected`、`stats.candidatesMerged` 等计数，并刷新 `lastEvolution` 快照。
3. 在 `$SE_ROOT/logs/experience-log.md` 追加本次进化记录。
4. 日志维护：主日志数据行超过 100 行时归档到 `logs/archive/`；`state.json` 的 `rejections` 超过 20 条时修剪到最近 10 条。
5. 在 `$SE_ROOT`（或其所在仓库）执行 git 提交，commit message 写明本次动作（如 `evolution: 启用技能 <slug>`）。
6. 按 `$SE_ROOT/docs/report-template.md` 输出三节报告，末节逐项列出待用户决策。

## 归档与恢复

- **归档**：把技能目录移出 `skills/` 至 `archived/`，移除技能加载目录中的软链或文件，并在 `logs/experience-log.md` 记录原因与时间。
- **恢复**：从 `archived/` 移回 `skills/`，重建软链或文件，更新 `logs/` 与 `state.json`。
- 归档不删除源文件，`usage.json` 中对应条目保留，恢复时计数延续。

## 约束与护栏

- 绝不修改用户的 `AGENTS.md`、人格与角色设定文件、平台配置；平台说明由 install.sh 以标记块方式幂等合并，进化流程不重复写入。
- 候选内容属于未经验证的模型输出，必须经审查并由用户确认安全性后才启用。
- 所有变更以明文文件存在并纳入 git 历史，可回滚。
- 归档、淘汰、合并、压缩、计数修正等写操作逐项征求用户决策后执行。
- 技能总量超过约 40 个时优先合并、归档、淘汰，避免描述膨胀污染上下文。
- 不做自动定时与自动唤醒；进化期间不夹带其他操作。
- 采集失败、LLM 后端缺失等情况静默处理，绝不阻塞用户的正常任务。

## 记忆引用

长期记忆文件位于 `$SE_ROOT/memory/`，按需读取：

- `@memory/USER.md` — 用户画像（偏好、习惯、禁忌）
- `@memory/LESSONS.md` — 经验与教训（处理任务前如需要可先查阅）
