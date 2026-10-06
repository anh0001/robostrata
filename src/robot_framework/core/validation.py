"""Validation, grounding and compatibility check (architecture note §5).

Every failure becomes a structured reason ``{code, node_id, detail}``; all reasons are collected
before raising ``PlanRejectedError``. Preflight does **not** evaluate future-step preconditions
against the current world, and capability checks use *structural* availability only.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from robot_framework.core.errors import PlanRejectedError
from robot_framework.core.interfaces import Executive
from robot_framework.spec import (
    NATIVE_KINDS,
    LoopNode,
    PlanProposal,
    PortSpec,
    ProviderManifest,
    RejectionReason,
    RobotManifest,
    SkillContract,
    SkillNode,
    TaskGraph,
    WaitEventNode,
    iter_nodes,
)

if TYPE_CHECKING:
    from robot_framework.core.context import FrameworkContext

UNRESOLVED_PREFIX = "$"

_TYPE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "string": lambda value: isinstance(value, str),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "entity": lambda value: isinstance(value, str) and bool(value),
    "pose": lambda value: isinstance(value, dict),
    "object": lambda value: isinstance(value, dict),
}


@dataclass(frozen=True)
class ValidatedPlan:
    proposal: PlanProposal
    skill_refs: tuple[str, ...]
    resource_scope: frozenset[str]


def provider_fits(
    manifest: ProviderManifest, contract: SkillContract, robot: RobotManifest
) -> bool:
    """A provider is eligible when it implements the skill, the robot structurally has the
    hardware it needs, and it can stop at least as fast as the skill contract demands."""
    capabilities = robot.structural_capabilities()
    return (
        contract.skill_id in manifest.implements
        and all(req.capability in capabilities for req in manifest.hardware)
        and manifest.cancellation.max_stop_time_s <= contract.cancellation.max_stop_time_s
    )


def _reason(code: str, detail: str, node_id: str | None = None) -> RejectionReason:
    return RejectionReason(code=code, node_id=node_id, detail=detail)


class PlanValidator:
    def __init__(
        self, ctx: FrameworkContext, *, native_validators: frozenset[str] = frozenset()
    ) -> None:
        self._ctx = ctx
        self._native_validators = native_validators

    def validate(
        self, proposal: PlanProposal, robot: RobotManifest, executive: Executive
    ) -> ValidatedPlan:
        reasons = (
            *self._check_executive(proposal, executive),
            *self._check_native(proposal),
            *(
                self._check_graph(proposal.task_graph, robot, executive)
                if proposal.task_graph is not None
                else ()
            ),
        )
        if reasons:
            codes = sorted({reason.code for reason in reasons})
            raise PlanRejectedError(
                f"plan {proposal.proposal_id} rejected: {', '.join(codes)}",
                details={"reasons": [reason.model_dump(mode="json") for reason in reasons]},
            )
        skill_ids = self._skill_ids(proposal.task_graph)
        scope = frozenset(
            resource
            for skill_id in skill_ids
            for resource in self._ctx.skills.get(skill_id).required_resources
        )
        return ValidatedPlan(proposal=proposal, skill_refs=skill_ids, resource_scope=scope)

    def _check_executive(
        self, proposal: PlanProposal, executive: Executive
    ) -> tuple[RejectionReason, ...]:
        reasons: tuple[RejectionReason, ...] = ()
        if proposal.kind not in executive.supported_kinds:
            reasons = (
                _reason(
                    "unsupported_artifact_kind",
                    f"executive '{executive.executive_id}' does not accept "
                    f"'{proposal.kind.value}' artifacts",
                ),
            )
        pinned = proposal.executive_requirements.executive_id
        if pinned is not None and pinned != executive.executive_id:
            reasons = (
                *reasons,
                _reason(
                    "executive_mismatch",
                    f"plan requires executive '{pinned}', profile selects "
                    f"'{executive.executive_id}'",
                ),
            )
        return reasons

    def _check_native(self, proposal: PlanProposal) -> tuple[RejectionReason, ...]:
        if proposal.kind not in NATIVE_KINDS or proposal.native is None:
            return ()
        if proposal.native.validator_id in self._native_validators:
            return ()
        return (
            _reason(
                "native_validator_missing",
                f"no validator '{proposal.native.validator_id}' is registered for "
                f"'{proposal.native.format}' artifacts",
            ),
        )

    def _check_graph(
        self, graph: TaskGraph, robot: RobotManifest, executive: Executive
    ) -> tuple[RejectionReason, ...]:
        node_reasons = tuple(
            reason
            for node in iter_nodes(graph.root)
            for reason in self._check_node(node, executive)
        )
        known = tuple(sid for sid in self._skill_ids(graph) if sid in self._ctx.skills)
        contracts = tuple(self._ctx.skills.get(skill_id) for skill_id in known)
        return (
            *node_reasons,
            *self._check_robot(contracts, robot),
            *self._check_execution(contracts, robot),
        )

    def _check_node(self, node: Any, executive: Executive) -> Iterator[RejectionReason]:
        if node.kind not in executive.supported_node_kinds:
            yield _reason(
                "unsupported_node_kind",
                f"executive '{executive.executive_id}' cannot run '{node.kind}' nodes",
                node.node_id,
            )
        if isinstance(node, LoopNode) and node.max_iterations < 1:
            yield _reason("unbounded_loop", "loop needs max_iterations >= 1", node.node_id)
        if isinstance(node, WaitEventNode) and node.timeout_s <= 0:
            yield _reason("unbounded_wait", "wait_event needs timeout_s > 0", node.node_id)
        if isinstance(node, SkillNode):
            yield from self._check_skill_node(node)

    def _check_skill_node(self, node: SkillNode) -> Iterator[RejectionReason]:
        if node.skill_id not in self._ctx.skills:
            yield _reason(
                "unknown_skill", f"skill '{node.skill_id}' is not registered", node.node_id
            )
            return
        contract = self._ctx.skills.get(node.skill_id)
        yield from _check_params(node, contract)
        for port in sorted(set(node.bindings) - {p.name for p in contract.outputs}):
            yield _reason(
                "invalid_binding",
                f"'{port}' is not an output port of '{contract.skill_id}'",
                node.node_id,
            )

    def _check_robot(
        self, contracts: tuple[SkillContract, ...], robot: RobotManifest
    ) -> tuple[RejectionReason, ...]:
        capabilities = robot.structural_capabilities()
        resources = robot.resource_ids()
        missing_caps = sorted(
            {c for k in contracts for c in k.required_capabilities} - capabilities
        )
        missing_res = sorted({r for k in contracts for r in k.required_resources} - resources)
        return (
            *(
                _reason("missing_capability", f"robot '{robot.robot_id}' lacks capability '{cap}'")
                for cap in missing_caps
            ),
            *(
                _reason("unknown_resource", f"robot '{robot.robot_id}' has no resource '{res}'")
                for res in missing_res
            ),
        )

    def _check_execution(
        self, contracts: tuple[SkillContract, ...], robot: RobotManifest
    ) -> tuple[RejectionReason, ...]:
        providers = tuple(p.manifest for p in self._ctx.providers.items().values())
        no_provider = tuple(
            _reason("no_provider", f"no eligible provider implements '{contract.skill_id}'")
            for contract in contracts
            if not any(provider_fits(m, contract, robot) for m in providers)
        )
        no_verifier = tuple(
            _reason(
                "unknown_verifier",
                f"verifier '{contract.verification.verifier_id}' for '{contract.skill_id}' "
                "is not registered",
            )
            for contract in contracts
            if contract.verification.required
            and contract.verification.verifier_id not in self._ctx.verifiers
        )
        return (*no_provider, *no_verifier)

    @staticmethod
    def _skill_ids(graph: TaskGraph | None) -> tuple[str, ...]:
        if graph is None:
            return ()
        ids = (node.skill_id for node in iter_nodes(graph.root) if isinstance(node, SkillNode))
        return tuple(dict.fromkeys(ids))


def _check_params(node: SkillNode, contract: SkillContract) -> Iterator[RejectionReason]:
    ports = {port.name: port for port in contract.inputs}
    for name in sorted(set(node.params) - set(ports)):
        yield _reason("invalid_parameter", f"unknown parameter '{name}'", node.node_id)
    for port in contract.inputs:
        if port.name not in node.params:
            if port.required or port.name in contract.referenced_ports():
                yield _reason("invalid_parameter", f"missing parameter '{port.name}'", node.node_id)
            continue
        problem = param_problem(port, node.params[port.name])
        if problem is not None:
            yield _reason("invalid_parameter", problem, node.node_id)


def param_problem(port: PortSpec, value: Any) -> str | None:
    """Why ``value`` does not satisfy ``port`` (unresolved reference or wrong type), or None."""
    if isinstance(value, str) and value.startswith(UNRESOLVED_PREFIX):
        return f"parameter '{port.name}' has unresolved reference '{value}'"
    if not _TYPE_CHECKS[port.type](value):
        return f"parameter '{port.name}' expects {port.type}, got {type(value).__name__}"
    return None
