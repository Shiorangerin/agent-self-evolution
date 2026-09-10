/**
 * agent-self-evolution —— 共享纯函数库
 *
 * 由 self-evolve.ts（采集器）与 skill-usage.ts（使用统计）共用。
 * 刻意保持零依赖（只有纯计算，不碰 fs / 不调 LLM），
 * 可被测试框架直接导入验证（bun test ~/.pi/agent/extensions/lib/）。
 *
 * 注意：本文件位于 extensions/lib/ 下且不叫 index.ts，
 * pi 的扩展自动发现（extensions/*.ts 与 extensions\/*\/index.ts）不会把它当作扩展加载。
 */

/** 轨迹摘要上限 */
export const MAX_TRACE_CHARS = 2500;

/** 负面语义词表（启发式：用于结果归因的失败信号，进化时人工复核） */
export const NEGATIVE_WORDS = [
	"失败", "不行", "没用", "还是错", "不对", "坏了", "算了", "放弃", "不弄",
	"崩溃", "打不开", "报错", "出错", "卡住", "没成功", "搞不定", "解决不了",
	"有问题", "假的", "骗人", "没有用", "白费", "退回", "删了吧",
];

/** 正面语义词表（启发式：用于结果归因的成功信号） */
export const POSITIVE_WORDS = [
	"好了", "搞定", "成功", "可以了", "能用了", "完美", "感谢", "谢谢",
	"赞", "没问题", "行了", "完成", "好用", "厉害", "棒", "nice", "great",
];

export function extractText(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	const parts: string[] = [];
	for (const block of content) {
		if (block && typeof block === "object" && (block as { type?: string }).type === "text") {
			const text = (block as { text?: unknown }).text;
			if (typeof text === "string") parts.push(text);
		}
	}
	return parts.join("\n");
}

export function slugify(name: string): string {
	return (
		name
			.toLowerCase()
			.replace(/[^a-z0-9-]+/g, "-")
			.replace(/^-+|-+$/g, "")
			.replace(/-{2,}/g, "-")
			.slice(0, 60) || "untitled-skill"
	);
}

/**
 * 只剥整篇被单个代码围栏包裹的外层，正文内部的 ``` 代码块原样保留。
 * 不能用全局 replace：那会把候选正文里的 ```bash 块删残（LESSONS 2026-08-26）。
 */
export function stripOuterFence(raw: string): string {
	const t = raw.trim();
	const m = t.match(/^```[a-zA-Z]*\s*\n([\s\S]*?)\n?```\s*$/);
	return m ? m[1].trim() : t;
}

/**
 * 通用脱敏：把轨迹文本中的家目录绝对路径统一替换为 ~。
 * 轨迹摘要会外发给低成本采集模型，家目录结构属于用户环境信息，不应随之外泄。
 * 纯函数：home 由调用方传入（保持本库不碰 fs / env 的约定）。
 */
export function sanitizeTraceText(text: string, home: string): string {
	if (!text || !home || home === "~") return text;
	return text.split(home).join("~");
}

/**
 * 默认隐私路径模式（通用词表，与具体用户无关）：文件名命中即视为私密内容。
 * 覆盖日记 / 环境变量 / SSH 密钥 / 证书 / 凭证 / 密码 / 钱包等常见私密文件。
 * 可通过环境变量 SE_PRIVATE_PATTERNS（逗号分隔）覆盖或扩充。
 */
export const DEFAULT_PRIVATE_PATTERNS: ReadonlyArray<string> = [
	"diary",
	".env",
	"id_rsa",
	"id_ed25519",
	".pem",
	"credential",
	"password",
	"passwd",
	"wallet",
	"private_key",
	"privatekey",
	"secrets.",
];

/** 解析隐私模式：env 值（逗号分隔）非空则覆盖默认词表，否则用内置通用词表 */
export function privatePatterns(envValue?: string): string[] {
	const fromEnv = (envValue ?? "")
		.split(",")
		.map((s) => s.trim().toLowerCase())
		.filter(Boolean);
	return fromEnv.length > 0 ? fromEnv : [...DEFAULT_PRIVATE_PATTERNS];
}

