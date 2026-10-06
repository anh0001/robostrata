"""Robot manifest: a component graph with resources and capability bindings.

The robot is a DAG of components (bases, arms, grippers, sensors, tools), not a fixed
base+arm+gripper template.
"""

from typing import Literal

from pydantic import Field, model_validator

from robot_framework.spec._base import ContractModel, Identifier, ValueModel


class ResourceDecl(ValueModel):
    resource_id: Identifier
    kind: Literal["actuator", "sensor", "workspace", "tool"] = "actuator"


class ComponentNode(ValueModel):
    component_id: Identifier
    type: str = Field(min_length=1)
    resources: tuple[ResourceDecl, ...] = ()
    interfaces: tuple[str, ...] = ()


class ComponentEdge(ValueModel):
    parent: Identifier
    child: Identifier
    joint: str | None = None


class CapabilityBinding(ValueModel):
    """``structural`` capabilities exist in hardware; dynamic availability is a runtime check."""

    capability: Identifier
    components: tuple[Identifier, ...] = Field(min_length=1)
    structural: bool = True


def _has_cycle(nodes: frozenset[str], edges: tuple[ComponentEdge, ...]) -> bool:
    children = {node: tuple(e.child for e in edges if e.parent == node) for node in nodes}
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str) -> bool:
        if node in done:
            return False
        if node in visiting:
            return True
        visiting.add(node)
        cyclic = any(visit(child) for child in children[node])
        visiting.discard(node)
        done.add(node)
        return cyclic

    return any(visit(node) for node in sorted(nodes))


class RobotManifest(ContractModel):
    robot_id: Identifier
    components: tuple[ComponentNode, ...] = Field(min_length=1)
    edges: tuple[ComponentEdge, ...] = ()
    capabilities: tuple[CapabilityBinding, ...] = ()
    calibration_ref: str | None = None
    safety_ref: str | None = None
    description_ref: str | None = None

    @model_validator(mode="after")
    def _check_graph(self) -> "RobotManifest":
        ids = [component.component_id for component in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate component ids in robot {self.robot_id}")
        known = frozenset(ids)
        dangling = sorted(
            {end for edge in self.edges for end in (edge.parent, edge.child) if end not in known}
        )
        if dangling:
            raise ValueError(f"edges reference unknown components: {dangling}")
        if _has_cycle(known, self.edges):
            raise ValueError(f"component graph of robot {self.robot_id} contains a cycle")
        resources = [r.resource_id for c in self.components for r in c.resources]
        duplicates = sorted({r for r in resources if resources.count(r) > 1})
        if duplicates:
            raise ValueError(f"duplicate resource ids across components: {duplicates}")
        unbound = sorted(
            {c for binding in self.capabilities for c in binding.components if c not in known}
        )
        if unbound:
            raise ValueError(f"capability bindings reference unknown components: {unbound}")
        return self

    def resource_ids(self) -> frozenset[str]:
        return frozenset(r.resource_id for c in self.components for r in c.resources)

    def structural_capabilities(self) -> frozenset[str]:
        return frozenset(b.capability for b in self.capabilities if b.structural)
