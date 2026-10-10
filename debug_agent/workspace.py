"""Scratch workspace where mitigations are applied and validated.

The scenario sources are never modified. Each validation attempt starts from
a fresh copy, applies only the current plan, and keeps a unified diff.
"""

from __future__ import annotations

import difflib
import json
import shutil
from pathlib import Path
from typing import Any


class ApplyError(RuntimeError):
    pass


def prepare_workspace(scenario_dir: Path, run_dir: Path) -> Path:
    workspace = run_dir / "workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    for name in ("src", "tests"):
        source = scenario_dir / name
        if source.exists():
            shutil.copytree(source, workspace / name)
    fmf = scenario_dir / ".fmf"
    if fmf.exists():
        shutil.copytree(fmf, workspace / ".fmf")
    return workspace


def apply_actions(workspace: Path, actions: list[dict[str, Any]]) -> list[str]:
    """Apply plan actions. Return human-readable notes. Raise ``ApplyError`` on a bad edit."""
    notes: list[str] = []
    for action in actions:
        kind = action["kind"]
        payload = action.get("payload") or {}
        if kind == "flag":
            _apply_flag(workspace, payload)
            notes.append(f"Recorded flag ramp for {payload.get('flag')} to {payload.get('to')}.")
        elif kind == "edit":
            _apply_edit(workspace, payload)
            notes.append(f"Edited {payload.get('path')}.")
        elif kind == "rollback":
            notes.append(
                "Rollback "
                f"{payload.get('service')} to {payload.get('to_version')} was recorded "
                "and not executed. No deploy-write connector is configured."
            )
        else:
            raise ApplyError(f"unsupported action {kind}")
    return notes


def unified_diff(scenario_dir: Path, workspace: Path) -> str:
    """Diff scenario sources against the scratch workspace, plus a flag proposal file."""
    chunks: list[str] = []
    original = scenario_dir / "src"
    updated = workspace / "src"
    paths: set[Path] = set()
    if original.exists():
        paths.update(path.relative_to(original) for path in original.rglob("*") if path.is_file())
    if updated.exists():
        paths.update(path.relative_to(updated) for path in updated.rglob("*") if path.is_file())
    for relative in sorted(paths):
        before = (original / relative).read_text(encoding="utf-8") if (original / relative).exists() else ""
        after = (updated / relative).read_text(encoding="utf-8") if (updated / relative).exists() else ""
        if before == after:
            continue
        display = Path("src") / relative
        chunks.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{display.as_posix()}",
                tofile=f"b/{display.as_posix()}",
            )
        )
    proposal = workspace / "proposed_flags.json"
    if proposal.exists():
        after = proposal.read_text(encoding="utf-8")
        chunks.extend(
            difflib.unified_diff(
                [],
                after.splitlines(keepends=True),
                fromfile="/dev/null",
                tofile="b/proposed_flags.json",
            )
        )
    return "".join(chunks)


def _apply_flag(workspace: Path, payload: dict[str, Any]) -> None:
    flag = payload.get("flag")
    if not flag or "to" not in payload:
        raise ApplyError("flag action requires 'flag' and 'to'")
    path = workspace / "proposed_flags.json"
    existing: dict[str, Any] = {}
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
    changes = list(existing.get("changes") or [])
    changes.append({"flag": flag, "from": payload.get("from"), "to": payload.get("to")})
    path.write_text(json.dumps({"changes": changes}, indent=2) + "\n", encoding="utf-8")


def _apply_edit(workspace: Path, payload: dict[str, Any]) -> None:
    relative = payload.get("path")
    old = payload.get("old")
    new = payload.get("new")
    if not isinstance(relative, str) or not isinstance(old, str) or not isinstance(new, str):
        raise ApplyError("edit action requires string path, old, and new")
    if relative.startswith("/") or ".." in Path(relative).parts:
        raise ApplyError(f"edit path escapes the workspace: {relative}")
    path = workspace / relative
    if not path.is_file():
        raise ApplyError(f"edit target does not exist: {relative}")
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found != 1:
        raise ApplyError(f"{relative}: expected the old text once, found it {found} times")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
