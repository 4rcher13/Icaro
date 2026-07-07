# Asistente_IA agent manifest

This repository defines project agents in the .github/agents folder. They are intended to be discoverable by compatible IDEs and CLI tools such as GitHub Copilot, Copilot CLI, Cursor, Antigravity, and similar environments.

## Available agents
- ai-architect
- design-system-auditor
- implementation-planner
- implementation
- security-auditor
- testing
- calidad / arquitectura (quality&architecture(auditor))
- seguridad

## Discovery files
- .github/agents/: agent definitions
- .github/copilot-instructions.md: shared instructions for Copilot-compatible tools
- .github/instructions/: additional repo instructions
- .cursor/rules/: Cursor-compatible project rules

When a task matches one of these areas, choose the most appropriate agent and keep the work scoped to the repository.
