---
name: self-evolve
description: agent-self-evolution 的自我进化流程（用户手动触发模式）。当用户说"进化""自我进化""沉淀技能""技能候选""进化一下""技能体检"时触发。流程：审查 <SE_ROOT>/candidates/ 中的技能候选（预检脚本 + 价值评估后启用或淘汰）→ 技能体检（记分卡诊断，归档/淘汰逐项征求用户决策）→ 根据近期经验更新现有技能 → 维护 USER.md/LESSONS.md 记忆 → 更新 state.json 与经验日志 → git 提交 → 按固定模板输出进化报告。
---

# 自我进化流程

> 本流程由用户**手动触发**，没有任何自动定时唤醒。用户说一声就做，不说就不做。

## 前置理解

进化系统数据位于 `$SE_ROOT`（默认 `~/.config/agent-self-evolution/`，可通过环境变量 `SE_ROOT` 覆盖），架构见仓库 `README.md`：

- `candidates/`：经验采集器在任务结束后自动沉淀的候选技能（未启用，不进上下文）
- `skills/`：已启用技能的源文件，在 Pi 上通过软链挂到 `~/.pi/agent/skills/` 生效
- `memory/USER.md`、`memory/LESSONS.md`：长期记忆（用户画像 / 踩坑经验）
- `logs/experience-log.md`：经验沉淀日志（可追溯）
- `logs/session-summaries/`：~~每日工作总结存档~~（功能已删除，仅存历史）
- `state.json`：系统状态与统计

## 触发

用户说 **「进化」** 或 `/skill:self-evolve` 即启动下方完整流程；说 **「技能体检」** 则只跑记分卡诊断与报告（第三步的体检部分），不做候选启用等写操作。

---

## 进化流程

### 第一步：初始化

1. 用 `python3`/`jq` 只读 `$SE_ROOT/state.json` 的**统计摘要**（`stats`、`lastEvolutionAt`、`lastCollectionAt`），**不读全文**——`rejections`/`collectedUpTo` 明细不进上下文，仅在需要时按需查看
2. 用 `tail -30 $SE_ROOT/logs/experience-log.md` 只看尾部，了解最近沉淀情况（完整历史在 `logs/archive/` 按月归档）

### 第二步：审查候选技能

用 `eza -la $SE_ROOT/candidates/` 列出候选（每个子目录一个候选，含 `SKILL.md` + `meta.md`）。

**⓪ 预检脚本（推荐先跑，零 token 机械检查）**
`python3 <仓库>/scripts/candidate_preflight.py` 一键完成下方格式 / 大小 / 截断启发式（代码围栏不闭合、尾部中断）/ 同名查重的机械检查；硬伤须修复或淘汰，警示项人工复核。

对每个候选逐一执行（先阅读 `SKILL.md` 与 `meta.md`，meta 里有来源会话、工具/错误计数）：

**① 格式校验（任一不满足即淘汰）**
- frontmatter 有 `name`：小写字母数字连字符，1-64 字符
- frontmatter 有 `description`：中文，≤1024 字符，写明了「何时使用」
- SKILL.md 总大小 ≤ 8000 字符（软上限；多个候选超限且内容重叠时，先合并压缩到限内再启用，而不是直接全淘汰）

**② 查重**
- 对比 `~/.pi/agent/skills/` 现有技能，语义重复或高度重叠 → 合并进现有技能或淘汰

**③ 价值评估**
- 这类任务以后会重复出现吗？步骤清晰、可复用吗？有真实经验/坑点吗？
- 一次性的琐碎内容、明显噪声 → 淘汰

**处置**

- **通过 → 启用**（候选区 → 启用区 + 软链）：
  ```bash
  mkdir -p $SE_ROOT/skills/<name>
  cp $SE_ROOT/candidates/<slug>/SKILL.md $SE_ROOT/skills/<name>/SKILL.md
  ln -sfn $SE_ROOT/skills/<name> ~/.pi/agent/skills/<name>
  ```
  然后在 `experience-log.md` 追加一行：`| 时间 | <slug> | 启用 | <一句话摘要> | skills/<name>/ |`

- **淘汰**：在候选目录的 `meta.md` 末尾追加 `candidate-verdict: rejected` 与原因，然后删除该候选目录（或在日志中说明保留原因）。若候选质量过差直接删除并记日志。
- 每个候选（无论启用/并入/淘汰）审查后都在其 `meta.md` 末尾追加 `candidate-verdict: enabled/merged/rejected` 与一句原因，便于追溯与防误删。

