#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional


MANAGED_START = "<!-- compound-orchestrator:start -->"
MANAGED_END = "<!-- compound-orchestrator:end -->"
CLAUDE_AGENT_TEAM_ENV = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

REQUIRED_FILES = [
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CODEBASE_MAP.md",
    "STRATEGY.md",
    ".agent-loop/task-brief-template.md",
    ".agent-loop/handoff-template.md",
    ".agent-loop/review-rubric.md",
    ".agent-loop/eval-scorecard.md",
    ".agent-loop/harness-checklist.md",
    ".agent-loop/module-claude-template.md",
    ".agent-loop/path-scoped-skill-template.md",
    ".agent-loop/lsp-mcp-roadmap.md",
    ".agent-loop/harness-ownership.md",
    ".agent-loop/team-topology.md",
    ".agent-loop/codex-parallel-contract.md",
    ".agent-loop/cross-tool-protocol.md",
    ".agent-loop/core-planning-artifacts.md",
    ".agent-loop/two-round-review-protocol.md",
    ".agent-loop/parallel-agent-team-protocol.md",
    ".agent-loop/deliverables-checklist.md",
    ".agent-loop/readme-maintenance.md",
    ".agent-loop/coordination/ownership.json",
    "prd.html",
    "planning.html",
    "spec.html",
    "test-cases.html",
    "architecture.html",
    "architecture.excalidraw",
    "users.html",
    ".claude/settings.json",
    ".claude/commands/compound-start.md",
    ".claude/commands/compound-plan.md",
    ".claude/commands/compound-review.md",
    ".claude/commands/compound-learn.md",
    ".claude/commands/compound-init.md",
    ".claude/commands/compound-team-start.md",
    ".claude/commands/compound-harness-check.md",
    ".claude/commands/compound-claim.md",
    ".claude/commands/compound-release.md",
    ".claude/commands/compound-ownership-status.md",
    ".claude/commands/compound-cross-review.md",
    ".claude/commands/compound-deliverables-check.md",
    ".claude/agents/compound-architect.md",
    ".claude/agents/compound-reviewer.md",
    ".claude/agents/compound-test-runner.md",
    ".claude/agents/compound-cross-tool-reviewer.md",
    "scripts/compound_orchestrator.py",
    "scripts/verify.py",
    "scripts/verify.ps1",
    "scripts/verify.sh",
]

IGNORED_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".next",
    "vendor",
    "generated",
}


def normalize_scope_path(value: str) -> str:
    value = value.strip().replace("\\", "/")
    while "//" in value:
        value = value.replace("//", "/")
    if value.startswith("./"):
        value = value[2:]
    value = value.strip("/")
    return value or "."


def paths_overlap(left: str, right: str) -> bool:
    left = normalize_scope_path(left)
    right = normalize_scope_path(right)
    if left == "." or right == ".":
        return True
    if "*" in left or "?" in left or "[" in left:
        return left == right or right.startswith(left.split("*", 1)[0].rstrip("/") + "/")
    if "*" in right or "?" in right or "[" in right:
        return left == right or left.startswith(right.split("*", 1)[0].rstrip("/") + "/")
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def load_json(path: Path, errors: List[str]) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"Invalid JSON in {path}: {exc}")
    return None


