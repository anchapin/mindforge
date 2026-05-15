/**
 * Unit tests for useTokenStream (#50).
 *
 * Mocks EventSource so we can drive the SSE protocol without spinning up
 * a real backend. Pins:
 *   - Tokens accumulate in order.
 *   - "[DONE]" sentinel flips isStreaming to false without recording the
 *     sentinel itself.
 *   - error events surface via the `error` field.
 *   - Unmount calls EventSource.close (no leaked sockets).
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

import { useTokenStream } from "./useTokenStream";

class FakeEventSource {
  static lastInstance: FakeEventSource | null = null;

  url: string;
  readyState: number = 0;
  closed: boolean = false;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  onopen: ((e: Event) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    this.readyState = 1;
    FakeEventSource.lastInstance = this;
  }

  emit(data: string) {
    this.onmessage?.(new MessageEvent("message", { data }));
  }

  emitError() {
    this.onerror?.(new Event("error"));
  }

  close() {
    this.closed = true;
    this.readyState = 2;
  }
}

describe("useTokenStream", () => {
  let originalES: typeof EventSource;

  beforeEach(() => {
    originalES = (globalThis as any).EventSource;
    (globalThis as any).EventSource = FakeEventSource;
    FakeEventSource.lastInstance = null;
  });

  afterEach(() => {
    (globalThis as any).EventSource = originalES;
  });

  it("opens an EventSource at the right URL", () => {
    renderHook(() => useTokenStream("task-123"));
    expect(FakeEventSource.lastInstance?.url).toMatch(/\/api\/tasks\/task-123\/stream$/);
  });

  it("does NOT open a stream when taskId is null", () => {
    renderHook(() => useTokenStream(null));
    expect(FakeEventSource.lastInstance).toBeNull();
  });

  it("accumulates tokens in order", async () => {
    const { result } = renderHook(() => useTokenStream("task-abc"));
    const es = FakeEventSource.lastInstance!;
    act(() => {
      es.emit(JSON.stringify({ token: "Hello" }));
      es.emit(JSON.stringify({ token: " " }));
      es.emit(JSON.stringify({ token: "world" }));
    });
    await waitFor(() => expect(result.current.tokens).toBe("Hello world"));
    expect(result.current.isStreaming).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it("handles plain string payloads (non-JSON) by appending raw", async () => {
    const { result } = renderHook(() => useTokenStream("task-raw"));
    const es = FakeEventSource.lastInstance!;
    act(() => {
      es.emit("plain");
      es.emit(" text");
    });
    await waitFor(() => expect(result.current.tokens).toBe("plain text"));
  });

  it("[DONE] sentinel stops streaming without appending the sentinel", async () => {
    const { result } = renderHook(() => useTokenStream("task-done"));
    const es = FakeEventSource.lastInstance!;
    act(() => {
      es.emit(JSON.stringify({ token: "hi" }));
      es.emit("[DONE]");
    });
    await waitFor(() => expect(result.current.isStreaming).toBe(false));
    expect(result.current.tokens).toBe("hi");
    expect(es.closed).toBe(true);
  });

  it("surfaces errors and stops streaming", async () => {
    const { result } = renderHook(() => useTokenStream("task-err"));
    const es = FakeEventSource.lastInstance!;
    act(() => {
      es.emitError();
    });
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.isStreaming).toBe(false);
  });

  it("closes the EventSource on unmount", () => {
    const { unmount } = renderHook(() => useTokenStream("task-unmount"));
    const es = FakeEventSource.lastInstance!;
    unmount();
    expect(es.closed).toBe(true);
  });

  it("disconnect() closes the EventSource imperatively", () => {
    const { result } = renderHook(() => useTokenStream("task-disc"));
    const es = FakeEventSource.lastInstance!;
    act(() => result.current.disconnect());
    expect(es.closed).toBe(true);
  });

  it("opens a fresh stream when taskId changes", () => {
    const { rerender } = renderHook(({ id }: { id: string | null }) => useTokenStream(id), {
      initialProps: { id: "task-1" },
    });
    const first = FakeEventSource.lastInstance!;
    rerender({ id: "task-2" });
    const second = FakeEventSource.lastInstance!;
    expect(first.closed).toBe(true);
    expect(second.url).toMatch(/task-2\/stream$/);
  });
});
