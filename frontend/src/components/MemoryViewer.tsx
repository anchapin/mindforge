import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listMemory, searchMemory, type MemoryEntry } from "@/lib/api";

type MemoryType = "all" | "semantic" | "episodic" | "style";

interface MemoryResponse {
  semantic: MemoryEntry[];
  episodic: MemoryEntry[];
  style: MemoryEntry[];
}

export function MemoryViewer() {
  const [activeTab, setActiveTab] = useState<MemoryType>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [memoryInjectionEnabled, setMemoryInjectionEnabled] = useState(false);

  const { data: memories, isLoading } = useQuery<MemoryResponse>({
    queryKey: ["memories"],
    queryFn: listMemory,
  });

  const { data: searchResults } = useQuery<MemoryEntry[]>({
    queryKey: ["memory-search", searchQuery],
    queryFn: () => searchMemory(searchQuery),
    enabled: searchQuery.length > 0,
  });

  // Build the list of all memories based on mode
  let allMemories: MemoryEntry[] = [];
  if (searchQuery && searchResults) {
    allMemories = searchResults;
  } else if (memories) {
    allMemories = [
      ...memories.semantic,
      ...memories.episodic,
      ...memories.style,
    ];
  }

  const filteredMemories = allMemories.filter((m) => {
    if (activeTab === "all") return true;
    return m.memory_type === activeTab;
  });

  const tabs: { key: MemoryType; label: string }[] = [
    { key: "all", label: "All" },
    { key: "semantic", label: "Semantic" },
    { key: "episodic", label: "Episodes" },
    { key: "style", label: "Writing Style" },
  ];

  return (
    <div className="rounded border border-zinc-700 bg-zinc-900 p-4">
      <h2 className="mb-4 text-lg font-semibold text-zinc-100">Memory</h2>

      {/* Tabs */}
      <div className="mb-4 flex gap-1 border-b border-zinc-700">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-3 py-1 text-sm ${
              activeTab === tab.key
                ? "border-b-2 border-indigo-500 text-indigo-400"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="mb-4 flex gap-2">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search memories..."
          className="flex-1 rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
        />
        <button
          onClick={() => setSearchQuery("")}
          className="rounded border border-zinc-700 px-3 py-2 text-sm text-zinc-400 hover:text-zinc-200"
        >
          Clear
        </button>
      </div>

      {/* Memory injection toggle */}
      <div className="mb-4 flex items-center gap-2">
        <input
          type="checkbox"
          id="memory-injection"
          checked={memoryInjectionEnabled}
          onChange={(e) => setMemoryInjectionEnabled(e.target.checked)}
          className="h-4 w-4 rounded border-zinc-600 bg-zinc-800 text-indigo-600 focus:ring-indigo-500"
        />
        <label htmlFor="memory-injection" className="text-sm text-zinc-400">
          Memory injection enabled
        </label>
      </div>

      {/* Loading state */}
      {isLoading && <p className="text-zinc-500">Loading memories...</p>}

      {/* Memory list */}
      <div className="space-y-2">
        {filteredMemories.length === 0 && !isLoading && (
          <p className="text-zinc-500">No memories found</p>
        )}
        {filteredMemories.map((memory) => (
          <div
            key={memory.id}
            className="rounded border border-zinc-700 bg-zinc-800 p-3"
          >
            <p className="text-sm text-zinc-200">{memory.content}</p>
            <p className="mt-1 text-xs text-zinc-500">
              {memory.memory_type} · {new Date(memory.created_at).toLocaleDateString()}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}