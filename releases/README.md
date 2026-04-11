# Release Notes Index

Append-only narrative release notes for `fs-mcp`.

## Authoring

- **One file per release.** Name: `vX.Y.Z.md`. No overwrites.
- **Audience:** human first, then agents picking up context six months later.
- **Structure:** TL;DR → Why → Highlights table → Mermaid diagram (when there's a flow) → Before/After example → Config → Upgrade notes → Files changed.
- **Voice:** pitch, not changelog. If a line could be a commit subject, cut it.
- **Diagrams:** Mermaid only — GitHub renders it natively in release bodies.
- **Promotion boundary:** anything that lands in `releases/` is world-readable. Private reasoning belongs in `gsd-lite/` (gitignored).

## Publishing

The `.github/workflows/release.yaml` workflow reads `releases/${{ github.ref_name }}.md` via `gh release create --notes-file` when a tag is pushed. If the file is missing, the workflow fails loudly — no `--generate-notes` fallback, because empty stubs defeat the point.

## History

Previously tracked at `CHANGELOG.md` — retired 2026-04-11 in favor of per-file narrative entries under `releases/`. Earlier releases (v0.1.0 → v1.47.0) predate this pattern; see [GitHub Releases](https://github.com/luutuankiet/fs-mcp/releases) for the auto-generated changelogs that shipped with those tags.

## Index

| Version | Date | Theme |
|---|---|---|
| [v1.47.1](./v1.47.1.md) | 2026-04-11 | Release infra migration to Pattern C (narrative per-file) |
