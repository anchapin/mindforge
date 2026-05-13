import { useState } from "react";
import { Bell, X } from "lucide-react";

export interface Notification {
  id: string;
  type: "info" | "warning" | "error" | "success";
  message: string;
  timestamp: string;
  read: boolean;
}

interface NotificationBellProps {
  notifications: Notification[];
  onMarkRead?: (id: string) => void;
  onMarkAllRead?: () => void;
  onDismiss?: (id: string) => void;
}

export function NotificationBell({ notifications, onMarkRead, onMarkAllRead, onDismiss }: NotificationBellProps) {
  const [isOpen, setIsOpen] = useState(false);

  const unreadCount = notifications.filter((n) => !n.read).length;

  const getNotificationStyles = (type: Notification["type"]) => {
    switch (type) {
      case "error":
        return "border-red-600 bg-red-900/20";
      case "warning":
        return "border-amber-600 bg-amber-900/20";
      case "success":
        return "border-green-600 bg-green-900/20";
      default:
        return "border-zinc-600 bg-zinc-800";
    }
  };

  const getNotificationDotColor = (type: Notification["type"]) => {
    switch (type) {
      case "error":
        return "bg-red-500";
      case "warning":
        return "bg-amber-500";
      case "success":
        return "bg-green-500";
      default:
        return "bg-blue-500";
    }
  };

  return (
    <div className="relative">
      {/* Bell button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="relative rounded p-2 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-200"
        aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ""}`}
      >
        <Bell size={20} />
        {unreadCount > 0 && (
          <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-red-600 text-xs font-medium text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown */}
      {isOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
          />

          {/* Dropdown panel */}
          <div className="absolute right-0 top-full z-50 mt-2 w-80 rounded-lg border border-zinc-700 bg-zinc-900 shadow-xl">
            <div className="flex items-center justify-between border-b border-zinc-700 p-3">
              <h3 className="font-semibold text-zinc-100">Notifications</h3>
              <div className="flex gap-1">
                {unreadCount > 0 && (
                  <button
                    onClick={onMarkAllRead}
                    className="rounded px-2 py-1 text-xs text-indigo-400 hover:bg-zinc-800"
                  >
                    Mark all read
                  </button>
                )}
                <button
                  onClick={() => setIsOpen(false)}
                  className="rounded p-1 text-zinc-400 hover:bg-zinc-800"
                  aria-label="Close notifications"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* Notification list */}
            <div className="max-h-96 overflow-y-auto">
              {notifications.length === 0 ? (
                <p className="p-4 text-center text-sm text-zinc-500">No notifications</p>
              ) : (
                <ul>
                  {notifications.map((notification) => (
                    <li
                      key={notification.id}
                      className={`flex items-start gap-3 border-b border-zinc-800 p-3 last:border-b-0 ${getNotificationStyles(notification.type)}`}
                    >
                      <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${getNotificationDotColor(notification.type)}`} />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-zinc-200">{notification.message}</p>
                        <p className="mt-1 text-xs text-zinc-500">
                          {new Date(notification.timestamp).toLocaleString()}
                        </p>
                      </div>
                      <div className="flex shrink-0 gap-1">
                        {!notification.read && onMarkRead && (
                          <button
                            onClick={() => onMarkRead(notification.id)}
                            className="rounded px-2 py-1 text-xs text-indigo-400 hover:bg-zinc-700"
                          >
                            Mark read
                          </button>
                        )}
                        {onDismiss && (
                          <button
                            onClick={() => onDismiss(notification.id)}
                            className="rounded p-1 text-zinc-500 hover:bg-zinc-700 hover:text-zinc-300"
                            aria-label="Dismiss notification"
                          >
                            <X size={14} />
                          </button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}