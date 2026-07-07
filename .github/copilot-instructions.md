# Asistente_IA project instructions

This repository includes project-specific agents in the .github/agents folder. These agents should be used for architecture, implementation planning, implementation, testing, UI/UX auditing, and security review.

## Agent usage
- Use ai-architect for AI architecture, model selection, and prompt design.
- Use implementation-planner for planning changes and refactors.
- Use implementation for applying code changes.
- Use testing for test strategy and validation.
- Use design-system-auditor for UI/UX and desktop widget review.
- Use security-auditor for security analysis and hardening.

## Repository guidance
- Keep changes aligned with the existing Python and pytest-based structure.
- Prefer small, verifiable updates and include tests when behavior changes.
- Avoid committing secrets; use environment variables or .env files.
