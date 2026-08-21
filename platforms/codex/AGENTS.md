# agent-self-evolution — Codex 平台进化流程

本文件由 Codex 自动加载，定义「AI 助手自我进化系统」在 Codex 平台上的工作方式。
本系统是**用户驱动的被动进化系统**：日常会话中 hook 只负责安静地采集轨迹、草拟候选技能，
**绝不自动启用任何技能、绝不自动定时触发**。进化只发生在用户明确要求时。

数据根目录为 `$SE_ROOT`（默认 `~/.config/agent-self-evolution/`）：
- `candidates/` — 待审查的候选技能区（不进入运行上下文）
- `skills/` — 已启用技能（SKILL.md 源文件）
- `memory/` — 长期记忆（USER.md 用户画像 / LESSONS.md 踩坑经验）
- `logs/` — 经验日志、启用/淘汰记录、被拒草稿
- `state.json` — 系统状态与统计
- `usage.json` — 技能使用统计

## 触发方式

只有用户手动触发才进入进化流程。典型说法：

- 「进化」「自我进化」「沉淀技能」「审查候选」
- 「技能体检」「归档技能」

## 进化流程（五步）

### 第一步：审查候选

读取 `$SE_ROOT/candidates/` 下每个候选目录（`<slug>/SKILL.md` + `meta.md`），逐项审查：

1. **格式校验**（任一不满足即淘汰）：
   - frontmatter `name`：仅小写字母、数字、连字符（`^[a-z0-9-]+$`），不带引号
   - `description`：中文，≤1024 字符，写明「何时使用」
   - SKILL.md 正文：总长 ≤8000 字符（可先用 `scripts/candidate_preflight.py` 零 token 预检）
2. **查重**：与 `$SE_ROOT/skills/` 下已启用技能对比（名称与语义），重复的必须淘汰
3. **价值评估**：判断是否可复用——有明确步骤流程、常见坑点、会重复出现的任务才值得启用；
   一次性的琐碎问答、闲聊直接淘汰

### 第二步：启用 / 并入 / 淘汰

对每个候选三选一，**所有动作都必须在 `logs/` 留痕**：

- **启用**（全新技能）：`mkdir -p skills/<slug>/` → `cp candidates/<slug>/SKILL.md skills/<slug>/SKILL.md`
  → 在 `logs/experience-log.md` 记录（技能名、来源会话、启用时间）→ 删除候选目录
- **并入**（与已有技能高度相关）：用 edit 把候选内容合并进 `skills/<已有>/SKILL.md`，
  更新 description 与正文 → 在 `logs/` 记录并入来源 → 删除候选目录
- **淘汰**（格式不符 / 重复 / 无价值）：在 `candidates/<slug>/meta.md` 末尾追加
  `verdict: rejected` + 原因 + 日期 → 删除候选目录

### 第三步：技能体检（三线：闲置 / 问题 / 优质）

读取 `$SE_ROOT/usage.json`（由 hook 调用 `core/track_usage.py` 维护，纯规则零 LLM 成本），
对每个已启用技能做三线体检，向用户汇报并征求处置决定：

1. **闲置技能**：`lastUsedAt` 距今 **≥60 天** 未使用（含从未被记录过使用且启用已超 60 天的），
   列出清单（最后使用时间、次数），征求归档决定——用户确认才归档，不可自作主张。
2. **问题技能（健康度）**：读取每个技能的 `outcomes`（success/failure/unknown）与
   `failReasons`，计算失败率 `failure/(success+failure)`，列出 **失败 ≥2 次，或失败率 >50% 且失败 ≥1 次**
   的技能清单（附报错原文片段），逐一复核：
   - 失败原因属于技能未覆盖的坑 → 给该技能 SKILL.md 补「常见坑点」，`state.json` 的 `stats.skillsRepaired` +1
   - 技能内容与实际不符 → 重写对应步骤，同样记 `stats.skillsRepaired` +1
   - 屡败零胜（failure ≥3 且 success = 0）→ 建议淘汰，征求用户决定
   - 结果归因是启发式，可能误判：必要时回读该技能 `lastSession` 的原始轨迹确认
3. **优质技能**：`success ≥3` 且失败率为 0 → 确认「表现良好」，不做任何操作

汇报时给出每个技能的使用次数与成功/失败/未知计数，让用户一眼看清谁好谁坏。

### 第四步：维护记忆

- `USER.md`（用户画像）：只在用户明确告知时更新；用户的隐私信息绝不写入任何公开内容
- `LESSONS.md`（踩坑经验）：从会话轨迹与本次进化中发现的新坑点，按模板追加
  （场景 / 现象 / 根因 / 解法 / 来源），已有的重复经验不重复记录

### 第五步：收尾

1. 更新 `$SE_ROOT/state.json`：stats（skillsEnabled / skillsUpdated / candidatesMerged 等）、
   lastEvolutionAt、本次进化摘要
2. 在 `logs/experience-log.md` 追加本次进化记录
3. 在 `$SE_ROOT`（或其所在仓库）执行 git 提交，commit message 写明本次进化动作
   （如 `evolution: 启用技能 <slug>`、`evolution: 淘汰候选 <slug>`）

## 归档与恢复

- **归档**：把技能目录移出 `skills/` 至归档位置（如 `logs/archived-skills/<slug>/`），
  并在 `logs/` 记录归档原因与时间
- **恢复**：从归档位置移回 `skills/`，更新 `logs/` 与 `state.json`

## 约束护栏

- 绝不修改用户的 AGENTS.md、人格文件与平台配置
- 候选技能必须经用户确认（或按上述流程审查通过）后才能启用，禁止未经审查自动启用
- 不做自动定时触发，一切进化动作以用户手动指令为准
- 采集失败、LLM 后端缺失等情况静默处理，绝不阻塞用户的正常任务

## 记忆引用

长期记忆文件位于 `$SE_ROOT/memory/`（默认 `~/.config/agent-self-evolution/memory/`），
按需读取：

- `@memory/USER.md` — 用户画像（偏好、习惯、禁忌）
- `@memory/LESSONS.md` — 踩坑经验（长期记忆，处理任务前如需要可先查阅）
