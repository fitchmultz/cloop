import { describe, expect, it } from "vitest";

import { formatToolJsonPreview } from "./chat";

describe("formatToolJsonPreview", () => {
  it("keeps small tool payloads readable", () => {
    expect(formatToolJsonPreview({ ok: true })).toBe('{\n  "ok": true\n}');
  });

  it("formats undefined payloads without throwing", () => {
    expect(formatToolJsonPreview(undefined)).toBe("undefined");
  });

  it("bounds large tool payloads with a clear truncation marker", () => {
    const preview = formatToolJsonPreview({ text: "x".repeat(9_000) });

    expect(preview.length).toBeLessThanOrEqual(8_012);
    expect(preview.endsWith("\n… truncated")).toBe(true);
    expect(preview).toContain('"text"');
  });
});
