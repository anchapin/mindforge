import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listSkills, type Skill } from "@/lib/api";

interface SkillLauncherProps {
  onActivate?: (skillId: string) => void;
}

export function SkillLauncher({ onActivate }: SkillLauncherProps) {
  const [searchQuery, setSearchQuery] = useState("");

  const { data: skills, isLoading } = useQuery({
    queryKey: ["skills"],
    queryFn: listSkills,
  });

  const filteredSkills = (skills ?? []).filter((skill: Skill) =>
    skill.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    skill.description?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="rounded border border-zinc-700 bg-zinc-900 p-4">
      <h2 className="mb-4 text-lg font-semibold text-zinc-100">Skills</h2>

      {/* Search */}
      <div className="mb-4">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search skills..."
          className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
        />
      </div>

      {/* Loading state */}
      {isLoading && <p className="text-zinc-500">Loading skills...</p>}

      {/* Skills grid */}
      <div className="grid gap-3">
        {filteredSkills.length === 0 && !isLoading && (
          <p className="text-zinc-500">No skills found</p>
        )}
        {filteredSkills.map((skill: Skill) => (
          <div
            key={skill.id}
            className="rounded border border-zinc-700 bg-zinc-800 p-3 transition hover:border-zinc-600"
          >
            <div className="flex items-start justify-between">
              <div className="min-w-0 flex-1">
                <h3 className="font-medium text-zinc-200">{skill.name}</h3>
                {skill.description && (
                  <p className="mt-1 text-sm text-zinc-400">{skill.description}</p>
                )}
              </div>
              <button
                onClick={() => onActivate?.(skill.id)}
                className="ml-2 shrink-0 rounded bg-indigo-600 px-3 py-1 text-sm font-medium text-white transition hover:bg-indigo-500"
              >
                Activate
              </button>
            </div>
            {skill.version && (
              <span className="mt-2 inline-block rounded bg-zinc-700 px-2 py-0.5 text-xs text-zinc-400">
                v{skill.version}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}