import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import path from "node:path";
import readline from "node:readline";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const bridgePath = path.resolve(testDir, "..", "bridge.mjs");
const bridgeModule = await import(pathToFileURL(bridgePath).href);

const {
	buildBridgeErrorPayload,
	parseConversationMessages,
	parseModelSelector,
	resolveModelSelection,
	runSession,
	serializeToolResultPayload,
} = bridgeModule;

function startBridge() {
	const child = spawn(process.execPath, [bridgePath], {
		stdio: ["pipe", "pipe", "pipe"],
	});
	const rl = readline.createInterface({
		input: child.stdout,
		crlfDelay: Infinity,
	});
	const stderr = [];
	const lines = [];
	const waiters = [];
	let exitError = null;
	child.stderr.on("data", (chunk) => {
		stderr.push(chunk.toString("utf8"));
	});
	rl.on("line", (line) => {
		const waiter = waiters.shift();
		if (waiter) {
			waiter.resolve(line);
			return;
		}
		lines.push(line);
	});
	child.once("error", (error) => {
		exitError = error;
		const waiter = waiters.shift();
		if (waiter) {
			waiter.reject(error);
		}
	});
	child.once("exit", (code, signal) => {
		exitError = new Error(
			`bridge exited before emitting a line (code=${code}, signal=${signal})`,
		);
		const waiter = waiters.shift();
		if (waiter) {
			waiter.reject(exitError);
		}
	});

	const readEvent = async () => {
		if (lines.length > 0) {
			return JSON.parse(lines.shift());
		}
		if (exitError) {
			throw exitError;
		}
		const line = await new Promise((resolve, reject) => {
			waiters.push({ resolve, reject });
		});
		return JSON.parse(line);
	};

	const send = (payload) => {
		child.stdin.write(`${JSON.stringify(payload)}\n`);
	};

	const stop = async () => {
		rl.close();
		if (child.stdin && !child.stdin.destroyed) {
			child.stdin.end();
		}
		if (child.exitCode !== null || child.signalCode !== null) {
			return;
		}
		await new Promise((resolve) => {
			const timer = setTimeout(() => {
				child.kill("SIGKILL");
			}, 500);
			child.once("exit", () => {
				clearTimeout(timer);
				resolve();
			});
			child.kill("SIGTERM");
		});
	};

	return { child, readEvent, send, stop, stderr };
}

test("bridge emits hello and responds to ping", async () => {
	const bridge = startBridge();
	try {
		const hello = await bridge.readEvent();
		assert.equal(hello.type, "hello");
		assert.equal(hello.bridge, "cloop-pi-bridge");

		bridge.send({ type: "ping", protocol: 1, request_id: "ping-1" });
		const pong = await bridge.readEvent();
		assert.equal(pong.type, "pong");
		assert.equal(pong.request_id, "ping-1");
		assert.equal(pong.protocol, 1);
	} finally {
		await bridge.stop();
	}
});

test("bridge rejects unsupported selector resolution requests", async () => {
	const bridge = startBridge();
	try {
		await bridge.readEvent();
		bridge.send({
			type: "resolve_model",
			protocol: 1,
			request_id: "resolve-1",
			selectors: ["definitely-missing-provider/definitely-missing-model"],
			selector_mode: "fallback",
		});
		const response = await bridge.readEvent();
		assert.equal(response.type, "error");
		assert.equal(response.request_id, "resolve-1");
		assert.match(response.message, /unsupported pi model selector/i);
	} finally {
		await bridge.stop();
	}
});

test("bridge reports invalid start requests as protocol errors", async () => {
	const bridge = startBridge();
	try {
		await bridge.readEvent();

		bridge.send({
			type: "start",
			protocol: 1,
			request_id: "bad-start",
			model: "",
			messages: [{ role: "user", content: "hi" }],
			thinking_level: "none",
			timeout_ms: 1000,
			max_tool_rounds: 1,
			tools: [],
		});
		const error = await bridge.readEvent();
		assert.equal(error.type, "error");
		assert.equal(error.request_id, "bad-start");
		assert.match(error.message, /model selector/i);
	} finally {
		await bridge.stop();
	}
});