/**
 * 隐私熔断检测（旧版全文子串，已废弃保留兼容）：轨迹文本命中任一隐私路径模式即熔断。
 * 缺陷：".env" 会命中代码里的 process.env，rg 正则/帮助文本也会误杀（2026-09-05 实证 4 场 3 误杀）。
 * 新采集统一走 touchesPrivatePath（只判工具调用的文件路径）。
 */
export function touchesPrivateText(text: string, patterns: string[]): boolean {
	if (!text) return false;
	const lower = text.toLowerCase();
	return patterns.some((p) => p && lower.includes(p.toLowerCase()));
}

/**
 * 路径型工具参数键：这类键的值整体视为文件路径（即使不含 "/"，如相对文件名 "Diary.md"）。
 */
const PATH_ARG_KEYS: ReadonlySet<string> = new Set([
	"path", "file", "filepath", "filename", "dir", "directory", "cwd",
	"target", "source", "src", "dest", "destination", "folder",
]);

/** 路径形 token：必须含 "/" 或以 "~" 开头（如 ~/.env、/tmp/x、.agents/skills） */
const PATH_TOKEN_RE = /~?\/[\w.~][\w.~+\-@]*(\/[\w.~][\w.~+\-@]*)*/g;

/** 从工具调用参数中提取候选路径（用户正文/助手正文/工具结果一律不进，只看行动证据） */
export function extractToolPaths(entries: any[], limit = 2000): string[] {
	const out: string[] = [];
	const push = (s: string) => {
		const t = s.trim();
		if (t && t.length <= 500 && out.length < limit) out.push(t);
	};
	for (const e of entries ?? []) {
		const content = e?.message?.content;
		if (!Array.isArray(content)) continue;
		for (const block of content) {
			if (!block || typeof block !== "object" || (block as any).type !== "toolCall") continue;
			const args = (block as any).arguments;
			if (!args || typeof args !== "object") continue;
			for (const [k, v] of Object.entries(args)) {
				if (typeof v !== "string") continue;
				if (PATH_ARG_KEYS.has(String(k).toLowerCase())) {
					push(v);
				} else {
					// bash -c 等自由文本参数：只抠路径形 token，rg 正则/代码片段自动排除
					PATH_TOKEN_RE.lastIndex = 0;
					let m: RegExpExecArray | null;
					while ((m = PATH_TOKEN_RE.exec(v)) !== null) push(m[0]);
				}
			}
		}
		if (out.length >= limit) break;
	}
	return out;
}

/**
 * 隐私熔断检测（甲方案，2026-09-05）：任一工具调用的文件路径命中隐私模式 → 整场跳过采集。
 * 点号模式（.env/.pem）要求路径片段全等（兼容 .env.local 类变体）；单词模式（diary/credential）要求片段包含。
 * 提到文件名不算触及，只有真读真写才算：process.env、rg 扫描正则、CLI 帮助文本不再误杀。
 */
export function touchesPrivatePath(entries: any[], patterns: string[]): boolean {
	const paths = extractToolPaths(entries);
	if (paths.length === 0) return false;
	const pats = (patterns ?? []).map((p) => String(p).toLowerCase()).filter(Boolean);
	if (pats.length === 0) return false;
	for (const raw of paths) {
		const segs = String(raw).toLowerCase().split("/").filter(Boolean);
		if (segs.length === 0) continue;
		for (const p of pats) {
			if (p.startsWith(".")) {
				if (segs.some((s) => s === p || s.startsWith(p + "."))) return true;
			} else {
				if (segs.some((s) => s.includes(p))) return true;
			}
		}
	}
	return false;
}

