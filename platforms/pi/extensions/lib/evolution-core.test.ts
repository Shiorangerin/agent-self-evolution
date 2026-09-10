/**
 * evolution-core 纯函数库测试（bun test 运行，零外部依赖）
 *
 * 用例来源：进化系统历史踩坑实录（LESSONS.md）+ 迭代中人工发现的缺陷。
 * 每个用例对应一个真实发生过的问题，防止回归。
 */
import { describe, expect, test } from "bun:test";
import {
	buildTraceSummary,
	buildTraceText,
	entryText,
	extractText,
	extractToolPaths,
	isSelfManagementSession,
	judgeOutcome,
	privatePatterns,
	sanitizeTraceText,
	slugify,
	stripOuterFence,
	touchesPrivatePath,
	touchesPrivateText,
} from "./evolution-core.ts";

describe("slugify", () => {
	test("大写转小写、空格转连字符", () => {
		expect(slugify("My Cool Skill")).toBe("my-cool-skill");
	});
	test("非 ASCII 字符被剥离", () => {
		expect(slugify("技能 skill")).toBe("skill");
	});
	test("全非法字符时回退 untitled-skill", () => {
		expect(slugify("技能")).toBe("untitled-skill");
		expect(slugify("")).toBe("untitled-skill");
	});
	test("超长截断到 60 字符", () => {
		expect(slugify("a".repeat(100)).length).toBeLessThanOrEqual(60);
	});
});

describe("extractText", () => {
	test("字符串直通", () => {
		expect(extractText("hello")).toBe("hello");
	});
	test("text 块数组拼接", () => {
		expect(extractText([{ type: "text", text: "a" }, { type: "text", text: "b" }])).toBe("a\nb");
	});
	test("非文本块与非数组输入返回空串", () => {
		expect(extractText([{ type: "toolCall", name: "bash" }])).toBe("");
		expect(extractText(42)).toBe("");
		expect(extractText(null)).toBe("");
	});
});

describe("buildTraceSummary", () => {
	const entries = [
		{ type: "message", message: { role: "user", content: "帮我修一下" } },
		{
			type: "message",
			message: {
				role: "assistant",
				content: [{ type: "toolCall", name: "bash", arguments: { command: "bun test" } }],
			},
		},
		{ type: "message", message: { role: "toolResult", isError: true, content: "command failed" } },
	];
	test("统计工具调用与错误数", () => {
		const { toolCalls, errors } = buildTraceSummary(entries);
		expect(toolCalls).toBe(1);
		expect(errors).toBe(1);
	});
	test("摘要含用户请求/执行操作/错误三段", () => {
		const { summary } = buildTraceSummary(entries);
		expect(summary).toContain("【用户请求】");
		expect(summary).toContain("【执行操作】");
		expect(summary).toContain("【出现的错误】");
	});
	test("斜杠命令不计入用户请求", () => {
		const { summary } = buildTraceSummary([
			{ type: "message", message: { role: "user", content: "/evolve-collect" } },
		]);
		expect(summary).not.toContain("/evolve-collect");
	});
	test("空会话返回空摘要", () => {
		const { summary, toolCalls } = buildTraceSummary([]);
		expect(summary).toBe("");
		expect(toolCalls).toBe(0);
	});
});

describe("isSelfManagementSession", () => {
	const userMsg = (t: string) => [{ type: "message", message: { role: "user", content: t } }];
	test("触发词命中：进化/总结一天/审查候选", () => {
		for (const t of ["今天来进化一下", "总结一天的工作", "帮我审查候选"]) {
			expect(isSelfManagementSession(userMsg(t))).toBe(true);
		}
	});
	test("自管理目录操作命中", () => {
		const win = [
			{
				type: "message",
				message: {
					role: "assistant",
					content: [
						{ type: "toolCall", name: "read", arguments: { path: "~/.pi/agent/evolution/state.json" } },
					],
				},
			},
		];
		expect(isSelfManagementSession(win)).toBe(true);
	});
	test("普通任务不误判", () => {
		expect(isSelfManagementSession(userMsg("帮我把这首歌下载到音乐库"))).toBe(false);
	});
	test("斜杠命令不参与触发词匹配", () => {
		expect(isSelfManagementSession(userMsg("/evolve-collect"))).toBe(false);
	});
});

