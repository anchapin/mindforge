import "@testing-library/jest-dom";
import { afterEach, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// Default QueryClient for tests
export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

// Render with QueryClient wrapper
export function renderWithQuery(ui: React.ReactElement, queryClient?: QueryClient) {
  const client = queryClient ?? createTestQueryClient();
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>
  );
}

// Cleanup after each test
afterEach(() => {
  cleanup();
});

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

// Mock WebSocket
class MockWebSocket {
  onmessage: ((data: { data: string }) => void) | null = null;
  onerror: ((error: unknown) => void) | null = null;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  readyState = 1; // OPEN
  send = vi.fn();
  close = vi.fn();
}
global.WebSocket = MockWebSocket as unknown as typeof WebSocket;