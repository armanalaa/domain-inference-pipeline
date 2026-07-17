"""Shared path helpers for DomainMiner command-line scripts."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATALAKES_ROOT = PROJECT_ROOT / "Datalakes"


def resolve_dataset_dir(dataset_dir: str | Path | None) -> Path:
    """Resolve a dataset argument to an absolute dataset folder.

    Plain dataset names are resolved under Datalakes/ by default. Explicit
    relative paths such as Datalakes/Sakila and absolute paths are preserved.
    """
    if dataset_dir is None:
        return Path.cwd().resolve()

    raw = Path(dataset_dir)
    if raw.is_absolute():
        return raw.resolve()

    cwd_candidate = (Path.cwd() / raw).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    datalake_candidate = (DATALAKES_ROOT / raw).resolve()
    if datalake_candidate.exists() or DATALAKES_ROOT.exists():
        return datalake_candidate

    return cwd_candidate


def dataset_display_name(dataset_dir: str | Path | None, resolved: Path) -> str:
    """Return a concise dataset name for reports."""
    if dataset_dir is None:
        return resolved.name
    raw = Path(dataset_dir)
    return raw.name if raw.name else resolved.name