describe("entryText / buildTraceText", () => {
	test("entryText 提取 toolCall 名与参数", () => {
		const t = entryText({
			type: "message",
			message: {
				role: "assistant",
				content: [{ type: "toolCall", name: "read", arguments: { path: "/tmp/x" } }],
			},
		});
		expect(t).toContain("read");
		expect(t).toContain("/tmp/x");
	});
	test("弱信号文本排除系统注入的技能全文（LESSONS 2026-08-18 假失败根因）", () => {
		const injected = '<skill name="homebrew-cellarbin-update">失败 报错 有问题</skill>';
		const out = buildTraceText([{ type: "message", message: { role: "user", content: injected } }]);
		expect(out).toBe("");
	});
	test("弱信号文本排除助手正文，只留 toolCall 证据", () => {
		const out = buildTraceText([
			{
				type: "message",
				message: {
					role: "assistant",
					content: [
						{ type: "text", text: "brew-cleanup-optimize 这个技能很好用 brew-cleanup-optimize" },
						{ type: "toolCall", name: "bash", arguments: { command: "brew cleanup" } },
					],
				},
			},
		]);
		expect(out).not.toContain("这个技能很好用");
		expect(out).toContain("brew cleanup");
	});
});

describe("judgeOutcome", () => {
	const okRun = { type: "message", message: { role: "toolResult", isError: false, content: "ok" } };
	test("读取后出现错误 → failure 且带报错原文", () => {
		const r = judgeOutcome(
			[
				okRun,
				{ type: "message", message: { role: "toolResult", isError: true, content: "EACCES permission" } },
			],
			0,
		);
		expect(r.outcome).toBe("failure");
		expect(r.reasons[0]).toContain("EACCES");
	});
	test("注入的技能全文不算用户负面反馈（LESSONS 2026-08-18）", () => {
		const r = judgeOutcome(
			[
				okRun,
				{
					type: "message",
					message: {
						role: "user",
						content: '<skill name="x">这里全是 失败 报错 有问题 的字样</skill>',
					},
				},
			],
			0,
		);
		expect(r.outcome).toBe("success");
	});
	test("真实用户负面词 → failure；正面词 → success", () => {
		const neg = judgeOutcome(
			[okRun, { type: "message", message: { role: "user", content: "还是不对，算了" } }],
			0,
		);
		expect(neg.outcome).toBe("failure");
		const pos = judgeOutcome(
			[okRun, { type: "message", message: { role: "user", content: "完美，搞定" } }],
			0,
		);
		expect(pos.outcome).toBe("success");
	});
	test("无错误无反馈但有执行 → success；只读未执行 → unknown", () => {
		expect(judgeOutcome([okRun], 0).outcome).toBe("success");
		expect(judgeOutcome([], 0).outcome).toBe("unknown");
	});
	test("归因窗口从 fromIndex 起：之前的错误不计入", () => {
		const err = { type: "message", message: { role: "toolResult", isError: true, content: "old error" } };
		expect(judgeOutcome([err, okRun], 1).outcome).toBe("success");
	});
});

describe("stripOuterFence", () => {
	test("整篇被围栏包裹时剥掉外层", () => {
		expect(stripOuterFence("```markdown\n---\nname: x\n---\n正文\n```")).toBe("---\nname: x\n---\n正文");
		expect(stripOuterFence("```\n---\nname: x\n---\n```")).toBe("---\nname: x\n---");
	});
	test("正文内部的代码块原样保留（LESSONS 2026-08-26：全局剥围栏会把 ```bash 块删残）", () => {
		const doc = "---\nname: x\n---\n\n```bash\necho hi\n```\n";
		expect(stripOuterFence(doc)).toBe(doc.trim());
		expect(stripOuterFence(doc)).toContain("```bash");
	});
	test("无围栏输入直通", () => {
		expect(stripOuterFence("---\nname: x\n---\n正文")).toBe("---\nname: x\n---\n正文");
	});
});

describe("sanitizeTraceText", () => {
	test("家目录绝对路径统一替换为 ~（轨迹外发前的通用脱敏）", () => {
		expect(sanitizeTraceText("cat /Users/someone/notes.md", "/Users/someone")).toBe("cat ~/notes.md");
		expect(sanitizeTraceText("read /Users/someone/a /Users/someone/b", "/Users/someone")).toBe("read ~/a ~/b");
	});
	test("无命中时原样返回；home 为空时直通", () => {
		expect(sanitizeTraceText("no path here", "/Users/someone")).toBe("no path here");
		expect(sanitizeTraceText("/Users/someone/x", "")).toBe("/Users/someone/x");
	});
});

