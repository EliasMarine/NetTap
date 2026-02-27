# Contributing

Thank you for your interest in contributing to NetTap. This page provides a summary of the contribution workflow. For full details, see the [CONTRIBUTING.md](https://github.com/EliasMarine/NetTap/blob/develop/CONTRIBUTING.md) file in the repository.

---

## Quick Start

1. **Fork** the repository on GitHub
2. **Clone** your fork:
   ```bash
   git clone https://github.com/<your-username>/NetTap.git
   cd NetTap
   ```
3. **Add upstream remote:**
   ```bash
   git remote add upstream https://github.com/EliasMarine/NetTap.git
   ```
4. **Create a feature branch** from `develop`:
   ```bash
   git checkout develop
   git pull upstream develop
   git checkout -b phase-N/your-feature
   ```
5. **Make your changes**, commit, and push
6. **Open a Pull Request** targeting `develop`

---

## Branch Model

| Branch | Purpose |
|---|---|
| `main` | Protected. Only receives merges at major releases. Never push directly. |
| `develop` | Integration branch. All feature branches merge here via PR. |
| `phase-N/description` | Feature branches. All work happens here. |
| `infra/description` | Cross-cutting infrastructure work. |
| `chore/description` | Maintenance tasks. |

---

## Commit Convention

This project uses [Conventional Commits](https://www.conventionalcommits.org/). Every commit must follow this format:

```
type(scope): short description
```

**Types:** `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `perf`, `style`

**Examples:**

```
feat(bridge): add netplan persistence for br0
fix(daemon): handle OpenSearch connection timeout
test(storage): add coverage for disk threshold logic
docs(readme): update architecture diagram
chore(docker): pin Malcolm images to v26.02.0
```

Rules:

- Use imperative mood ("add" not "added")
- No period at the end of the subject line
- Keep subject under 72 characters
- One logical change per commit

---

## Pull Request Process

1. **Target `develop`** --- never `main`
2. Ensure your branch is up to date with `develop`
3. **All CI checks must pass** before review
4. Fill out the PR template completely
5. Request a review from `@EliasMarine`
6. Address review feedback with new commits (do not force-push during review)
7. After merge, delete your feature branch

### PR Size

- Keep PRs under ~400 lines of diff when possible
- Break large changes into smaller, reviewable PRs
- Each PR should represent one logical unit of work

---

## Code Style

### Python (daemon)

- Linter/formatter: [Ruff](https://docs.astral.sh/ruff/)
- Follow PEP 8
- Type hints for function signatures
- Google-style docstrings

```bash
ruff check daemon/
ruff format daemon/
```

### TypeScript / Svelte (web)

- Linter: ESLint
- Type checking: `svelte-check`
- TypeScript for all new code

```bash
cd web
npm run lint
npm run check
```

### Shell Scripts

- Linter: [ShellCheck](https://www.shellcheck.net/)
- Use `set -euo pipefail`
- Quote all variables
- Use `#!/usr/bin/env bash`

```bash
shellcheck scripts/**/*.sh
```

---

## Testing Requirements

- All existing tests must pass before submitting a PR
- New features must include tests
- Bug fixes should include a regression test

See [Testing](testing.md) for details on running the test suite.

---

## Reporting Issues

- **Bugs:** Open a [GitHub Issue](https://github.com/EliasMarine/NetTap/issues) with reproduction steps
- **Features:** Open a Discussion or Issue describing the use case
- **Security:** See [SECURITY.md](https://github.com/EliasMarine/NetTap/blob/develop/SECURITY.md) for responsible disclosure

---

## Community

- [GitHub Discussions](https://github.com/EliasMarine/NetTap/discussions)
- [Discord Community](https://discord.gg/nettap)