test("runSession initializes Agent state through constructor options", async () => {
	const model = {
		provider: "test-provider",
		id: "test-model",
		api: "test-api",
		name: "Test model",
		baseUrl: "",
		reasoning: false,
		input: [],
		cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
		contextWindow: 1000,
		maxTokens: 1000,
	};
	const registry = {
		find(provider, id) {
			return provider === model.provider && id === model.id ? model : null;
		},
		getAll() {
			return [model];
		},
		async getAvailable() {
			return [model];
		},
	};
	const observed = {};
	class ConstructorOnlyAgent {
		constructor(options) {
			observed.options = options;
			this.state = {
				...options.initialState,
				messages: [...options.initialState.messages],
			};
		}

		subscribe(listener) {
			observed.listener = listener;
			return () => {
				observed.unsubscribed = true;
			};
		}

		abort() {
			observed.aborted = true;
		}

		async continue() {
			this.state.messages.push({
				role: "assistant",
				content: [{ type: "text", text: "hello from fake agent" }],
				provider: this.state.model.provider,
				api: this.state.model.api,
				model: this.state.model.id,
				usage: {
					input: 1,
					output: 2,
					cacheRead: 0,
					cacheWrite: 0,
					totalTokens: 3,
					cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
				},
				stopReason: "stop",
				timestamp: Date.now(),
			});
		}
	}
	const events = [];
	const session = {
		requestId: "good-start",
		request: {
			model: "test-provider/test-model",
			messages: [
				{ role: "system", content: "system guidance" },
				{ role: "user", content: "hello" },
			],
			thinking_level: "none",
			timeout_ms: 1000,
			max_tool_rounds: 1,
			tools: [],
		},
		pendingToolResults: new Map(),
	};

	await runSession(session, {
		AgentClass: ConstructorOnlyAgent,
		emitEvent: (event) => events.push(event),
		log: () => {},
		registry,
	});

	assert.equal(observed.options.initialState.model, model);
	assert.equal(observed.options.initialState.systemPrompt, "system guidance");
	assert.equal(observed.options.initialState.thinkingLevel, "off");
	assert.equal(observed.options.initialState.messages.length, 1);
	assert.equal(observed.options.initialState.messages[0].role, "user");
	assert.deepEqual(observed.options.initialState.tools, []);
	assert.equal(events.at(-1).type, "done");
	assert.equal(events.at(-1).text, "hello from fake agent");
	assert.equal(session.agent.state.model, model);
});

test("parseConversationMessages preserves assistant metadata and defaults replay metadata", () => {
	const parsed = parseConversationMessages(
		[
			{ role: "system", content: "system guidance" },
			{ role: "user", content: "hello" },
			{
				role: "assistant",
				content: "preserve me",
				provider: "anthropic",
				api: "anthropic-messages",
				model: "claude-3-7-sonnet",
				usage: { input: 11, output: 7 },
				stop_reason: "stop",
			},
			{
				role: "assistant",
				content: "selector fallback",
				model: "zai/glm-5.1",
			},
			{
				role: "assistant",
				content: "default everything",
			},
			{
				role: "tool",
				tool_call_id: "tool-1",
				name: "write_note",
				content: { ok: false },
				is_error: true,
			},
		],
		{
			provider: "google",
			api: "google-genai",
			model: "gemini-3-flash-preview",
		},
	);

	assert.equal(parsed.systemPrompt, "system guidance");
	assert.equal(parsed.messages[1].provider, "anthropic");
	assert.equal(parsed.messages[1].api, "anthropic-messages");
	assert.equal(parsed.messages[1].model, "claude-3-7-sonnet");
	assert.deepEqual(parsed.messages[1].usage, { input: 11, output: 7 });
	assert.equal(parsed.messages[2].provider, "zai");
	assert.equal(parsed.messages[2].api, "google-genai");
	assert.equal(parsed.messages[2].model, "glm-5.1");
	assert.equal(parsed.messages[3].provider, "google");
	assert.equal(parsed.messages[3].api, "google-genai");
	assert.equal(parsed.messages[3].model, "gemini-3-flash-preview");
	assert.equal(parsed.messages[4].role, "toolResult");
	assert.equal(parsed.messages[4].isError, true);
});