- **并入现有技能**：用 `edit` 把有价值内容合并进对应技能的 SKILL.md，再删除候选。

### 第三步：更新现有技能

0. **技能体检（使用情况报告）**：先跑 `python3 <仓库>/scripts/skill_scorecard.py` 自动产出六档分级（🌟优秀 ✅健康 ❓未观测 ⚠️问题 😴闲置 🛡️元技能）与归档候选清单；再读取 `$SE_ROOT/usage.json` 复核数据，向用户汇报并征求处置决定：

   **元技能豁免**：`self-evolve` / `self-evolve-maintenance` 是进化流程定义本身，豁免闲置归档与自动压缩（规则不得吃掉自己的元规则）；其超长问题仅提示，结构优化须用户决策。

   **① 闲置技能**：`lastUsedAt` 距今天数 **≥60 天** 未使用（含从未被记录过使用且启用已超 60 天的），列出清单（最后使用时间、次数），征求归档决定：
   - 用户确认归档 → 执行归档操作（见下方「归档技能」）
   - 用户决定保留 → 不动，记入汇报

   **② 问题技能（健康度）**：读取每个技能的 `outcomes`（success/failure/unknown）与 `failReasons`，计算失败次数与失败率 `failure/(success+failure)`，列出 **失败 ≥2 次，或失败率 >50% 且失败 ≥1 次** 的技能清单（附 failReasons 报错原文片段），逐一复核处置：
   - 先看 `usage.json` 里的 `failReasons`，必要时回会话记录读该技能 `lastSession` 的原始轨迹确认失败原因（结果归因是启发式，可能误判，以原始轨迹为准）
   - **坑点缺失**：失败原因属于技能未覆盖的场景/坑 → 用 `edit` 给该技能 SKILL.md 补「常见坑点」，`state.json` 的 `stats.skillsRepaired` +1
   - **步骤错误/过时**：技能内容与实际不符 → 用 `edit` 重写对应步骤，同样记 `stats.skillsRepaired` +1
   - **屡败零胜**（failure ≥3 且 success = 0）→ 建议淘汰，征求用户决定
   - 拿不准的向用户汇报求决策，绝不自行删技能

   **③ 优质技能**：`success ≥3` 且失败率为 0 的技能 → 汇报中确认「表现良好」，不做任何操作

   汇报时给出每个技能的使用次数与成功/失败/未知计数，让用户一眼看清谁好谁坏。

阅读 `memory/LESSONS.md`、今天的会话总结与近期 `experience-log.md`，判断是否有现有技能需要更新：
- 步骤过时/有更优做法/有新增坑点 → 用 `edit` 修改 `$SE_ROOT/skills/<name>/SKILL.md`（软链指向源文件）
- 已启用技能若长期未被使用或与新的候选重叠 → 考虑合并/淘汰

### 超长技能压缩（省 token 规范）

不在主会话人肉重写超长技能：
1. 用低成本模型起草压缩稿：prompt 附原 SKILL.md 全文 + 硬约束（保留全部坑点/命令/参数/实测结论，只删冗余叙述、重复示例；≤8000 字符）
2. 人工只审 diff 确认零信息损失后落盘；拿不准的段落保留原状
3. 单技能 >8K 或涉及用户隐私边界的，先逐项征求用户意见再动

### 归档技能（用户确认后执行）

归档 = 让技能从上下文消失但源文件与历史保留（区别于删除）：

```bash
mkdir -p $SE_ROOT/archived
mv $SE_ROOT/skills/<name> $SE_ROOT/archived/<name>   # 源文件移入存档区
unlink ~/.pi/agent/skills/<name>                     # 移除软链（技能从上下文消失）
```

恢复（用户需要时）：

```bash
ln -sfn $SE_ROOT/archived/<name> ~/.pi/agent/skills/<name>
```

归档/恢复后：`usage.json` 中对应条目保留（恢复时计数延续）；在 `experience-log.md` 记录归档/恢复行；git 提交保证可回滚。

### 第四步：维护记忆

