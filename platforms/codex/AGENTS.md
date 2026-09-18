# agent-self-evolution — Codex 平台进化流程

本文件由 Codex 自动加载，定义「AI 助手自我进化系统」在 Codex 平台上的工作方式。
本系统是**用户驱动的被动进化系统**：日常会话中 hook 只负责安静地采集轨迹、草拟候选技能，
**绝不自动启用任何技能、绝不自动定时触发**。进化只发生在用户明确要求时。

数据根目录为 `$SE_ROOT`（默认 `~/.config/agent-self-evolution/`）：
`candidates/` 候选区、`profiles/` 画像草稿区、`skills/` 已启用技能、`archived/` 归档技能、
`docs/` 流程细则、`scripts/` 流程脚本、`memory/` 长期记忆、`logs/` 经验日志、
`state.json` 系统状态、`usage.json` 技能使用统计。

## 触发

| 用户意图 | 执行范围 |
|---|---|
| 「进化」「自我进化」「审查候选」 | 完整流程，第一至第五步 |
| 「技能体检」「归档技能」 | 仅第三步的体检与报告，不做写操作 |
| 其他情况 | 不执行、不主动提示、不夹带相关操作 |

## 成本纪律

流程耗时几乎全部来自模型往返，减少往返次数优先于减少读取字节。快速通道 4 次以内，常规路线 10 次以内。

1. **先探测**：`bash $SE_ROOT/scripts/evolve_brief.sh` 一次给出状态、候选、体检分级、草稿、日志尾部、**本轮走向**与异常，按其结论选路线，不重复扫描。
2. **轨迹只定点回查**：`python3 $SE_ROOT/scripts/evolve_trail.py <会话片段> <关键词> --max 30 --chars 8000`，不要整文件读取会话轨迹。
3. **按需读**：`memory/LESSONS.md` 只读相关片段；`state.json` 只取 `stats`、`lastEvolutionAt`、`lastEvolution`。
4. **合并往返**：互不依赖的命令放在同一次调用里，收尾一次性交给 evolve_finish.py。
5. **报告不复述输出**：只写结论与关键命令，正文不超过 1200 字。

## 五步流程

1. **探测**：跑 `evolve_brief.sh`。快速通道下直接跳到第五步。
2. **候选审查**：对 `$SE_ROOT/candidates/` 每个候选（`<slug>/SKILL.md` 与 `meta.md`）先跑 `python3 $SE_ROOT/scripts/candidate_preflight.py`，再做价值判断。细则见 `$SE_ROOT/docs/candidate-review.md`，处理候选前必读；所有动作都要在 `logs/experience-log.md` 留痕。
3. **技能体检**：按记分卡分级处置，细则见 `$SE_ROOT/docs/skill-health.md`，执行处置动作前必读。
4. **维护记忆**：画像草稿融合进 `$SE_ROOT/memory/USER.md`，要求只写跨会话成立的高信号条目、每条一句话、正向表述、无举例、无元信息、剔除身份信息；经验教训追加到 `$SE_ROOT/memory/LESSONS.md` 并遵守文件内格式模板，用户的隐私信息绝不写入任何公开内容。
5. **收尾与报告**：`python3 $SE_ROOT/scripts/evolve_finish.py --candidates N --enabled A --rejected B --merged C --updated D --repaired R --memory E` 一条命令完成 state.json 计数、日志维护与追加、体检与 git 提交；核心脚本有改动时加 `--full`。最后按 `$SE_ROOT/docs/report-template.md` 输出三节报告，末节逐项列出待用户决策。

## 体检分级速查

优秀与健康不做操作；未观测不处置；问题项复核失败归因，能修则修；闲置项（半月未用且低产，或满 30 天）列出后征求用户归档决定；沉睡项（半月未用但累计使用 ≥10 次）仅提示不归档；元技能与用户手动管理的技能只提示或只读观察。启用区技能总量上限约 40 个，实测目录数须与 `stats.skillsEnabled` 一致。归档、淘汰、合并、压缩等写操作逐项征求用户决策后执行，绝不自行删除技能。

归档把技能目录移出 `skills/` 至 `archived/` 并记录原因，恢复时移回并重建软链或文件；源文件不删除，`usage.json` 计数保留。

## 约束与护栏

- 绝不修改用户主导的文件：`AGENTS.md`、人格与角色设定文件、平台配置；平台说明由 install.sh 以标记块方式幂等合并。
- 候选内容属于未经验证的模型输出，必须经审查并由用户确认安全性后才启用。
- 所有变更以明文文件存在并纳入 git 历史，可回滚。
- 不做自动定时与自动唤醒；进化期间不夹带其他操作。
- 采集失败、LLM 后端缺失等情况静默处理，绝不阻塞用户的正常任务。

## 记忆引用

长期记忆位于 `$SE_ROOT/memory/`，按需读取：`@memory/USER.md` 用户画像、`@memory/LESSONS.md` 经验与教训。