/** 收集本次会话轨迹摘要（传入 home 时对摘要做家目录通用脱敏；hasUser 用于画像采集门槛） */
export function buildTraceSummary(
	entries: any[],
	home = "",
): { toolCalls: number; errors: number; summary: string; hasUser: boolean } {
	let toolCalls = 0;
	let errors = 0;
	const userParts: string[] = [];
	const bashParts: string[] = [];
	const errorParts: string[] = [];

	for (const e of entries) {
		if (e.type !== "message" || !e.message) continue;
		const m = e.message;
		const role = m.role;

		if (role === "user") {
			const t = extractText(m.content).trim();
			if (t && !t.startsWith("/")) userParts.push(t.slice(0, 300));
		} else if (role === "assistant") {
			const content = m.content;
			if (Array.isArray(content)) {
				for (const block of content) {
					if (block && typeof block === "object" && (block as any).type === "toolCall") {
						toolCalls++;
						const args = (block as any).arguments ?? {};
						const name = (block as any).name ?? "";
						if (name === "bash" || name === "bash_command" || name === "command") {
							const cmd = typeof args === "object" ? String(args.command ?? args.cmd ?? "") : "";
							if (cmd) bashParts.push(cmd.slice(0, 200));
						} else if (name === "edit" || name === "write" || name === "read") {
							const p = typeof args === "object" ? String(args.path ?? "") : "";
							if (p) bashParts.push(`${name} ${p}`);
						}
					}
				}
			}
		} else if (role === "toolResult") {
			if (m.isError) {
				errors++;
				errorParts.push(extractText(m.content).slice(0, 400));
			}
		} else if (role === "bashExecution") {
			if (m.command && !m.cancelled) bashParts.push(m.command.slice(0, 200));
		}
	}

	const lines: string[] = [];
	if (userParts.length) lines.push("【用户请求】\n" + userParts.slice(-5).join("\n"));
	if (bashParts.length) lines.push("【执行操作】\n" + bashParts.slice(-25).join("\n"));
	if (errorParts.length) lines.push("【出现的错误】\n" + errorParts.slice(-3).join("\n---\n"));
	const summary = sanitizeTraceText(lines.join("\n\n"), home).slice(0, MAX_TRACE_CHARS);

	return { toolCalls, errors, summary, hasUser: userParts.length > 0 };
}

/**
 * 判断本次会话是否为「自我管理会话」——即正在执行 self-evolve / self-evolve-maintenance 流程本身。
 * 这类会话 100% 注定与已有元技能重复（历史拒绝均为白烧 LLM），应在调用 LLM 前直接短路跳过，避免自耗。
 * 识别信号：① 用户请求含进化触发词；② 执行操作（bash/read/edit 路径）涉及 evolution 自管理目录。
 */
export function isSelfManagementSession(window: any[]): boolean {
	const triggerWords = [
		"进化", "总结一天", "总结今天", "总结一下", "自我进化", "技能候选", "沉淀技能",
		"进化一下", "自我沉淀", "审查候选", "技能体检", "进化系统",
	];
	const managePathMarks = [
		"evolution/candidates", "evolution/skills", "evolution/archived",
		"evolution/state.json", "evolution/usage.json", "evolution/logs/experience-log",
		"evolution/logs/session-summaries", "/extensions/self-evolve", "evolution/skills/self-evolve",
	];

	for (const e of window) {
		if (e?.type !== "message" || !e.message) continue;
		const m = e.message;
		const role = m.role;

		if (role === "user") {
			const t = extractText(m.content).trim();
			if (!t || t.startsWith("/")) continue;
			// 宽松匹配：避免脆弱的整词边界，用子串包含判断
			if (triggerWords.some((w) => t.includes(w))) return true;
		} else if (role === "assistant") {
			const content = m.content;
			if (!Array.isArray(content)) continue;
			for (const block of content) {
				if (!block || typeof block !== "object" || (block as any).type !== "toolCall") continue;
				const args = (block as any).arguments ?? {};
				const toolName = (block as any).name ?? "";
				// bash 命令或 read/edit/write 路径里出现自管理目录标记 → 命中
				let probe = "";
				if (toolName === "bash" || toolName === "bash_command" || toolName === "command") {
					probe = String(args.command ?? args.cmd ?? "");
				} else if (toolName === "read" || toolName === "edit" || toolName === "write") {
					probe = String(args.path ?? "");
				}
				// 归一化路径：历史日志可能用相对/绝对路径，都归一化到是否包含 evolution 自管理特征
				if (managePathMarks.some((p) => probe.includes(p))) return true;
			}
		} else if (role === "bashExecution") {
			if (m.command && !m.cancelled && managePathMarks.some((p) => m.command.includes(p))) return true;
		}
	}
	return false;
}

