/**
 * /skills/new and /skills/:id/edit — SkillEditor host.
 */

import { useParams, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { SkillEditor } from "../components/SkillEditor";
import { API_BASE, getSkill } from "../lib/api";

export default function SkillEditPage() {
  // useParams returns {} on /skills/new since there's no skillId param;
  // strict:false suppresses the type-narrowing warning for this case.
  const params = useParams({ strict: false }) as { skillId?: string };
  const navigate = useNavigate();
  const skillId = params.skillId;

  const { data: existing, isLoading } = useQuery({
    queryKey: ["skill", skillId],
    queryFn: () => getSkill(skillId!),
    enabled: Boolean(skillId),
  });

  const initial = (existing as { yaml_content?: string } | undefined)?.yaml_content;

  if (skillId && isLoading) {
    return <p className="text-sm text-zinc-500">Loading skill…</p>;
  }

  const handleSave = async (yamlContent: string) => {
    // Create new vs. update existing
    const url = skillId
      ? `${API_BASE}/api/skills/${skillId}`
      : `${API_BASE}/api/skills/`;
    const res = await fetch(url, {
      method: skillId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        // POST shape is {name, yaml_content}; we let the YAML's own `name`
        // field carry through and let the backend extract it. The editor
        // sends the canonical name in the YAML so we just echo a sensible
        // default for the dedicated field.
        name: skillId ?? "new-skill",
        yaml_content: yamlContent,
      }),
    });
    if (!res.ok) {
      throw new Error(`Save failed: ${res.status} ${res.statusText}`);
    }
    // Navigate to the skills list after success
    navigate({ to: "/skills" });
  };

  return (
    <section className="space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">
          {skillId ? `Edit skill: ${skillId}` : "Create new skill"}
        </h1>
      </header>
      <SkillEditor initialYaml={initial} onSave={handleSave} />
    </section>
  );
}