test("serializeToolResultPayload bounds large bridge tool outputs", () => {
	const small = serializeToolResultPayload({ ok: true });
	assert.equal(small.text, '{"ok":true}');
	assert.deepEqual(small.details, { ok: true });

	const large = serializeToolResultPayload({ text: "x".repeat(13_000) });
	assert.equal(large.details._cloop_truncated, true);
	assert.equal(large.text.endsWith("\n… truncated"), true);
	assert.equal(large.details._cloop_preview, large.text);
	assert.ok(large.text.length <= 12_012);
});

test("buildBridgeErrorPayload returns explicit timeout and tool round limit errors", () => {
	assert.deepEqual(
		buildBridgeErrorPayload({
			requestId: "req-timeout",
			timedOut: true,
			finalMessage: { errorMessage: "timed out upstream" },
		}),
		{
			type: "error",
			request_id: "req-timeout",
			code: "timeout",
			message: "timed out upstream",
			retryable: false,
		},
	);
	assert.deepEqual(
		buildBridgeErrorPayload({
			requestId: "req-round-limit",
			roundLimitExceeded: true,
			toolRoundsUsed: 3,
			maxToolRounds: 2,
		}),
		{
			type: "error",
			request_id: "req-round-limit",
			code: "tool_round_limit",
			message:
				"Pi bridge tool round limit exceeded before the model produced a terminal response.",
			retryable: false,
			tool_rounds_used: 3,
			max_tool_rounds: 2,
			stop_reason: "aborted",
			partial_text: "",
		},
	);
});

test("resolveModelSelection falls back to the first available selector", async () => {
	const registry = {
		find(provider, model) {
			return { provider, id: model, api: "test-api" };
		},
		getAll() {
			return [
				{ provider: "zai", id: "glm-5.1", api: "test-api" },
				{ provider: "kimi-coding", id: "k2p6", api: "test-api" },
			];
		},
		async getAvailable() {
			return [{ provider: "kimi-coding", id: "k2p6", api: "test-api" }];
		},
	};

	const resolution = await resolveModelSelection(
		["zai/glm-5.1", "kimi-coding/k2p6"],
		"fallback",
		registry,
	);

	assert.equal(resolution.requestedSelector, "zai/glm-5.1");
	assert.deepEqual(resolution.requestedSelectors, [
		"zai/glm-5.1",
		"kimi-coding/k2p6",
	]);
	assert.equal(resolution.resolvedSelector, "kimi-coding/k2p6");
	assert.equal(resolution.fallbackUsed, true);
});

test("resolveModelSelection fails fast in exact mode", async () => {
	const registry = {
		find(provider, model) {
			return { provider, id: model, api: "test-api" };
		},
		getAll() {
			return [{ provider: "zai", id: "glm-5.1", api: "test-api" }];
		},
		async getAvailable() {
			return [];
		},
	};

	await assert.rejects(
		resolveModelSelection(["zai/glm-5.1"], "exact", registry),
		/not currently available|tried: zai\/glm-5\.1/i,
	);
});

test("parseModelSelector rejects unavailable models with pi guidance", async () => {
	const registry = {
		find(provider, model) {
			return provider === "zai" && model === "glm-5.1"
				? { provider, id: model, api: "zai-chat" }
				: null;
		},
		getAll() {
			return [{ provider: "zai", id: "glm-5.1", api: "zai-chat" }];
		},
		async getAvailable() {
			return [];
		},
	};

	await assert.rejects(
		parseModelSelector("zai/glm-5.1", registry),
		/not currently available|pi --list-models/i,
	);
});