describe("privatePatterns / touchesPrivateText", () => {
	test("缺省使用内置通用词表（不含任何具体用户信息）", () => {
		const patterns = privatePatterns();
		expect(patterns).toContain("diary");
		expect(patterns).toContain(".env");
		expect(patterns).toContain("id_rsa");
	});
	test("SE_PRIVATE_PATTERNS 环境变量非空时覆盖默认词表", () => {
		expect(privatePatterns("foo, bar")).toEqual(["foo", "bar"]);
		expect(privatePatterns("  ")).toContain("diary"); // 空值回退默认
	});
	test("轨迹命中隐私路径模式 → true（宁可不采不可外发）", () => {
		expect(touchesPrivateText("cat app/.env", privatePatterns())).toBe(true);
		expect(touchesPrivateText("read ~/Documents/diary.md", privatePatterns())).toBe(true);
		expect(touchesPrivateText("mv report.txt ./out/", privatePatterns())).toBe(false);
	});
	test("大小写不敏感", () => {
		expect(touchesPrivateText("cat APP/.ENV", privatePatterns())).toBe(true);
	});
});

describe("buildTraceSummary.hasUser", () => {
	test("有用户消息 → hasUser true；无 → false", () => {
		const withUser = [{ type: "message", message: { role: "user", content: "帮我整理文件" } }];
		const noUser = [{ type: "message", message: { role: "assistant", content: [{ type: "toolCall", name: "bash", arguments: { command: "ls" } }] } }];
		expect(buildTraceSummary(withUser).hasUser).toBe(true);
		expect(buildTraceSummary(noUser).hasUser).toBe(false);
	});
	test("传入 home 时摘要做脱敏", () => {
		const entries = [{ type: "message", message: { role: "assistant", content: [{ type: "toolCall", name: "bash", arguments: { command: "cat /Users/someone/a.txt" } }] } }];
		const { summary } = buildTraceSummary(entries, "/Users/someone");
		expect(summary).toContain("~/a.txt");
		expect(summary).not.toContain("/Users/someone");
	});
});

describe("touchesPrivatePath（甲方案 2026-09-05：只判工具调用路径）", () => {
	const tc = (name: string, args: Record<string, unknown>) => ({
		type: "message",
		message: { role: "assistant", content: [{ type: "toolCall", name, arguments: args }] },
	});
	const pats = () => privatePatterns();

	test("真读日记/真读 .env → 熔断", () => {
		expect(touchesPrivatePath([tc("read", { path: "/Users/someone/Desktop/Diary.md" })], pats())).toBe(true);
		expect(touchesPrivatePath([tc("bash", { command: "cat ~/.env" })], pats())).toBe(true);
		expect(touchesPrivatePath([tc("bash", { command: "ls ~/.ssh/id_ed25519" })], pats())).toBe(true);
		expect(touchesPrivatePath([tc("read", { path: "/app/web/.env.local" })], pats())).toBe(true);
		expect(touchesPrivatePath([tc("read", { path: "/tmp/a/credentials.json" })], pats())).toBe(true);
	});
	test("process.env 代码不再误杀（2026-09-04 …01a06df4… 实证 .env×39 全误杀）", () => {
		const code = `cat > /tmp/dbg.ts <<'EOF'\nprocess.env.PI_CODING_AGENT_DIR = "/tmp/cc-dbg";`;
		expect(touchesPrivatePath([tc("bash", { command: code })], pats())).toBe(false);
	});
	test("rg 扫描正则不再误杀（2026-09-02 …01a061c3… 实证）", () => {
		expect(
			touchesPrivatePath([tc("bash", { pattern: "(\\.env|\\.pem|password|credential)" })], pats()),
		).toBe(false);
	});
	test("用户/助手正文提到文件名不再熔断（提到≠触及）", () => {
		const entries = [
			{ type: "message", message: { role: "user", content: "桌面上有 Diary.md 和 TODO.md" } },
			tc("bash", { command: "eza /Users/someone/Desktop | head" }),
		];
		expect(touchesPrivatePath(entries, pats())).toBe(false);
	});
	test("普通路径不熔断；大小写不敏感", () => {
		expect(touchesPrivatePath([tc("read", { path: "/tmp/ase-audit/core/collect.py" })], pats())).toBe(false);
		expect(touchesPrivatePath([tc("bash", { command: "cat /APP/.ENV" })], pats())).toBe(true);
	});
	test("工具结果内容不参与判定（已知残留风险：env 输出类泄露需上层兜底）", () => {
		const entries = [
			tc("bash", { command: "eza /tmp | head" }),
			{ type: "message", message: { role: "toolResult", content: "password=hunter2" } },
		];
		expect(touchesPrivatePath(entries, pats())).toBe(false);
	});
	test("extractToolPaths：path 键整体收录；自由文本只抠路径 token", () => {
		const entries = [tc("read", { path: "Diary.md" }), tc("bash", { command: "cd /tmp && rg -i password src" })];
		const paths = extractToolPaths(entries);
		expect(paths).toContain("Diary.md");
		expect(paths).toContain("/tmp");
		expect(paths.some((p) => p.includes("password"))).toBe(false);
	});
});
