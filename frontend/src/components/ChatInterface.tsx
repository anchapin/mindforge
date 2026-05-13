import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createTask } from "../lib/api";

export function ChatInterface() {
  const [input, setInput] = useState("");
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (description: string) => createTask(description),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      setInput("");
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    mutation.mutate(input.trim());
  };

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="What would you like to do?"
        className="flex-1 rounded border border-zinc-700 bg-zinc-800 px-4 py-2 text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        disabled={mutation.isPending}
      />
      <button
        type="submit"
        disabled={!input.trim() || mutation.isPending}
        className="rounded bg-indigo-600 px-4 py-2 font-medium text-white transition hover:bg-indigo-500 disabled:opacity-50"
      >
        {mutation.isPending ? "Sending..." : "Send"}
      </button>
    </form>
  );
}