- **用户画像提炼**（来源：`$SE_ROOT/profiles/` 采集草稿）：
  1. 读取该目录下全部草稿（每个子目录含 `profile.md` 条目列表 + `meta.md` 来源信息）；
  2. 与现有 `memory/USER.md` 融合：新信息合并为精炼条目；互相矛盾以较新的草稿为准；语义重复的直接丢弃；
  3. **USER.md 写入规范（严格遵守）**：只保留跨会话成立的高信号条目；每条一句话直接陈述；**正向表述优先，避免否定句式**；**禁止任何举例**；内容**必须纯净**——禁止文件头说明、`来源：xxx` 标注、HTML 注释等任何元信息（USER.md 若通过系统提示注入如 Pi 的 `APPEND_SYSTEM.md` 软链，错误条目会持续影响行为）；语言与用户输入一致；
  4. 处理完的草稿目录移入 `logs/archive/profiles-YYYY-MM/`（保留可回溯，不删除）；
  5. 在经验日志记录：画像草稿 N 份 → 提炼 +M 条 / 丢弃 K 条。
- 提炼踩坑经验 → 追加到 `memory/LESSONS.md`（严格按文件中的格式模板；LESSONS.md 若不注入 prompt，可保留「来源」标注用于追溯）
- 记忆条目要精炼，避免重复；已有的不再追加

### 第五步：收尾

1. 更新 `state.json`：`lastEvolutionAt`（当前时间）、`stats.skillsEnabled`、`stats.skillsUpdated`、`stats.candidatesRejected`、`stats.skillsRepaired`（本次修复/补坑的技能数）等计数
2. 在 `experience-log.md` 追加本次进化总结行：`| 时间 | - | 进化 | 审查X候选：启用A/淘汰B/并入C；更新技能D；记忆+E | - |`
3. **日志维护**（保持文件精简，避免进化时读取膨胀）：
   - `experience-log.md` 数据行超过 100 行时，把旧条目归档到 `logs/archive/experience-log-YYYY-MM.md`（表头保留，主文件只留最近 40 条）
   - `state.json` 的 `rejections` 超过 20 条时修剪到最近 10 条（历史在归档日志里）
   - `collectedUpTo` 由扩展自动清理（只保留仍存在的会话），无需手动处理
4. git 提交（保证可追溯回滚；若 `$SE_ROOT` 或其所在目录是 git 仓库）：
   ```bash
   cd <仓库根> && git add <SE_ROOT 相对路径>
   git commit -m "self-evolve: <今日工作总结+进化摘要>"
   ```

## 约束与安全护栏（必须遵守）

- **绝不修改** 用户的 `AGENTS.md`、TODO 等用户主导的规则与私密文件；进化流程**不主动改动**用户已有配置文件
- 自动生成的候选必须经本流程审查后才启用，不直接信任采集器输出
- 所有变更以明文文件存在，透明、可回滚（git 历史）
- 启用区技能总量控制：超过约 40 个时优先合并/淘汰，避免 description 污染上下文
- 进化过程只做与进化相关的事，不夹带其他操作
- **不做任何自动定时/自动唤醒**：除非用户主动说，否则不自行启动本流程

## 汇报格式（固定模板，每次进化结束必须完整按此向用户汇报）

## 🧬 进化报告 <YYYY-MM-DD HH:MM>

**1️⃣ 候选审查（共 X 个）**

| 候选 | 结论 | 原因 |
|---|---|---|
| <slug> | ✅启用 / ❌淘汰 / 🔀并入 | 一句话原因 |

**2️⃣ 技能变更**
- 新启用：<name>（来源会话）
- 更新：<name>：改了什么、为什么
- 归档/淘汰：<name>：依据（count / lastUsedAt / failReasons ＋ 用户决策）

**3️⃣ 记忆与文档**
- LESSONS.md：新增 N 条（各一句话主题）
- USER.md / 其他文档变更

**4️⃣ 关键命令与结果**（只列关键命令不贴全文输出；异常必须原文附上）

| 命令 | 结果 |
|---|---|
| healthcheck.sh / 预检 / 记分卡 | 结果摘要 |
| git commit | hash 与 message 首行 |

**5️⃣ 系统状态**
- state.json 计数变化（skillsEnabled / evolutions 等，前 → 后）
- 记分卡摘要：优秀/健康/未观测/问题/闲置/元技能 各几个
- 本轮 LLM 调用次数与成本备注

**6️⃣ 待用户决策**（逐项列出；无则写「无」）