/** 提取单条 entry 的全部文本（用于定位技能文件被读取的位置） */
export function entryText(e: any): string {
	if (!e || e.type !== "message" || !e.message) return "";
	const m = e.message;
	if (typeof m.content === "string") return m.content;
	if (!Array.isArray(m.content)) return "";
	const parts: string[] = [];
	for (const block of m.content) {
		if (!block || typeof block !== "object") continue;
		if ((block as any).type === "text") {
			const t = (block as { text?: unknown }).text;
			if (typeof t === "string") parts.push(t);
		} else if ((block as any).type === "toolCall") {
			const name = (block as any).name ?? "";
			const args = (block as any).arguments ?? {};
			parts.push(String(name));
			try {
				parts.push(typeof args === "object" ? JSON.stringify(args) : String(args));
			} catch {
				/* ignore */
			}
		}
	}
	return parts.join("\n");
}

/**
 * 收集本次会话轨迹中用于「弱信号匹配」的文本。
 * 只含用户消息 + 工具调用名/参数，刻意排除助手正文：
 * 助手复述/罗列技能名不代表使用（典型污染场景：用户要求「报告全部上下文」，
 * 助手原文输出含全部技能清单的系统提示词，曾把 50 个技能 lastUsedAt 同秒刷爆）。
 */
export function buildTraceText(entries: any[]): string {
	const parts: string[] = [];
	for (const e of entries) {
		if (e.type !== "message" || !e.message) continue;
		const m = e.message;
		if (m.role === "user") {
			const t = extractText(m.content).trim();
			// 同 judgeOutcome：过滤系统注入的技能全文，避免污染轨迹文本与信号检测
			if (t && !t.startsWith("/") && !t.includes("<skill name=")) parts.push(t);
		} else if (m.role === "assistant") {
			// 仅保留 toolCall 名/参数作为行动证据；助手 prose 不参与弱信号匹配
			const content = m.content;
			if (Array.isArray(content)) {
				for (const block of content) {
					if (!block || typeof block !== "object") continue;
					if ((block as any).type === "toolCall") {
						const name = (block as any).name ?? "";
						const args = (block as any).arguments ?? {};
						parts.push(name);
						try {
							parts.push(typeof args === "object" ? JSON.stringify(args) : String(args));
						} catch {
							/* ignore */
						}
					}
				}
			}
		}
	}
	return parts.join("\n");
}

/**
 * 结果归因：只看 [fromIndex..] 的轨迹（技能文件被读取之后）。
 * @returns outcome: success / failure / unknown；failure 时附 failReasons（报错原文片段，最多 3 条）
 */
export function judgeOutcome(
	entries: any[],
	fromIndex: number,
): { outcome: "success" | "failure" | "unknown"; reasons: string[] } {
	let hasError = false;
	const reasons: string[] = [];
	let lastUserText = "";
	let hasRun = false; // 是否有非错误 toolResult（证明技能被实际执行过）

	for (let i = fromIndex; i < entries.length; i++) {
		const e = entries[i];
		if (!e || e.type !== "message" || !e.message) continue;
		const m = e.message;
		if (m.role === "toolResult") {
			if (m.isError) {
				hasError = true;
				const t = extractText(m.content).slice(0, 200).trim();
				if (t && reasons.length < 3) reasons.push(t);
			} else {
				hasRun = true;
			}
		} else if (m.role === "user") {
			const t = extractText(m.content).trim();
			// 跳过系统注入的技能全文（<skill name="..."> 是技能注入格式，不是用户真实输入），
			// 否则技能正文中的负面词（失败/报错/有问题等）会被误判为「用户反馈失败」。
			if (t && !t.startsWith("/") && !t.includes("<skill name=")) lastUserText = t;
		}
	}

	if (hasError) return { outcome: "failure", reasons };
	if (lastUserText) {
		if (NEGATIVE_WORDS.some((w) => lastUserText.includes(w))) {
			return { outcome: "failure", reasons: [`用户反馈: ${lastUserText.slice(0, 100)}`] };
		}
		if (POSITIVE_WORDS.some((w) => lastUserText.includes(w))) {
			return { outcome: "success", reasons: [] };
		}
	}
	// 无错误、无负面反馈且技能确实被执行（产生过非错误工具结果）→ 视为一次成功使用
	if (hasRun) return { outcome: "success", reasons: [] };
	// 只读取了技能文件、无实际执行活动 → 无法判定
	return { outcome: "unknown", reasons: [] };
}
