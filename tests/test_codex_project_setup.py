from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_project_codex_config_enables_bounded_parallelism():
    config = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))

    assert config["agents"]["enabled"] is True
    assert config["agents"]["max_concurrent_threads_per_session"] == 3


def test_project_custom_agents_are_bounded_and_read_only():
    agent_dir = ROOT / ".codex" / "agents"
    agents = [
        tomllib.loads(path.read_text(encoding="utf-8")) for path in sorted(agent_dir.glob("*.toml"))
    ]

    assert {agent["name"] for agent in agents} == {
        "aiguard_explorer",
        "aiguard_reviewer",
        "aiguard_docs_auditor",
    }
    for agent in agents:
        assert agent["sandbox_mode"] == "read-only"
        assert agent["description"]
        assert agent["developer_instructions"]
        assert "model" not in agent


def test_repo_guidance_and_skill_references_stay_valid():
    agents_md = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    skill = (ROOT / ".agents" / "skills" / "aiguard-change-workflow" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    check_matrix = (
        ROOT / ".agents" / "skills" / "aiguard-change-workflow" / "references" / "check-matrix.md"
    ).read_text(encoding="utf-8")

    assert len(agents_md.splitlines()) < 180
    for relative_path in (
        "docs/README.md",
        "docs/architecture.md",
        "docs/project-status.md",
        "ROADMAP.md",
        "docs/acceptance/README.md",
        "docs/platform/ai-for-thai.md",
        "docs/release-process.md",
        "desktop/src/app.js",
        "desktop/src/api.js",
        "office-addin/package.json",
    ):
        assert (ROOT / relative_path).exists(), relative_path

    frontmatter = re.match(r"\A---\n(?P<body>.*?)\n---\n", skill, re.DOTALL)
    assert frontmatter
    assert "name: aiguard-change-workflow" in frontmatter["body"]
    assert "description:" in frontmatter["body"]
    assert "references/check-matrix.md" in skill
    assert "desktop\\src\\app.js" in check_matrix
    assert "office-addin" in check_matrix
