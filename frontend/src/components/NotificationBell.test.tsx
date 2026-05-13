import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { NotificationBell } from "@/components/NotificationBell";

const mockNotifications = [
  { id: "1", type: "info" as const, message: "Task #23 completed", timestamp: "2024-01-15T10:00:00Z", read: false },
  { id: "2", type: "warning" as const, message: "Approval deadline approaching", timestamp: "2024-01-15T09:00:00Z", read: false },
  { id: "3", type: "success" as const, message: "GitHub PR merged", timestamp: "2024-01-15T08:00:00Z", read: true },
];

describe("NotificationBell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders bell icon", () => {
    const { container } = render(<NotificationBell notifications={[]} />);
    expect(container.querySelector("button")).toBeInTheDocument();
  });

  it("shows unread count badge when there are unread notifications", () => {
    render(<NotificationBell notifications={mockNotifications.filter((n) => !n.read)} />);

    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("does not show badge when all notifications are read", () => {
    render(<NotificationBell notifications={mockNotifications.filter((n) => n.read)} />);

    // Badge should not be visible when count is 0
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("opens dropdown when bell is clicked", async () => {
    render(<NotificationBell notifications={mockNotifications} />);

    await userEvent.click(screen.getByRole("button"));

    expect(screen.getByText("Notifications")).toBeInTheDocument();
  });

  it("renders notification list in dropdown", async () => {
    render(<NotificationBell notifications={mockNotifications} />);

    await userEvent.click(screen.getByRole("button"));

    expect(screen.getByText("Task #23 completed")).toBeInTheDocument();
    expect(screen.getByText("Approval deadline approaching")).toBeInTheDocument();
  });

  it("calls onMarkRead when 'Mark read' is clicked", async () => {
    const onMarkRead = vi.fn();
    render(<NotificationBell notifications={mockNotifications} onMarkRead={onMarkRead} />);

    await userEvent.click(screen.getByRole("button"));
    // There are multiple "Mark read" buttons - click the first one (first notification)
    await userEvent.click(screen.getAllByText("Mark read")[0]);

    expect(onMarkRead).toHaveBeenCalledWith("1");
  });

  it("calls onMarkAllRead when 'Mark all read' is clicked", async () => {
    const onMarkAllRead = vi.fn();
    render(<NotificationBell notifications={mockNotifications} onMarkAllRead={onMarkAllRead} />);

    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(screen.getByText("Mark all read"));

    expect(onMarkAllRead).toHaveBeenCalled();
  });

  it("calls onDismiss when dismiss button is clicked", async () => {
    const onDismiss = vi.fn();
    render(<NotificationBell notifications={mockNotifications} onDismiss={onDismiss} />);

    await userEvent.click(screen.getByRole("button"));
    // Click the dismiss button (X icon) on the first notification
    const dismissButtons = screen.getAllByLabelText("Dismiss notification");
    await userEvent.click(dismissButtons[0]);

    expect(onDismiss).toHaveBeenCalledWith("1");
  });

  it("shows empty state when no notifications", async () => {
    render(<NotificationBell notifications={[]} />);

    await userEvent.click(screen.getByRole("button"));

    expect(screen.getByText("No notifications")).toBeInTheDocument();
  });

  it("closes dropdown when backdrop is clicked", async () => {
    render(<NotificationBell notifications={mockNotifications} />);

    // Open the dropdown
    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
    expect(screen.getByText("Notifications")).toBeInTheDocument();

    // Click the backdrop (which has class 'fixed inset-0 z-40')
    const backdrop = document.querySelector(".fixed.inset-0.z-40");
    if (backdrop) {
      await userEvent.click(backdrop);
    }

    // The dropdown should be closed
    expect(screen.queryByText("Notifications")).not.toBeInTheDocument();
  });
});