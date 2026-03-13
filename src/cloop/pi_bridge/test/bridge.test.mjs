import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import readline from "node:readline";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const bridgePath = path.resolve(testDir, "..", "bridge.mjs");
const bridgeModule = await import(pathToFileURL(bridgePath).href);

const { buildBridgeErrorPayload, parseConversationMessages, parseModelSelector } = bridgeModule;

function startBridge() {
	const child = spawn(process.execPath, [bridgePath], {
		stdio: ["pipe", "pipe", "pipe"],
	});
	const rl = readline.createInterface({ input: child.stdout, crlfDelay: Infinity });
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
		exitError = new Error(`bridge exited before emitting a line (code=${code}, signal=${signal})`);
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
				model: "openai/gpt-5.4",
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
	assert.equal(parsed.messages[2].provider, "openai");
	assert.equal(parsed.messages[2].api, "google-genai");
	assert.equal(parsed.messages[2].model, "gpt-5.4");
	assert.equal(parsed.messages[3].provider, "google");
	assert.equal(parsed.messages[3].api, "google-genai");
	assert.equal(parsed.messages[3].model, "gemini-3-flash-preview");
	assert.equal(parsed.messages[4].role, "toolResult");
	assert.equal(parsed.messages[4].isError, true);
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
		}),
		{
			type: "error",
			request_id: "req-round-limit",
			code: "tool_round_limit",
			message: "Pi bridge tool round limit exceeded before the model produced a terminal response.",
			retryable: false,
		},
	);
});

test("parseModelSelector rejects unavailable models with pi guidance", async () => {
	const registry = {
		find(provider, model) {
			return provider === "openai" && model === "gpt-5.4"
				? { provider, id: model, api: "openai-responses" }
				: null;
		},
		getAll() {
			return [{ provider: "openai", id: "gpt-5.4", api: "openai-responses" }];
		},
		async getAvailable() {
			return [];
		},
	};

	await assert.rejects(
		parseModelSelector("openai/gpt-5.4", registry),
		/not currently available|pi --list-models/i,
	);
});
