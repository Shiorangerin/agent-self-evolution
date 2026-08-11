---
name: self-evolve
description: agent-self-evolution 的每日工作总结 + 自我进化流程（用户手动触发模式）。当用户说"总结一天的工作""总结今天的工作""总结一下今天""进化""自我进化""沉淀技能""技能候选""进化一下"时触发。流程：回顾当天会话 → 向用户汇报工作总结 → 审查 <SE_ROOT>/candidates/ 中的技能候选（校验格式、查重、评估价值后启用或淘汰）→ 根据近期经验更新现有技能 → 维护 USER.md/LESSONS.md 记忆 → 更新 state.json 与经验日志 → git 提交。
---

# 每日工作总结 + 自我进化流程

> 本流程由用户**手动触发**，没有任何自动定时唤醒。用户说一声就做，不说就不做。

## 前置理解

进化系统数据位于 `$SE_ROOT`（默认 `~/.config/agent-self-evolution/`，可通过环境变量 `SE_ROOT` 覆盖），架构见仓库 `README.md`：

- `candidates/`：经验采集器在任务结束后自动沉淀的候选技能（未启用，不进上下文）
- `skills/`：已启用技能的源文件，在 Pi 上通过软链挂到 `~/.pi/agent/skills/` 生效
- `memory/USER.md`、`memory/LESSONS.md`：长期记忆（用户画像 / 踩坑经验）
- `logs/experience-log.md`：经验沉淀日志（可追溯）
- `logs/session-summaries/`：每日工作总结存档
- `state.json`：系统状态与统计

## 触发分类

- 用户说 **「总结一天/今天的工作」** 或类似 → 执行【第一部分】+【第二部分】
- 用户说 **「进化」** 或 `/skill:self-evolve` → 只执行【第二部分】

---

## 第一部分：总结一天的工作

1. 找到今天的会话记录：`~/.pi/agent/sessions/` 下按日期筛选今天修改的 `.jsonl` 文件
   （可参考 `$SE_ROOT/logs/session-summaries/` 里已有的总结，避免重复总结同一个会话）
2. 阅读会话要点（用户请求、完成的任务、工具使用、结果），归纳今天完成的工作
3. 向用户输出一份简洁的工作总结：今天做了哪些事（按主题分组）、哪些已完成/未完成、有什么值得注意的经验
4. 把总结存档到 `$SE_ROOT/logs/session-summaries/YYYY-MM-DD.md`
5. 若今天的会话中有值得沉淀的经验但采集器没捕捉到，记录下来进入进化环节

## 第二部分：进化流程

### 第一步：初始化

1. 用 `bat` 阅读 `$SE_ROOT/state.json`，了解当前统计
2. 用 `bat` 阅读 `$SE_ROOT/logs/experience-log.md` 尾部，了解最近沉淀情况

### 第二步：审查候选技能

用 `eza -la $SE_ROOT/candidates/` 列出候选（每个子目录一个候选，含 `SKILL.md` + `meta.md`）。

对每个候选逐一执行（先 `bat` 阅读 `SKILL.md` 与 `meta.md`，meta 里有来源会话、工具/错误计数）：

**① 格式校验（任一不满足即淘汰）**
- frontmatter 有 `name`：小写字母数字连字符，1-64 字符
- frontmatter 有 `description`：中文，≤1024 字符，写明了「何时使用」
- SKILL.md 总大小 ≤ 5000 字符（审查时先 `wc -c SKILL.md` 实测；多个候选超限且内容重叠时，先合并压缩到限内再启用，而不是直接全淘汰）

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

0. **技能体检（使用情况报告）**：读取 `$SE_ROOT/usage.json`（由扩展 skill-usage 维护，纯规则零 LLM 成本），对每个已启用技能计算 `lastUsedAt` 距今天数，列出 **≥60 天未使用**的技能清单（含最后使用时间、次数），向用户汇报并**征求归档决定**：
   - 用户确认归档 → 执行归档操作（见下方「归档技能」）
   - 用户决定保留 → 不动，记入汇报
   - 从未被记录过使用（usage.json 无条目）且启用已超 60 天的技能，同样列入清单提示

阅读 `memory/LESSONS.md`、今天的会话总结与近期 `experience-log.md`，判断是否有现有技能需要更新：
- 步骤过时/有更优做法/有新增坑点 → 用 `edit` 修改 `$SE_ROOT/skills/<name>/SKILL.md`（软链指向源文件）
- 已启用技能若长期未被使用或与新的候选重叠 → 考虑合并/淘汰

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

- 从今天的工作总结、经验日志提炼用户偏好与习惯 → 追加到 `memory/USER.md`
- **USER.md 规范（重要）**：若 USER.md 通过系统提示注入（如 Pi 的 `APPEND_SYSTEM.md` 软链），内容**必须纯净**——只写实际内容条目（偏好/习惯/禁忌本身），**禁止**添加文件头说明、`来源：xxx` 标注、HTML 注释等与内容无关的元信息，条目精炼无冗余
- 提炼踩坑经验 → 追加到 `memory/LESSONS.md`（严格按文件中的格式模板；LESSONS.md 若不注入 prompt，可保留「来源」标注用于追溯）
- 记忆条目要精炼，避免重复；已有的不再追加

### 第五步：收尾

1. 更新 `state.json`：`lastEvolutionAt`（当前时间）、`stats.skillsEnabled`、`stats.skillsUpdated`、`stats.candidatesRejected` 等计数
2. 在 `experience-log.md` 追加本次进化总结行：`| 时间 | - | 进化 | 审查X候选：启用A/淘汰B/并入C；更新技能D；记忆+E | - |`
3. git 提交（保证可追溯回滚；若 `$SE_ROOT` 或其所在目录是 git 仓库）：
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

## 汇报格式

完成后向用户简要汇报：
1. 今天的工作总结（做了什么、完成/未完成）
2. 审查了多少候选：启用 X / 淘汰 Y（各一句话原因）/ 并入 Z
3. 更新了哪些现有技能
4. 记忆新增了什么
5. git commit 摘要
