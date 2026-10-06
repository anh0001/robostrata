import pytest

from builders import (
    add_move_skill,
    graph_proposal,
    move_contract,
    skill_node,
    without_capability,
)
from robot_framework.core.errors import PlanRejectedError
from robot_framework.core.mission_supervisor import MissionSupervisor
from robot_framework.core.validation import PlanValidator, provider_fits
from robot_framework.spec import (
    ExecutiveRequirements,
    NativeArtifact,
    ParallelNode,
    PlanArtifactKind,
    PlanProposal,
    PolicyGoal,
    PortSpec,
    SequenceNode,
)
from robot_framework.spec.provider import ProviderManifest


def validate(ctx, proposal, robot=None, **kwargs):
    validator = PlanValidator(ctx, **kwargs)
    return validator.validate(proposal, robot or ctx.robot, ctx.executives.get("sequential"))


def reasons_of(exc_info):
    return exc_info.value.details["reasons"]


def codes_of(exc_info):
    return {reason["code"] for reason in reasons_of(exc_info)}


def native_proposal(kind=PlanArtifactKind.TEMPORAL_PLAN):
    return PlanProposal(
        proposal_id="p",
        kind=kind,
        planner_id="plansys2",
        native=NativeArtifact(format="pddl_plan", content="(move a b)", validator_id="pddl_check"),
        world_snapshot_id="ws",
    )


async def test_validator_accepts_the_example_plan(ctx, goal):
    validated = await MissionSupervisor(ctx).prepare(goal)

    assert validated.skill_refs == (
        "navigation.go_to",
        "perception.observe_target",
        "manipulation.pick",
        "manipulation.place",
    )
    assert validated.resource_scope == frozenset({"base", "arm_0", "gripper_0"})


def test_validator_rejects_unknown_skill(ctx):
    proposal = graph_proposal(skill_node("manipulation.fly", node_id="fly", object="bottle"))

    with pytest.raises(PlanRejectedError) as exc_info:
        validate(ctx, proposal)

    assert reasons_of(exc_info) == [
        {
            "code": "unknown_skill",
            "node_id": "fly",
            "detail": "skill 'manipulation.fly' is not registered",
        }
    ]


def test_validator_rejects_missing_capability(ctx):
    robot = without_capability(ctx.robot, "manipulation.single_arm")
    proposal = graph_proposal(skill_node("manipulation.pick", object="bottle_17"))

    with pytest.raises(PlanRejectedError) as exc_info:
        validate(ctx, proposal, robot=robot)

    assert {"missing_capability", "no_provider"} <= codes_of(exc_info)
    assert any("manipulation.single_arm" in r["detail"] for r in reasons_of(exc_info))


def test_validator_rejects_unknown_resource(ctx):
    components = tuple(
        c.model_copy(update={"resources": ()}) if c.component_id == "gripper_0" else c
        for c in ctx.robot.components
    )
    robot = ctx.robot.model_copy(update={"components": components})
    proposal = graph_proposal(skill_node("manipulation.pick", object="bottle_17"))

    with pytest.raises(PlanRejectedError) as exc_info:
        validate(ctx, proposal, robot=robot)

    assert codes_of(exc_info) == {"unknown_resource"}


def test_validator_rejects_temporal_artifact_for_sequential_executive(ctx):
    with pytest.raises(PlanRejectedError) as exc_info:
        validate(ctx, native_proposal())

    assert codes_of(exc_info) == {"unsupported_artifact_kind", "native_validator_missing"}


def test_registered_native_validator_does_not_make_the_executive_compatible(ctx):
    with pytest.raises(PlanRejectedError) as exc_info:
        validate(ctx, native_proposal(), native_validators=frozenset({"pddl_check"}))

    assert codes_of(exc_info) == {"unsupported_artifact_kind"}


