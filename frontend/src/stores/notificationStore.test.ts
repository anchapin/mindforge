/**
 * Notification + clarification store tests (#47).
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useNotificationStore } from "./notificationStore";

describe("notificationStore", () => {
  beforeEach(() => {
    useNotificationStore.getState().clearAll();
  });

  describe("notifications", () => {
    it("starts empty", () => {
      expect(useNotificationStore.getState().notifications).toEqual([]);
    });

    it("pushNotification prepends with read=false by default", () => {
      useNotificationStore.getState().pushNotification({
        id: "n1",
        type: "info",
        message: "hello",
        timestamp: "2026-05-15T00:00:00Z",
      });
      const list = useNotificationStore.getState().notifications;
      expect(list).toHaveLength(1);
      expect(list[0].read).toBe(false);
      expect(list[0].id).toBe("n1");
    });

    it("pushNotification de-dups by id (most recent wins, no duplicate row)", () => {
      const store = useNotificationStore.getState();
      store.pushNotification({
        id: "dup",
        type: "info",
        message: "first",
        timestamp: "t1",
      });
      store.pushNotification({
        id: "dup",
        type: "warning",
        message: "second",
        timestamp: "t2",
      });
      const list = useNotificationStore.getState().notifications;
      expect(list).toHaveLength(1);
      expect(list[0].message).toBe("second");
      expect(list[0].type).toBe("warning");
    });

    it("markRead flips read flag for the matching id only", () => {
      const s = useNotificationStore.getState();
      s.pushNotification({ id: "a", type: "info", message: "a", timestamp: "t" });
      s.pushNotification({ id: "b", type: "info", message: "b", timestamp: "t" });
      s.markRead("a");
      const list = useNotificationStore.getState().notifications;
      expect(list.find((n) => n.id === "a")!.read).toBe(true);
      expect(list.find((n) => n.id === "b")!.read).toBe(false);
    });

    it("markAllRead flips every flag", () => {
      const s = useNotificationStore.getState();
      s.pushNotification({ id: "a", type: "info", message: "a", timestamp: "t" });
      s.pushNotification({ id: "b", type: "info", message: "b", timestamp: "t" });
      s.markAllRead();
      const list = useNotificationStore.getState().notifications;
      expect(list.every((n) => n.read)).toBe(true);
    });

    it("dismiss removes the matching notification", () => {
      const s = useNotificationStore.getState();
      s.pushNotification({ id: "a", type: "info", message: "a", timestamp: "t" });
      s.pushNotification({ id: "b", type: "info", message: "b", timestamp: "t" });
      s.dismiss("a");
      const list = useNotificationStore.getState().notifications;
      expect(list.map((n) => n.id)).toEqual(["b"]);
    });

    it("caps the in-memory list at 100", () => {
      const s = useNotificationStore.getState();
      for (let i = 0; i < 120; i++) {
        s.pushNotification({
          id: `n${i}`,
          type: "info",
          message: `m${i}`,
          timestamp: "t",
        });
      }
      expect(useNotificationStore.getState().notifications).toHaveLength(100);
    });
  });

  describe("clarifications", () => {
    it("starts empty", () => {
      expect(useNotificationStore.getState().pendingClarifications).toEqual([]);
    });

    it("pushClarification appends; resolveClarification removes by taskId", () => {
      const s = useNotificationStore.getState();
      s.pushClarification({
        taskId: "t1",
        agentName: "researcher",
        question: "Which option?",
        choices: ["a", "b"],
      });
      s.pushClarification({
        taskId: "t2",
        agentName: "cmo",
        question: "Tone?",
        choices: [],
      });
      expect(useNotificationStore.getState().pendingClarifications).toHaveLength(2);

      s.resolveClarification("t1");
      const remaining = useNotificationStore.getState().pendingClarifications;
      expect(remaining.map((c) => c.taskId)).toEqual(["t2"]);
    });

    it("pushClarification de-dups by taskId (redelivered WS frame)", () => {
      const s = useNotificationStore.getState();
      s.pushClarification({
        taskId: "t1",
        agentName: "researcher",
        question: "Which?",
        choices: [],
      });
      s.pushClarification({
        taskId: "t1",
        agentName: "researcher",
        question: "Which? (resent)",
        choices: [],
      });
      expect(useNotificationStore.getState().pendingClarifications).toHaveLength(1);
    });
  });
});
