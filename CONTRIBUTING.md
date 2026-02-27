# Contributing to NetTap

Thank you for your interest in contributing to NetTap! This guide will help you get started.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Environment](#development-environment)
- [Branch Naming Convention](#branch-naming-convention)
- [Commit Convention](#commit-convention)
- [Pull Request Process](#pull-request-process)
- [Code Style](#code-style)
- [Testing](#testing)
- [Issue Labels and Priorities](#issue-labels-and-priorities)
- [Reporting Security Issues](#reporting-security-issues)

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## Getting Started

1. **Fork the repository** on GitHub.
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/<your-username>/NetTap.git
   cd NetTap
   ```
3. **Add the upstream remote:**
   ```bash
   git remote add upstream https://github.com/EliasMarine/NetTap.git
   ```
4. **Create a feature branch** from `develop`:
   ```bash
   git checkout develop
   git pull upstream develop
   git checkout -b phase-N/your-feature
   ```

## Development Environment

### Prerequisites

- **Host OS:** Ubuntu Server 22.04 LTS (for full appliance testing)
- **Docker** and **Docker Compose** (v2+)
- **Python 3.10+** (for the storage/health daemon)
- **Node.js 18+** and **npm** (for the web UI)
- **Git** with conventional commit tooling (optional but recommended)

### Setup

1. **Install system dependencies:**
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-pip python3-venv docker.io docker-compose-v2 nodejs npm
   ```

2. **Set up Python environment (for daemon development):**
   ```bash
   cd daemon
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Set up web UI (for dashboard development):**
   ```bash
   cd web
   npm install
   npm run dev
   ```

4. **Start the full stack (requires bridge-capable hardware):**
   ```bash
   sudo scripts/install/install.sh
   docker compose -f docker/docker-compose.yml up -d
   ```

### Development Without Hardware

You can develop and test many components without the full dual-NIC hardware setup:

- **Web UI:** Runs standalone with mock data via `npm run dev`
- **Daemon:** Can be tested with simulated disk metrics
- **Configuration:** Can be validated without running Malcolm

## Branch Naming Convention

All work happens on feature branches. Never commit directly to `main` or `develop`.

**Format:** `phase-N/short-description`

```
phase-1/bridge-hardening
phase-2/ilm-policies
phase-3/setup-wizard
phase-4/dashboard-home
phase-5/ci-pipeline
```

For cross-cutting work: `infra/description` or `chore/description`.

## Commit Convention

This project uses **Conventional Commits**. Every commit message must follow this format:

```
type(scope): short description

Optional body explaining the "why" (not the "what").
```

### Types

| Type       | When to use                                  |
|------------|----------------------------------------------|
| `feat`     | New feature or capability                    |
| `fix`      | Bug fix                                      |
| `docs`     | Documentation only                           |
| `refactor` | Code restructuring, no behavior change       |
| `test`     | Adding or updating tests                     |
| `chore`    | Maintenance, dependencies, config            |
| `ci`       | CI/CD pipeline changes                       |
| `perf`     | Performance improvement                      |
| `style`    | Formatting, whitespace, no logic change      |

### Scope (optional but encouraged)

The component affected:

```
feat(bridge): add netplan persistence for br0
fix(daemon): handle OpenSearch connection timeout
test(storage): add coverage for disk threshold logic
docs(readme): update architecture diagram
chore(docker): pin Malcolm images to v26.02.0
```

### Rules

- Use the imperative mood in the subject line ("add" not "added" or "adds").
- Do not end the subject line with a period.
- Keep the subject line under 72 characters.
- Wrap the body at 72 characters.
- One logical change per commit. Do not bundle unrelated changes.

## Pull Request Process

1. **Target `develop`** -- never `main`. The `main` branch only receives merges at major release milestones.
2. **Ensure your branch is up to date:**
   ```bash
   git fetch upstream
   git rebase upstream/develop
   ```
3. **Push your branch** and create a PR on GitHub:
   ```bash
   git push -u origin phase-N/your-feature
   ```
4. **Fill out the PR template** completely (summary, type of change, testing checklist).
5. **All CI checks must pass** before a PR will be reviewed.
6. **Request a review** from `@EliasMarine` or a relevant code owner.
7. **Address review feedback** with new commits (do not force-push during review).
8. After merge, **delete your feature branch**.

### PR Size Guidelines

- Keep PRs focused and reasonably sized (under ~400 lines of diff when possible).
- If a change is large, break it into smaller, reviewable PRs.
- Each PR should represent one logical unit of work.

## Code Style

### Python (daemon)

- **Linter/formatter:** [Ruff](https://docs.astral.sh/ruff/)
- Follow PEP 8 conventions.
- Use type hints for function signatures.
- Docstrings for public functions and classes (Google style).

```bash
# Check
ruff check daemon/
# Format
ruff format daemon/
```

### TypeScript / Svelte (web UI)

- **Linter:** ESLint with the project configuration
- **Type checking:** `svelte-check`
- Use TypeScript for all new code (no plain JavaScript).

```bash
cd web
npm run lint
npm run check
```

### Shell Scripts

- **Linter:** [ShellCheck](https://www.shellcheck.net/)
- Use `set -euo pipefail` at the top of scripts.
- Quote all variables.
- Use `#!/usr/bin/env bash` as the shebang.

```bash
shellcheck scripts/**/*.sh
```

## Testing

- **All existing tests must pass** before submitting a PR.
- **New features must include tests.**
- **Bug fixes should include a regression test** that would have caught the bug.

### Running Tests

```bash
# Python daemon tests
cd daemon
python -m pytest tests/ -v

# Web UI tests
cd web
npm test

# Shell script linting
shellcheck scripts/**/*.sh
```

## Issue Labels and Priorities

### Labels

| Label         | Description                                      |
|---------------|--------------------------------------------------|
| `Bug`         | Something is not working correctly               |
| `Feature`     | New functionality request                        |
| `Improvement` | Enhancement to existing functionality            |
| `Info`        | Informational (e.g., hardware compatibility)     |

### Priorities

| Priority | Level  | Description                                     |
|----------|--------|-------------------------------------------------|
| 1        | Urgent | Critical issue, needs immediate attention        |
| 2        | High   | Important, should be addressed soon              |
| 3        | Normal | Standard priority                                |
| 4        | Low    | Nice to have, no rush                            |

## Reporting Security Issues

**Do not open a public issue for security vulnerabilities.** Please see [SECURITY.md](SECURITY.md) for instructions on responsible disclosure.

## Questions?

If you have questions about contributing, feel free to:

- Open a [Discussion](https://github.com/EliasMarine/NetTap/discussions) on GitHub
- Join our [Discord community](https://discord.gg/nettap)

Thank you for helping make NetTap better!
