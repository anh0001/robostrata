"""JSON Schema export. Schemas are generated from the models, never hand-edited."""

import json
from pathlib import Path

from robot_framework.spec._base import ContractModel
from robot_framework.spec.assessment import AssessmentReport
from robot_framework.spec.goal import GoalSpec
from robot_framework.spec.invocation import (
    ActionChunk,
    ProviderOutcome,
    SkillInvocation,
    SkillResult,
)
from robot_framework.spec.mission import MissionEvent, MissionResult
from robot_framework.spec.plan import PlanProposal
from robot_framework.spec.profile import DeploymentProfile
from robot_framework.spec.provider import ProviderManifest
from robot_framework.spec.resource import CommandAcknowledgement, CommandEnvelope, ResourceLease
from robot_framework.spec.robot import RobotManifest
from robot_framework.spec.skill import SkillContract
from robot_framework.spec.task import TaskDefinition, TaskGraph
from robot_framework.spec.world import Evidence, Fact, WorldSnapshot

CONTRACTS: tuple[type[ContractModel], ...] = (
    GoalSpec,
    TaskDefinition,
    TaskGraph,
    PlanProposal,
    SkillContract,
    ProviderManifest,
    RobotManifest,
    Fact,
    Evidence,
    WorldSnapshot,
    AssessmentReport,
    SkillInvocation,
    ProviderOutcome,
    SkillResult,
    ActionChunk,
    ResourceLease,
    CommandEnvelope,
    CommandAcknowledgement,
    MissionEvent,
    MissionResult,
    DeploymentProfile,
)


def schema_text(model: type[ContractModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


def export_schemas(out_dir: Path) -> list[Path]:
    """Write ``<ClassName>.schema.json`` for every contract; returns the written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / f"{model.__name__}.schema.json" for model in CONTRACTS]
    for path, model in zip(paths, CONTRACTS, strict=True):
        path.write_text(schema_text(model), encoding="utf-8")
    return paths
