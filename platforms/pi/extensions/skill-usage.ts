/**
 * agent-self-evolution —— 技能使用统计扩展（含健康度反馈回路）
 *
 * 目的：给启用技能补上「使用反馈回路」。每次 agent 运行结束（agent_settled）时，
 * 用纯规则（零 LLM 成本、零 token）扫描会话轨迹，记录哪些技能被「疑似使用」，
 * 并对强信号技能做「结果归因」（成功/失败/未知），数据写入 evolution/usage.json，
 * 供进化流程报告「长期未使用技能」与「问题技能」给用户决定处置。
 *
 * 信号定义（启发式，仅供参考，最终决策权在用户）：
 * - 强信号：轨迹中读取/触碰了 ~/.pi/agent/skills/<name>/SKILL.md 或 evolution/skills/<name> 路径
 * - 弱信号：技能 slug（如 brew-cleanup-optimize）出现在轨迹文本中（仅用户消息 + 工具调用名/参数；
 *   不含助手正文——否则用户让 AI「报告全部上下文」时，助手回显的技能清单会把全员刷成已使用）
 * - 回显熔断：零强信号却弱命中 ≥20 个技能 → 判定为上下文回显/盘点讨论，整体跳过不记录
 *
 * 结果归因（仅对强信号技能，弱信号不归因——可能只是闲聊提及）：
 * - 只统计「技能文件第一次被读取之后」的错误与用户反馈，避免误伤
 * - 失败信号：该位置之后出现 toolResult.isError；或该位置之后用户最后一条消息含负面语义
 * - 成功信号：该位置之后无任何错误、无负面反馈，且确实发生了工具执行（有非错误 toolResult）
 *   —— 工具按步骤跑完且没报错，即视为一次成功使用；用户最后消息含正面语义也计入
 * - 其余情况：unknown（只读取了技能文件、无实际执行，不强行判定）
 * - 判定是启发式，可能误判；进化时需回读原始轨迹复核
 *
 * 盘点/审查熔断：单会话强信号 ≥5 个技能（进化审查/体检的典型特征）时整体跳过，
 * 不计数、不刷新 lastUsedAt、不归因——批量读取是元工作，不是任务使用。
 *
 * 同一会话去重：按会话文件短名记录，同一会话多次触发只计数一次。
 * 所有失败静默处理，绝不打搅用户。
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { readFileSync, writeFileSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { buildTraceText, entryText, judgeOutcome } from "./lib/evolution-core.ts";
import { homedir } from "node:os";

const EVO_DIR = join(homedir(), ".pi", "agent", "evolution");
const USAGE_FILE = join(EVO_DIR, "usage.json");
const SKILLS_DIR = join(homedir(), ".pi", "agent", "skills");

/** 读取已启用技能名（slug）列表 */
function listSkillNames(): string[] {
	const names: string[] = [];
	try {
		for (const entry of readdirSync(SKILLS_DIR, { withFileTypes: true })) {
			if (entry.name.startsWith(".")) continue;
			if (!entry.isDirectory() && !entry.isSymbolicLink()) continue;
			if (!existsSync(join(SKILLS_DIR, entry.name, "SKILL.md"))) continue;
			names.push(entry.name);
		}
	} catch {
		/* 静默 */
	}
	return names.sort();
}

function readUsage(): any {
	try {
		return JSON.parse(readFileSync(USAGE_FILE, "utf8"));
	} catch {
		return { updatedAt: null, skills: {} };
	}
}

function nowIso(): string {
	return new Date().toISOString();
}

