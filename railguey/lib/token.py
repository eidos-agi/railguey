"""Token discovery from workspace .env files."""

from collections import Counter
from pathlib import Path


def _scan_sibling_tokens(workspace_parent: Path) -> tuple[str | None, list[Path]]:
    """Walk the parent of a workspace looking for sibling repos that already
    carry a project-scoped RAILWAY_TOKEN. Returns the most common value
    (with sources) if it appears in ≥2 siblings; otherwise (None, []).

    The ≥2 frequency guard is the safety rail — a personal user-scoped
    token misfiled in a single repo shouldn't be silently propagated.
    Project-scoped tokens get duplicated across every repo in the project
    by convention, so they always satisfy the threshold.
    """
    counts: Counter[str] = Counter()
    sources: dict[str, list[Path]] = {}

    if not workspace_parent.is_dir():
        return None, []

    for entry in sorted(workspace_parent.iterdir()):
        if not entry.is_dir():
            continue
        for fname in (".env.local", ".env"):
            envfile = entry / fname
            if not envfile.is_file():
                continue
            try:
                body = envfile.read_text(encoding="utf-8")
            except OSError:
                break
            for raw in body.splitlines():
                line = raw.strip()
                if not line.startswith("RAILWAY_TOKEN="):
                    continue
                value = line.split("=", 1)[1].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                if value:
                    counts[value] += 1
                    sources.setdefault(value, []).append(envfile)
                break
            break  # first matching env file per sibling is enough

    if not counts:
        return None, []
    value, freq = counts.most_common(1)[0]
    if freq < 2:
        return None, []
    return value, sources[value]


def _write_token_to_workspace(workspace: Path, value: str, sources: list[Path]) -> None:
    """Append RAILWAY_TOKEN to workspace/.env.local with a provenance comment."""
    target = workspace / ".env.local"
    provenance = ", ".join(p.parent.name for p in sources)
    block = (
        f"\n# Auto-discovered from {len(sources)} sibling repo(s): {provenance}\n"
        f"# Written by railguey's _load_project_token sibling-discovery fallback.\n"
        f"RAILWAY_TOKEN={value}\n"
    )
    with target.open("a", encoding="utf-8") as fh:
        fh.write(block)


def _load_project_token(workspace: str) -> str:
    """Resolve a PROJECT-scoped Railway token from workspace .env files.

    railguey is intentionally workspace-scoped: the CLI reads the token from
    the workspace it was asked to operate on instead of consulting global
    account state. That keeps CI and agents deterministic.

    When the workspace's own .env.local is empty, fall back to walking the
    parent directory for sibling repos that already carry the project
    token. Project tokens are duplicated across every repo in a project by
    convention; a fresh workspace can self-bootstrap from that convention.
    """
    ws = Path(workspace).expanduser().resolve()
    for filename in (".env.local", ".env"):
        envfile = ws / filename
        if not envfile.is_file():
            continue
        for line in envfile.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("RAILWAY_TOKEN="):
                value = stripped.split("=", 1)[1].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                if value:
                    return value

    # Fallback: scan sibling repos. If ≥2 share the same RAILWAY_TOKEN value,
    # write it into this workspace's .env.local and return it. This is the
    # AI-friendly path — a fresh workspace inherits the project's token
    # without an interactive `railguey login`.
    sibling_value, sources = _scan_sibling_tokens(ws.parent)
    if sibling_value:
        _write_token_to_workspace(ws, sibling_value, sources)
        return sibling_value

    raise ValueError(
        f"No project-scoped Railway token found in {ws}/.env.local.\n"
        f"\n"
        f"Recovery options:\n"
        f"  1. AI agent: place RAILWAY_TOKEN=<value> in another sibling repo "
        f"under {ws.parent}/, then re-run any railguey verb here. The "
        f"sibling-discovery fallback will auto-write the token to this "
        f"workspace's .env.local (requires the same value in ≥2 siblings "
        f"as the safety threshold).\n"
        f"  2. Human: run `railguey login {ws}` to bootstrap interactively "
        f"via browser + Tk popup. Paste a project token from the Railway "
        f"dashboard; railguey validates it against Railway's GraphQL "
        f"before writing.\n"
        f"  3. CI environment: set the RAILWAY_TOKEN env var explicitly "
        f"(railguey reads it from os.environ as a final fallback in some "
        f"contexts; check the calling verb's docs)."
    )


def _load_token(workspace: str) -> str:
    """Resolve a Railway token from workspace/.env.local or workspace/.env."""
    return _load_project_token(workspace)
