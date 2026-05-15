/**
 * useTokenStream -- React hook that streams LLM tokens from the backend
 * SSE endpoint introduced in #50 (GET /api/tasks/{taskId}/stream).
 *
 * Usage:
 *   const { tokens, isStreaming, error, disconnect } = useTokenStream(taskId);
 *
 * Contract:
 *   - Pass `null` to opt out (no EventSource is opened).
 *   - When `taskId` changes, the previous stream is closed and a new one
 *     is opened against the new id.
 *   - The `[DONE]` sentinel from the backend stops streaming and closes
 *     the underlying EventSource cleanly.
 *   - `disconnect()` lets the caller close the stream imperatively.
 *
 * The hook is intentionally a small primitive -- the draft-preview UI
 * integration is a follow-up. See SPEC §5.7.9.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { API_BASE } from "./api";

export interface TokenStreamState {
  tokens: string;
  isStreaming: boolean;
  error: Event | null;
  disconnect: () => void;
}

const DONE_SENTINEL = "[DONE]";

/**
 * Parse the SSE payload as either:
 *   - JSON: { token: "..." } -> returns the token string
 *   - Plain string -> returns it verbatim
 *   - DONE sentinel -> returns null (caller stops streaming)
 *
 * Pinned by useTokenStream.test.ts so a JSON-shape change doesn't
 * silently drop tokens.
 */
function parseTokenPayload(raw: string): string | null {
  if (raw === DONE_SENTINEL) return null;
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && "token" in parsed) {
      return String((parsed as { token: unknown }).token ?? "");
    }
    if (typeof parsed === "string") return parsed;
    return raw;
  } catch {
    return raw;
  }
}

export function useTokenStream(taskId: string | null): TokenStreamState {
  const [tokens, setTokens] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<Event | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  const disconnect = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
    setIsStreaming(false);
  }, []);

  useEffect(() => {
    if (!taskId) {
      // Opt-out -- close any in-flight stream.
      disconnect();
      return;
    }

    // Reset accumulator on (re)connect so old tokens don't bleed across
    // taskId changes.
    setTokens("");
    setError(null);
    setIsStreaming(true);

    const url = `${API_BASE}/api/tasks/${encodeURIComponent(taskId)}/stream`;
    const es = new EventSource(url);
    sourceRef.current = es;

    es.onmessage = (e: MessageEvent) => {
      const data = typeof e.data === "string" ? e.data : String(e.data ?? "");
      // Do NOT trim -- whitespace tokens (e.g. " ", "\n") are legal LLM
      // output. Only the sentinel comparison needs an exact match.
      const token = parseTokenPayload(data);
      if (token === null) {
        // Backend signalled end of stream.
        setIsStreaming(false);
        es.close();
        sourceRef.current = null;
        return;
      }
      setTokens((prev) => prev + token);
    };

    es.onerror = (e: Event) => {
      setError(e);
      setIsStreaming(false);
      es.close();
      sourceRef.current = null;
    };

    return () => {
      es.close();
      sourceRef.current = null;
    };
    // disconnect is stable (useCallback with []), so depending on it is safe
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  return { tokens, isStreaming, error, disconnect };
}
