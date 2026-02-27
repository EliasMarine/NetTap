# Release Process

This page documents how NetTap releases are versioned, built, and published.

---

## Versioning Scheme

NetTap uses **phase-based semantic versioning**. Development versions increment with each phase milestone:

| Milestone | Version | Tag Location |
|---|---|---|
| Phase 1 complete (Core Infrastructure) | `v0.1.0` | `develop` |
| Phase 2 complete (Storage Management) | `v0.2.0` | `develop` |
| Phase 3 complete (Onboarding UX) | `v0.3.0` | `develop` |
| Phase 4 complete (Dashboard Polish) | `v0.4.0` | `develop` |
| Phase 5 complete (Community Release) | `v1.0.0` | `main` |

### Patch Versions

Hotfixes within a phase use patch versions: `v0.1.1`, `v0.1.2`, etc.

### Pre-Release Versions

Testing releases use pre-release suffixes:

- `v1.0.0-alpha.1` --- early testing, features incomplete
- `v1.0.0-beta.1` --- feature complete, bug fixing
- `v1.0.0-rc.1` --- release candidate, final testing

---

## Branch Strategy

```
main ─────────────────────────────────────────────── v1.0.0 (final merge)
  │
  └── develop ──┬── phase-1/feature-a ──────> merge ──> tag v0.1.0
                ├── phase-2/feature-b ──────> merge ──> tag v0.2.0
                ├── phase-3/feature-c ──────> merge ──> tag v0.3.0
                ├── phase-4/feature-d ──────> merge ──> tag v0.4.0
                └── phase-5/feature-e ──────> merge ──> tag v1.0.0 on main
```

- All development happens on feature branches
- Feature branches merge to `develop` via PR
- Phase tags are applied on `develop` when all tasks for that phase are complete
- Only the final `v1.0.0` tag is applied on `main` after the develop-to-main merge

---

## Release Steps

### Tagging a Phase Milestone

When all tasks for a phase are complete and merged to `develop`:

```bash
git checkout develop
git pull origin develop

# Create annotated tag
git tag -a v0.X.0 -m "Phase X: Description of milestone"

# Push the tag
git push origin v0.X.0
```

### Creating a GitHub Release

1. Go to [Releases](https://github.com/EliasMarine/NetTap/releases) on GitHub
2. Click "Draft a new release"
3. Select the tag (e.g., `v0.3.0`)
4. Write release notes summarizing:
   - New features
   - Bug fixes
   - Breaking changes (if any)
   - Upgrade instructions
5. Publish the release

### Docker Image Publishing

Docker images are built and tagged for each release:

```bash
# Build images
docker compose -f docker/docker-compose.yml build

# Tag with version
docker tag nettap/storage-daemon:latest nettap/storage-daemon:v0.3.0
docker tag nettap/web:latest nettap/web:v0.3.0

# Push to registry (if applicable)
docker push nettap/storage-daemon:v0.3.0
docker push nettap/web:v0.3.0
```

---

## Changelog Generation

NetTap uses [git-cliff](https://git-cliff.org/) to generate changelogs from conventional commit messages:

```bash
# Generate changelog for all versions
git cliff -o CHANGELOG.md

# Generate changelog for a specific version range
git cliff v0.2.0..v0.3.0

# Preview changelog without writing
git cliff --unreleased
```

The conventional commit types map to changelog sections:

| Commit Type | Changelog Section |
|---|---|
| `feat` | Features |
| `fix` | Bug Fixes |
| `perf` | Performance |
| `docs` | Documentation |
| `refactor` | Refactoring |
| `test` | Testing |
| `chore`, `ci` | Miscellaneous |

---

## CI/CD Pipeline

GitHub Actions automates the build and test pipeline:

### On Every Push / PR

1. **Lint:** ShellCheck, Ruff, ESLint
2. **Test:** pytest, Vitest, svelte-check
3. **Build:** Docker images compile successfully

### On Tag Push

1. All of the above
2. **Docker build and push** to container registry
3. **GitHub Release** draft creation

---

## Dependency Pinning

### Malcolm Stack

Malcolm container images are pinned to a tested release tag in `docker-compose.yml`:

```yaml
x-malcolm-tag: &malcolm-tag "26.02.0"
```

This prevents upstream breaking changes. The tag is only updated after the new Malcolm release has been tested with NetTap.

### Python Dependencies

Python dependencies are pinned in `daemon/requirements.txt` with specific versions.

### Node.js Dependencies

Node.js dependencies are managed via `web/package.json` with a lockfile (`package-lock.json`) for reproducible builds.
