/**
 * http.ts - Shared frontend HTTP helpers.
 *
 * Purpose:
 *   Centralize strict JSON request/response handling for the Vite + TypeScript
 *   frontend platform.
 *
 * Responsibilities:
 *   - Send JSON and FormData requests safely.
 *   - Extract structured backend error messages.
 *   - Return typed JSON responses to frontend callers.
 *
 * Scope:
 *   - Generic transport helpers only.
 *
 * Usage:
 *   - Import requestJson/requestStream from frontend API modules.
 *
 * Invariants/Assumptions:
 *   - Backend error payloads may contain message/detail/error.message shapes.
 *   - 204 responses are represented as null in typed callers.
 */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readMessage(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  if (!isRecord(value)) {
    return null;
  }

  const detail = value["detail"];
  const message = value["message"];
  const error = value["error"];

  if (
    isRecord(detail)
    && typeof detail["message"] === "string"
    && detail["message"].trim()
  ) {
    return detail["message"];
  }
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (typeof message === "string" && message.trim()) {
    return message;
  }
  if (
    isRecord(error)
    && typeof error["message"] === "string"
    && error["message"].trim()
  ) {
    return error["message"];
  }
  return null;
}

export async function extractErrorMessage(
  response: Response,
  fallbackMessage: string,
): Promise<string> {
  try {
    const payload: unknown = await response.json();
    return readMessage(payload) ?? fallbackMessage;
  } catch {
    return fallbackMessage;
  }
}

type JsonRequestInit<TBody> = Omit<RequestInit, "body"> & {
  body?: TBody;
};

function buildRequestInit<TBody>(init: JsonRequestInit<TBody>): RequestInit {
  const headers = new Headers(init.headers);
  let body: BodyInit | null = null;

  if (init.body instanceof FormData) {
    body = init.body;
  } else if (typeof init.body === "string") {
    body = init.body;
  } else if (init.body !== undefined) {
    headers.set("content-type", "application/json");
    body = JSON.stringify(init.body);
  }

  return {
    ...init,
    headers,
    body,
  };
}

export async function requestJson<TResponse, TBody = undefined>(
  path: string,
  init: JsonRequestInit<TBody> = {},
  fallbackMessage = "Request failed",
): Promise<TResponse> {
  const response = await fetch(path, buildRequestInit(init));

  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, fallbackMessage));
  }

  if (response.status === 204) {
    return null as TResponse;
  }

  return (await response.json()) as TResponse;
}

export async function requestStream<TBody = undefined>(
  path: string,
  init: JsonRequestInit<TBody> = {},
  fallbackMessage = "Request failed",
): Promise<Response> {
  const response = await fetch(path, buildRequestInit(init));

  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, fallbackMessage));
  }

  return response;
}