/** 核心：扫描当前会话轨迹，更新技能使用统计与结果归因 */
function track(pi: ExtensionAPI, ctx: any): string {
	try {
		const sessionFile = ctx.sessionManager.getSessionFile();
		if (!sessionFile) return "无会话文件";
		const shortName = sessionFile.split("/").pop() ?? sessionFile;

		const entries = (ctx.sessionManager.getBranch() as any[]) ?? [];
		const text = buildTraceText(entries);
		if (!text.trim()) return "会话无可分析内容";

		const skillNames = listSkillNames();
		if (skillNames.length === 0) return "无已启用技能";

		const usage = readUsage();
		const skills = usage.skills ?? {};
		// 补齐旧条目缺失的 outcomes/failReasons（旧版扩展写入的弱信号条目没有这些字段），
		// 防止后续读取时 KeyError（进化体检遍历 usage.json 直接访问 outcomes）。
		for (const key of Object.keys(skills)) {
			const s = skills[key];
			if (!s || typeof s !== "object") continue;
			if (!s.outcomes || typeof s.outcomes !== "object") {
				s.outcomes = { success: 0, failure: 0, unknown: 0 };
			}
			if (!Array.isArray(s.failReasons)) {
				s.failReasons = [];
			}
		}
		let hit = 0;
		// 预计算每条 entry 的文本（entryText 内含 JSON.stringify，双层循环内反复调用代价高）
		const entryTexts = entries.map(entryText);
		// 单遍扫描：为每个技能定位强信号首次出现位置（强信号 = 真读取了技能文件）。
		// 进化审查/盘点类会话会一次性批量读取大量 SKILL.md，之后会话内任何无关错误
		// （如 cat -A 报错、体检脚本 KeyError）都不该被归因到单个技能，故跳过结果归因。
		const strongIndexOf = new Map<string, number>();
		for (const slug of skillNames) {
			for (let i = 0; i < entryTexts.length; i++) {
				const t = entryTexts[i];
				if (t.includes(`skills/${slug}/SKILL.md`) || t.includes(`evolution/skills/${slug}`)) {
					strongIndexOf.set(slug, i);
					break;
				}
			}
		}
		const strongHits = strongIndexOf.size;
		// 盘点/进化类会话只是批量读取技能做体检，不代表任务使用：
		// 计数、lastUsedAt、归因全部跳过，防止 count 膨胀污染体检数据
		// （LESSONS 2026-08-21「盘点会话污染 lastUsedAt」的延伸修复：仅保 lastUsedAt 不够，
		//   count 与弱信号命中同样会被盘点会话刷高）
		if (strongHits >= 5) {
			return `盘点/审查类会话（强信号 ${strongHits} 个技能被批量读取），跳过记录`;
		}

		const matched: Array<{ slug: string; strong: boolean; strongIndex: number }> = [];
		for (const slug of skillNames) {
			// 强信号：复用单遍扫描结果（技能文件路径第一次出现的 entry 位置，用于结果归因）
			const strongIndex = strongIndexOf.get(slug) ?? -1;
			const strong = strongIndex >= 0;
			// 弱信号：slug 出现在轨迹文本中（用户消息 + 工具参数，不含助手正文）
			const weak = !strong && text.includes(slug);

			if (strong || weak) matched.push({ slug, strong, strongIndex });
		}

		// 回显熔断：零强信号却弱命中大量技能（≥20），几乎必然是助手原文回显了
		// 系统提示词/技能清单（或纯盘点讨论），不是真实使用，整体跳过不记录。
		if (strongHits === 0 && matched.length >= 20) {
			return `疑似上下文回显（弱信号命中 ${matched.length} 个技能、无强信号），跳过记录`;
		}

		for (const { slug, strong, strongIndex } of matched) {
			// 会话去重：本会话已记录过则跳过
			const prev = skills[slug];
			if (prev && prev.lastSession === shortName) continue;

			// 盘点/进化类会话已在上方提前返回，走到这里的都是真实任务会话
			// 不刷新 lastUsedAt，否则每次进化都会把所有技能的 lastUsedAt 刷成当天，闲置检测失效。
			const entry: any = {
				count: (prev?.count ?? 0) + 1,
				lastUsedAt: nowIso(),
				lastSession: shortName,
				signal: strong ? "strong" : "weak",
				outcomes: prev?.outcomes ?? { success: 0, failure: 0, unknown: 0 },
				failReasons: prev?.failReasons ?? [],
			};
			// 结果归因：仅强信号技能（真读取了技能文件）
			if (strong) {
				const { outcome, reasons } = judgeOutcome(entries, strongIndex);
				entry.outcomes[outcome] = (entry.outcomes[outcome] ?? 0) + 1;
				if (reasons.length) {
					entry.failReasons = [...entry.failReasons, ...reasons].slice(-3);
				}
			}
			skills[slug] = entry;
			hit++;
		}

		if (hit === 0) return "无技能使用信号";
		usage.updatedAt = nowIso();
		usage.skills = skills;
		writeFileSync(USAGE_FILE, JSON.stringify(usage, null, 2), "utf8");
		return `已记录 ${hit} 个技能使用信号`;
	} catch {
		return "采集异常";
	}
}

export default function (pi: ExtensionAPI) {
	pi.on("agent_settled", async (_event, ctx) => {
		try {
			await track(pi, ctx);
		} catch {
			/* 任何异常都不打扰用户 */
		}
	});
}