def verify_compound(root: Path) -> List[str]:
    errors: List[str] = []

    for item in REQUIRED_FILES:
        if not (root / item).is_file():
            errors.append(f"Missing required compound file: {item}")

    for item in ["README.md", "AGENTS.md", "CLAUDE.md"]:
        path = root / item
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if MANAGED_START not in text or MANAGED_END not in text:
                errors.append(f"Missing managed compound block in {item}")

    readme_policy = root / ".agent-loop/readme-maintenance.md"
    if readme_policy.exists():
        text = readme_policy.read_text(encoding="utf-8")
        for phrase in ["Remove old information", "Keep unchanged information", "Add new content", "Reorganize"]:
            if phrase not in text:
                errors.append(f"README maintenance guide is missing policy phrase: {phrase}")

    architecture_html = root / "architecture.html"
    if architecture_html.exists():
        text = architecture_html.read_text(encoding="utf-8").lower()
        if "excalidraw" not in text or "architecture.excalidraw" not in text:
            errors.append("architecture.html must reference architecture.excalidraw")
    architecture_diagram = root / "architecture.excalidraw"
    if architecture_diagram.exists():
        diagram = load_json(architecture_diagram, errors)
        if isinstance(diagram, dict) and diagram.get("type") != "excalidraw":
            errors.append("architecture.excalidraw must have type=excalidraw")
    test_cases = root / "test-cases.html"
    if test_cases.exists():
        text = test_cases.read_text(encoding="utf-8").lower()
        for phrase in ["spec.html", "happy", "edge", "error", "performance", "user workflow", "acceptance"]:
            if phrase not in text:
                errors.append(f"test-cases.html must map coverage to spec.html and include: {phrase}")

    settings_path = root / ".claude/settings.json"
    if settings_path.exists():
        settings = load_json(settings_path, errors)
        if isinstance(settings, dict):
            env = settings.get("env")
            if not isinstance(env, dict) or env.get(CLAUDE_AGENT_TEAM_ENV) != "1":
                errors.append(f"Missing Claude agent team env flag: env.{CLAUDE_AGENT_TEAM_ENV} = \"1\"")
            permissions = settings.get("permissions")
            deny = permissions.get("deny") if isinstance(permissions, dict) else None
            if not isinstance(deny, list) or not deny:
                errors.append("Missing permissions.deny entries in .claude/settings.json")

    ownership_path = root / ".agent-loop/coordination/ownership.json"
    if ownership_path.exists():
        ownership = load_json(ownership_path, errors)
        if isinstance(ownership, dict):
            claims = ownership.get("claims", [])
            if not isinstance(claims, list):
                errors.append(".agent-loop/coordination/ownership.json claims must be a list")
                claims = []
            active = [claim for claim in claims if isinstance(claim, dict) and claim.get("status") == "active"]
            for index, left in enumerate(active):
                for right in active[index + 1 :]:
                    same_claimant = (
                        left.get("tool") == right.get("tool")
                        and left.get("agent") == right.get("agent")
                        and left.get("task_id") == right.get("task_id")
                    )
                    if same_claimant:
                        continue
                    if paths_overlap(str(left.get("path", "")), str(right.get("path", ""))):
                        errors.append(
                            "Active ownership conflict: "
                            f"{left.get('tool')}/{left.get('agent')} owns {left.get('path')} and "
                            f"{right.get('tool')}/{right.get('agent')} owns {right.get('path')}"
                        )
        elif ownership is not None:
            errors.append(".agent-loop/coordination/ownership.json must contain an object")

    return errors


def package_scripts(root: Path) -> Dict[str, str]:
    package_path = root / "package.json"
    if not package_path.exists():
        return {}
    try:
        data = json.loads(package_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"__error__": f"Invalid JSON in package.json: {exc}"}
    scripts = data.get("scripts", {})
    return scripts if isinstance(scripts, dict) else {}


def run_command(root: Path, command: List[str]) -> Optional[str]:
    printable = " ".join(command)
    print(f"running: {printable}")
    try:
        completed = subprocess.run(command, cwd=root, check=False)
    except FileNotFoundError:
        return f"Command not found: {command[0]}"
    if completed.returncode != 0:
        return f"Command failed ({completed.returncode}): {printable}"
    return None


def markdown_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for path in root.rglob("*.md"):
        relative_parts = path.relative_to(root).parts
        if any(part in IGNORED_PARTS for part in relative_parts):
            continue
        files.append(path)
    return files


def scan_markdown_conflicts(root: Path) -> List[str]:
    errors: List[str] = []
    for path in markdown_files(root):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("<<<<<<<") or stripped.startswith("=======") or stripped.startswith(">>>>>>>"):
                errors.append(f"Merge conflict marker in {path.relative_to(root).as_posix()}:{line_number}")
    return errors


def verify_project(root: Path) -> List[str]:
    errors: List[str] = []
    scripts = package_scripts(root)
    if "__error__" in scripts:
        errors.append(scripts["__error__"])
    else:
        for script_name in ["lint", "typecheck", "test", "build"]:
            if script_name in scripts:
                npm_command = ["npm", "test"] if script_name == "test" else ["npm", "run", script_name]
                error = run_command(root, npm_command)
                if error:
                    errors.append(error)

    if (root / "tests").is_dir() or (root / "pyproject.toml").exists():
        python = os.environ.get("PYTHON") or sys.executable
        if (root / "tests").is_dir():
            error = run_command(root, [python, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"])
            if error:
                errors.append(error)

    errors.extend(scan_markdown_conflicts(root))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify this project and its compound orchestration harness.")
    parser.add_argument("--compound-only", action="store_true", help="Check only Compound Orchestrator files and claims.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    errors = verify_compound(root)
    if not args.compound_only and not errors:
        errors.extend(verify_project(root))

    if errors:
        print("verification: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
