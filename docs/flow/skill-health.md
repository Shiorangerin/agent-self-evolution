# 技能体检与处置细则

适用：进化流程第三步。需要执行处置动作前阅读本文件。

数据来源：`$SE_ROOT/scripts/skill_scorecard.py` 的分级输出，以及 `$SE_ROOT/usage.json` 的 `outcomes`、`failReasons`、`lastUsedAt`。`usage.json` 由平台 hook 调用 `core/track_usage.py` 维护，纯规则统计，零 LLM 成本。

## 一、闲置技能

判定：`lastUsedAt` 距今 60 天以上未使用。从未被记录过使用、且启用已超 60 天的也算。

处置：列出技能名、最后使用时间、使用次数，征求用户归档决定。用户确认归档则执行归档操作，用户决定保留则记录进报告不动作。

## 二、问题技能

判定：失败次数不少于 2 次，或失败率超过 50% 且失败至少 1 次。失败率为 `failure / (success + failure)`。

复核顺序：

1. 先看 `usage.json` 的 `failReasons`。必要时回查该技能 `lastSession` 对应的轨迹确认原因，用 `python3 $SE_ROOT/scripts/evolve_trail.py <会话片段> <报错关键词> --max 30 --chars 8000` 定点抽取。结果归因是启发式判断，可能误判，以原始轨迹为准，不要整文件读取轨迹。
2. 判定为技能未覆盖的场景，给该技能补「常见问题」，`state.json` 的 `stats.skillsRepaired` 加一。
3. 判定为步骤错误或内容过时，重写对应步骤，同样 `stats.skillsRepaired` 加一。
4. 屡败零胜，即失败不少于 3 次且成功为 0，建议淘汰并征求用户决定。
5. 拿不准的向用户汇报求决策，绝不自行删除技能。

## 三、优质技能

判定：成功不少于 3 次且失败率为 0。报告中确认表现良好，不做任何操作。

## 四、总量硬约束

实测启用区目录数：

```bash
find $SE_ROOT/skills -mindepth 1 -maxdepth 1 -type d | wc -l
```

与 `state.json` 的 `stats.skillsEnabled` 比对，不一致以实测为准直接修正 stats。技能可能在流程之外被删除，stats 不是权威。

启用区技能数上限约 40 个。超过时列出合并、归档、淘汰候选清单，附每项的使用次数与最后使用时间依据，逐项征求用户决策后执行，绝不自行删除技能。控制总量的目的是避免技能描述膨胀、污染每次会话的上下文。

## 五、豁免范围

- **元技能**：`self-evolve` 与 `self-evolve-maintenance` 是进化流程定义本身，豁免闲置归档，不参与压缩，超长仅在报告中提示。
- **用户手动安装、非本系统管理的技能**：只读观察使用数据，不压缩、不归档、不淘汰、不修改内容。
- **第三方打包技能**：带 `reference/` 等资源的安装型技能不强制压缩，仅标记超长。

## 六、超长技能压缩流程

仅适用于本系统管理区的普通技能。元技能与豁免范围不进入本流程。

触发条件：`SKILL.md` 超过 8000 字符（`evolve_brief.sh` 的超长清单会直接列出）。

1. 用低成本模型起草压缩稿。prompt 附原 `SKILL.md` 全文与硬约束：保留全部注意点、命令、参数与实测结论，只删除冗余叙述与重复示例，结果不超过 8000 字符。不在主会话人肉重写。
2. 只审 diff 确认零信息损失后落盘。拿不准的段落保留原状。
3. 单技能超过 8000 字符，或内容涉及用户决策与隐私边界的，先逐项征求用户意见再动。

## 七、归档与恢复

归档让技能从上下文消失，源文件与历史保留，区别于删除。

```bash
mkdir -p $SE_ROOT/archived
mv $SE_ROOT/skills/<name> $SE_ROOT/archived/<name>
# 同时移除技能加载目录中的软链或文件
```

恢复：

```bash
mv $SE_ROOT/archived/<name> $SE_ROOT/skills/<name>
ln -sfn $SE_ROOT/skills/<name> ~/.pi/agent/skills/<name>   # Pi 平台的技能加载目录
```

归档或恢复后，`usage.json` 对应条目保留，恢复时计数延续；在 `logs/experience-log.md` 记录归档或恢复行；git 提交保证可回滚。
