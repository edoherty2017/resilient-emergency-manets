from __future__ import annotations

from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]


def _locked_versions() -> dict[str, str]:
    locked = {}
    for raw_line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, version = line.split("==", 1)
        locked[canonicalize_name(name)] = version
    return locked


def _direct_requirements() -> list[Requirement]:
    requirements = []
    for raw_line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-c "):
            continue
        requirements.append(Requirement(line))
    return requirements


def test_lock_covers_exact_installed_runtime_dependency_closure() -> None:
    locked = _locked_versions()
    direct = _direct_requirements()
    pending = [canonicalize_name(requirement.name) for requirement in direct]
    closure: set[str] = set()

    while pending:
        name = pending.pop()
        if name in closure:
            continue
        closure.add(name)
        distribution = metadata.distribution(name)
        for raw_requirement in distribution.requires or ():
            requirement = Requirement(raw_requirement)
            if requirement.marker is None or requirement.marker.evaluate():
                pending.append(canonicalize_name(requirement.name))

    assert set(locked) == closure
    for name, version in locked.items():
        assert metadata.version(name) == version
    for requirement in direct:
        name = canonicalize_name(requirement.name)
        assert requirement.specifier.contains(locked[name], prereleases=True)