def test_validator_rejects_policy_goal_for_sequential_executive(ctx):
    proposal = PlanProposal(
        proposal_id="p",
        kind=PlanArtifactKind.POLICY_GOAL,
        planner_id="vla",
        policy_goal=PolicyGoal(instruction="pick", horizon_s=3.0),
        world_snapshot_id="ws",
    )

    with pytest.raises(PlanRejectedError) as exc_info:
        validate(ctx, proposal)

    assert codes_of(exc_info) == {"unsupported_artifact_kind"}


def test_validator_rejects_bad_parameters(ctx):
    root = SequenceNode(
        node_id="s",
        children=(
            skill_node("manipulation.pick", node_id="missing"),
            skill_node("manipulation.pick", node_id="mistyped", object=17),
            skill_node("manipulation.pick", node_id="unknown", object="b", speed=2),
            skill_node("manipulation.pick", node_id="unresolved", object="$goal.object"),
        ),
    )

    with pytest.raises(PlanRejectedError) as exc_info:
        validate(ctx, graph_proposal(root))

    by_node = {r["node_id"]: r["detail"] for r in reasons_of(exc_info)}
    assert codes_of(exc_info) == {"invalid_parameter"}
    assert "missing parameter 'object'" in by_node["missing"]
    assert "expects entity, got int" in by_node["mistyped"]
    assert "unknown parameter 'speed'" in by_node["unknown"]
    assert "unresolved reference" in by_node["unresolved"]


@pytest.mark.parametrize(
    ("port_type", "good", "bad"),
    [
        ("string", "text", 3),
        ("number", 1.5, True),
        ("boolean", False, "no"),
        ("pose", {"x": 1.0}, [1.0]),
        ("object", {"k": "v"}, "v"),
    ],
)
def test_validator_checks_every_port_type(ctx, port_type, good, bad):
    contract = move_contract().model_copy(
        update={"inputs": (*move_contract().inputs, PortSpec(name="extra", type=port_type))}
    )
    add_move_skill(ctx, contract)

    assert validate(ctx, graph_proposal(skill_node("test.move", target="t", extra=good)))
    with pytest.raises(PlanRejectedError, match="invalid_parameter"):
        validate(ctx, graph_proposal(skill_node("test.move", target="t", extra=bad)))


def test_validator_rejects_skill_without_provider_or_verifier(ctx):
    ctx.skills.register("test.orphan", move_contract(skill_id="test.orphan", verifier_id="nope"))

    with pytest.raises(PlanRejectedError) as exc_info:
        validate(ctx, graph_proposal(skill_node("test.orphan", target="t")))

    assert codes_of(exc_info) == {"no_provider", "unknown_verifier"}


def test_validator_rejects_parallel_nodes_for_sequential_executive(ctx):
    root = ParallelNode(
        node_id="both",
        children=(
            skill_node("navigation.go_to", node_id="a", location="x"),
            skill_node("perception.observe_target", node_id="b", target="y"),
        ),
    )

    with pytest.raises(PlanRejectedError) as exc_info:
        validate(ctx, graph_proposal(root))

    assert codes_of(exc_info) == {"unsupported_node_kind"}


def test_validator_rejects_executive_mismatch_and_bad_bindings(ctx):
    node = skill_node("perception.observe_target", target="y").model_copy(
        update={"bindings": {"pose": "bottle_pose", "ghost": "x"}}
    )
    proposal = graph_proposal(node).model_copy(
        update={"executive_requirements": ExecutiveRequirements(executive_id="btcpp")}
    )

    with pytest.raises(PlanRejectedError) as exc_info:
        validate(ctx, proposal)

    assert codes_of(exc_info) == {"executive_mismatch", "invalid_binding"}


def test_provider_fits_requires_a_fast_enough_stop(ctx):
    contract = move_contract(max_stop_time_s=0.05)
    slow = ProviderManifest.model_validate(
        {
            **ctx.providers.get("mock.pick").manifest.model_dump(),
            "implements": ["test.move"],
            "cancellation": {"max_stop_time_s": 1.0},
        }
    )

    assert not provider_fits(slow, contract, ctx.robot)
    assert provider_fits(slow, move_contract(max_stop_time_s=1.0), ctx.robot)
