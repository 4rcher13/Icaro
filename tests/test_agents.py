import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
AGENTS_DIR = PROJECT_ROOT / ".github" / "agents"
CURSOR_RULES_DIR = PROJECT_ROOT / ".cursor" / "rules"
SKILLS_DIR = PROJECT_ROOT / ".agents" / "skills"
AGENTS_MD_PATH = PROJECT_ROOT / "AGENTS.md"

def get_expected_agents_from_manifest():
    """Parse AGENTS.md to get the list of expected agents."""
    if not AGENTS_MD_PATH.exists():
        return []
    
    content = AGENTS_MD_PATH.read_text(encoding="utf-8")
    agents = []
    in_agents_section = False
    
    for line in content.splitlines():
        if line.strip() == "## Available agents":
            in_agents_section = True
            continue
        elif in_agents_section and line.startswith("## "):
            break
            
        if in_agents_section and line.strip().startswith("- "):
            # Extract agent name, e.g., "- ai-architect" or "- calidad / arquitectura (quality&architecture(auditor))"
            agent_line = line.strip()[2:]
            
            agent_name = agent_line.strip()
            agents.append(agent_name)
            
    return agents

def get_agent_files():
    if not AGENTS_DIR.exists():
        return []
    return list(AGENTS_DIR.glob("*.agent.md"))

def test_manifest_matches_files():
    """Verify that all agents listed in AGENTS.md exist as files and vice versa."""
    expected_agents = get_expected_agents_from_manifest()
    assert len(expected_agents) > 0, "No expected agents found in AGENTS.md"
    
    actual_agent_files = [f.name.replace(".agent.md", "") for f in get_agent_files()]
    
    # Check that all expected agents exist
    missing_files = set(expected_agents) - set(actual_agent_files)
    assert not missing_files, f"Agents listed in AGENTS.md but missing files: {missing_files}"
    
    # Check that all files are listed in expected agents
    missing_in_manifest = set(actual_agent_files) - set(expected_agents)
    assert not missing_in_manifest, f"Agent files present but not listed in AGENTS.md: {missing_in_manifest}"

def test_agents_directory_exists():
    """Verify that the agents directory exists."""
    assert AGENTS_DIR.exists(), f"Agents directory not found at {AGENTS_DIR}"

def test_all_agents_have_bridge_files():
    """Verify that every agent has a corresponding Cursor rule and Antigravity skill."""
    agent_files = get_agent_files()
    assert len(agent_files) > 0, "No agent files found to test."
    
    for agent_file in agent_files:
        agent_name = agent_file.name.replace(".agent.md", "")
        
        # Check Cursor rule
        cursor_file = CURSOR_RULES_DIR / f"{agent_name}.mdc"
        assert cursor_file.exists(), f"Missing Cursor rule for {agent_name} at {cursor_file}"
        
        # Check Antigravity skill
        skill_file = SKILLS_DIR / agent_name / "SKILL.md"
        assert skill_file.exists(), f"Missing Antigravity skill for {agent_name} at {skill_file}"

def test_agents_are_ide_agnostic():
    """Verify that agents do not contain IDE-specific wording in their body."""
    agent_files = get_agent_files()
    
    for agent_file in agent_files:
        content = agent_file.read_text(encoding="utf-8")
        
        # Split by YAML frontmatter to only check the body
        parts = content.split("---")
        body = parts[-1] if len(parts) >= 3 else content
        
        # Look for specific VS Code terminology that shouldn't be there
        forbidden_terms = [
            r"vs code chat participant",
            r"vscode chat ui",
            r"vscode chat panel",
            r"vscode/runcommand",
            r"edit/editfiles"
        ]
        
        for term in forbidden_terms:
            matches = re.finditer(term, body, re.IGNORECASE)
            match_list = list(matches)
            assert len(match_list) == 0, f"Found forbidden term '{term}' in {agent_file.name}"
