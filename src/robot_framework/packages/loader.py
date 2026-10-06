"""YAML package loaders: robot packages, task packs, goals and deployment profiles → contracts.

Only ``yaml.safe_load`` is used. Validation errors become ``ContractValidationError`` with the file
and the pydantic error list in ``details``.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from robot_framework.core.errors import ContractValidationError
from robot_framework.spec import (
    DeploymentProfile,
    GoalSpec,
    RobotManifest,
    SkillContract,
    TaskDefinition,
)

ROOT_ENV = "ROBOT_FRAMEWORK_ROOT"
ROBOT_PACKAGES_DIR = "robot_packages"
TASK_PACKS_DIR = "task_packs"
MANIFEST_FILE = "manifest.yaml"

M = TypeVar("M", bound=BaseModel)


@dataclass(frozen=True)
class TaskPack:
    name: str
    directory: Path
    tasks: Mapping[str, TaskDefinition]
    skills: tuple[SkillContract, ...]


def read_yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractValidationError(
            f"cannot read {path}: {exc.strerror}", details={"file": str(path)}
        ) from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ContractValidationError(
            f"invalid YAML in {path}", details={"file": str(path), "error": str(exc)}
        ) from exc


def load_contract(path: Path, model: type[M]) -> M:
    data = read_yaml(path)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ContractValidationError(
            f"{path.name} is not a valid {model.__name__} ({exc.error_count()} error(s))",
            details={
                "file": str(path),
                "errors": exc.errors(include_url=False, include_context=False),
            },
        ) from exc


def resolve_root(profile_path: Path, override: Path | None = None) -> Path:
    """Package root: explicit override, else ``$ROBOT_FRAMEWORK_ROOT``, else the profile's
    grandparent directory (``<root>/deployment_profiles/<profile>.yaml``)."""
    if override is not None:
        return override
    env = os.environ.get(ROOT_ENV)
    if env:
        return Path(env)
    return profile_path.resolve().parent.parent


def load_profile(path: Path) -> DeploymentProfile:
    return load_contract(path, DeploymentProfile)


def load_goal(path: Path) -> GoalSpec:
    return load_contract(path, GoalSpec)


def load_robot_manifest(root: Path, robot_pack: str) -> RobotManifest:
    return load_contract(root / ROBOT_PACKAGES_DIR / robot_pack / MANIFEST_FILE, RobotManifest)


def load_task_pack(root: Path, task_pack: str) -> TaskPack:
    directory = root / TASK_PACKS_DIR / task_pack
    if not directory.is_dir():
        raise ContractValidationError(
            f"task pack '{task_pack}' not found", details={"directory": str(directory)}
        )
    tasks = tuple(load_contract(p, TaskDefinition) for p in sorted(directory.glob("*.task.yaml")))
    task_ids = [task.task_id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ContractValidationError(
            f"duplicate task ids in pack '{task_pack}'", details={"task_ids": task_ids}
        )
    skill_files = sorted((directory / "skills").glob("*.skill.yaml"))
    skills = tuple(load_contract(p, SkillContract) for p in skill_files)
    return TaskPack(
        name=task_pack,
        directory=directory,
        tasks={task.task_id: task for task in tasks},
        skills=skills,
    )


def pack_file(pack: TaskPack, relative: str) -> Path:
    """Resolve a path inside a task pack, refusing anything that escapes the pack directory."""
    base = pack.directory.resolve()
    path = (base / relative).resolve()
    if base not in path.parents:
        raise ContractValidationError(
            f"'{relative}' escapes task pack '{pack.name}'", details={"path": relative}
        )
    return path
