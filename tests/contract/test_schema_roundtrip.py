import json

import jsonschema
import pytest
from pydantic import ValidationError

from robot_framework.spec import (
    ActionChunk,
    AssessmentContext,
    AssessmentReport,
    AssessmentStatus,
    CancellationSpec,
    CommandAcknowledgement,
    CommandEnvelope,
    Condition,
    ConditionalNode,
    Constraint,
    ContractModel,
    ControlMode,
    DeploymentProfile,
    Evidence,
    ExpectedEffect,
    Fact,
    FactPredicate,
    FailureDiagnosis,
    GoalSpec,
    HardwareRequirement,
    LifecycleState,
    LoopNode,
    MissionEvent,
    MissionResult,
    MissionStatus,
    NativeArtifact,
    ObservationSpace,
    ParallelNode,
    PlanArtifactKind,
    PlanProposal,
    PolicyGoal,
    PortSpec,
    ProviderKind,
    ProviderManifest,
    ProviderOutcome,
    Quantity,
    RecommendedStep,
    RejectionReason,
    ResourceLease,
    RobotManifest,
    SequenceNode,
    SkillContract,
    SkillInvocation,
    SkillNode,
    SkillResult,
    SuccessCriterion,
    TaskDefinition,
    TaskGraph,
    VerificationStatus,
    WaitEventNode,
    WorldSnapshot,
    bind_args,
)
from robot_framework.spec.export import CONTRACTS, export_schemas
from robot_framework.spec.provider import ActionSpace


def _fact() -> Fact:
    return Fact(
        predicate="holding",
        args=("robot", "bottle_17"),
        value=True,
        source="world_fact",
        observation_time=12.5,
        validity_s=5.0,
        confidence=0.9,
        revision=3,
    )


def _graph() -> TaskGraph:
    return TaskGraph(
        root=SequenceNode(
            node_id="root",
            children=(
                SkillNode(node_id="go", skill_id="navigation.go_to", params={"location": "desk"}),
                ConditionalNode(
                    node_id="maybe",
                    condition=FactPredicate(predicate="door_open", args=("door_1",)),
                    then=SkillNode(node_id="pass", skill_id="navigation.go_to"),
                    otherwise=WaitEventNode(
                        node_id="wait",
                        condition=FactPredicate(predicate="door_open", args=("door_1",)),
                        timeout_s=3.0,
                    ),
                ),
                LoopNode(
                    node_id="loop",
                    max_iterations=3,
                    until=FactPredicate(predicate="done"),
                    child=SkillNode(node_id="try", skill_id="x.y", recovery_ref="again"),
                ),
                ParallelNode(
                    node_id="both",
                    children=(
                        SkillNode(node_id="left", skill_id="x.left"),
                        SkillNode(node_id="right", skill_id="x.right"),
                    ),
                    completion="any",
                ),
            ),
        ),
        recoveries={"again": {"kind": "retry", "max_attempts": 2, "requires_reconcile": True}},
    )


def _skill_result() -> SkillResult:
    return SkillResult(
        invocation_id="inv_1",
        node_id="pick",
        skill_id="manipulation.pick",
        provider_id="mock.pick",
        provider_status="SUCCESS",
        state=LifecycleState.SUCCEEDED,
        observed_effects=(_fact(),),
        verification_status=VerificationStatus.VERIFIED,
        evidence_references=("fact:holding@rev3",),
        failure_diagnosis=FailureDiagnosis(category="other", detail="none"),
    )


def _samples() -> dict[type[ContractModel], ContractModel]:
    lease = ResourceLease(
        lease_id="lease_1",
        owner_id="inv_1",
        resources=("arm_0", "gripper_0"),
        control_mode=ControlMode.TRAJECTORY,
        epoch=2,
        expires_at_monotonic=99.5,
    )
    samples: tuple[ContractModel, ...] = (
        GoalSpec(
            goal_id="g1",
            objective="deliver_object",
            parameters={"object": "bottle_17", "count": 2, "nested": {"a": [1, 2]}},
            success_criteria=(SuccessCriterion(predicate="at", args=("bottle_17", "desk")),),
            constraints=(
                Constraint(name="max_speed", limit=Quantity(value=0.5, unit="m/s"), hard=False),
            ),
            deadline_s=60.0,
        ),
        TaskDefinition(task_id="t1", objective="deliver_object", graph=_graph()),
        _graph(),
        PlanProposal(
            proposal_id="p1",
            kind=PlanArtifactKind.TEMPORAL_PLAN,
            planner_id="plansys2",
            native=NativeArtifact(
                format="pddl_plan",
                content="0.0: (move r a b) [5.0]",
                validator_id="pddl_check",
                resource_scope=("base",),
                entry_contract={"at": "a"},
            ),
            assumptions=("static_world",),
            world_snapshot_id="ws_1",
        ),
        SkillContract(
            skill_id="manipulation.pick",
            inputs=(PortSpec(name="object", type="entity"),),
            outputs=(PortSpec(name="grasp", type="pose", required=False, unit="m"),),
            preconditions=(Condition(predicate="pose_known", args=("$object",), max_age_s=5.0),),
            hold_conditions=(Condition(predicate="estop_clear", args=("robot",)),),
            expected_effects=(ExpectedEffect(predicate="holding", args=("robot", "$object")),),
            cancellation=CancellationSpec(mode="safe_state_first", max_stop_time_s=2.0),
            required_capabilities=("manipulation.single_arm",),
            required_resources=("arm_0", "gripper_0"),
        ),
        ProviderManifest(
            provider_id="vla.pi0",
            kind=ProviderKind.POLICY,
            implements=("manipulation.pick",),
            hardware=(HardwareRequirement(capability="manipulation.single_arm"),),
            domains=("tabletop",),
            version="1.2.0",
            model_ref="hf://example/pi0",
            cancellation=CancellationSpec(max_stop_time_s=0.5),
            control_mode=ControlMode.POLICY,
            observation_space=ObservationSpace(keys=("rgb", "joint_state"), frame="base_link"),
            action_space=ActionSpace(
                control_mode=ControlMode.POSITION, dimension=7, frame="base_link", rate_hz=10.0
            ),
        ),
        RobotManifest.model_validate(
            {
                "robot_id": "r1",
                "components": [
                    {
                        "component_id": "base",
                        "type": "mobile_base",
                        "resources": [{"resource_id": "base"}],
                    },
                    {"component_id": "cam", "type": "rgbd", "interfaces": ["rgb"]},
                ],
                "edges": [{"parent": "base", "child": "cam", "joint": "mount"}],
                "capabilities": [{"capability": "perception.rgbd", "components": ["cam"]}],
                "safety_ref": "safety.yaml",
            }
        ),
        _fact(),
        Evidence(evidence_id="e1", kind="image", ref="bag://frame/12", time=12.5),
        WorldSnapshot(snapshot_id="ws_1", revision=3, time=13.0, facts=(_fact(),)),
        AssessmentReport(
            status=AssessmentStatus.UNKNOWN,
            reason="object partially occluded",
            context=AssessmentContext(
                world_snapshot_id="ws_1", robot_state_revision=3, provider_id="mock.pick"
            ),
            evidence={"pose_known": "fact@rev3"},
            applicable_constraints=("max_payload",),
            recommended_next_step=RecommendedStep(
                skill_id="perception.observe_target", params={"target": "bottle_17"}
            ),
        ),
        SkillInvocation(
            invocation_id="inv_1",
            node_id="pick",
            skill_id="manipulation.pick",
            provider_id="mock.pick",
            bound_params={"object": "bottle_17"},
            lease_id="lease_1",
            epoch=2,
            state=LifecycleState.RUNNING,
            created_at=10.0,
        ),
        ProviderOutcome(
            invocation_id="inv_1",
            status="UNKNOWN",
            diagnosis=FailureDiagnosis(category="ack_lost", evidence_refs=("log:12",)),
        ),
        _skill_result(),
        ActionChunk(actions=({"joint": [0.1, 0.2]},), horizon=8, frame="base_link", epoch=2),
        lease,
        CommandEnvelope(
            envelope_id="env_1",
            issuer_id="inv_1",
            lease_id=lease.lease_id,
            epoch=2,
            target_resources=("arm_0",),
            control_mode=ControlMode.TRAJECTORY,
            payload={"points": [[0.0, 1.0]]},
            issued_at_monotonic=50.0,
        ),
        CommandAcknowledgement(envelope_id="env_1", accepted=False, reason="stale_epoch"),
        MissionEvent(mission_id="m1", sequence=0, time=1.0, kind="goal_received", payload={"a": 1}),
        MissionResult(
            mission_id="m1",
            status=MissionStatus.REJECTED,
            goal_id="g1",
            skill_results=(_skill_result(),),
            verified_effects=(_fact(),),
            rejection_reasons=(RejectionReason(code="unknown_skill", node_id="n1", detail="x"),),
            failure_reason="none",
            events_ref="/tmp/m.jsonl",
        ),
        DeploymentProfile.model_validate(
            {
                "api_version": "robot_framework/v1alpha1",
                "task_pack": "examples",
                "robot_pack": "mock_mobile_manipulator",
                "default_goal": "goals/x.goal.yaml",
                "deployment": {"mode": "mock", "backend": "mock_sim", "profile": "mock"},
                "planning": {"plugin": "manual", "output_kind": "task_graph"},
                "execution": {
                    "plugin": "sequential",
                    "provider_preference": {"manipulation.pick": ["mock.pick"]},
                },
                "extensions": [{"id": "anhar_ae", "required": True, "config": "ae.yaml"}],
                "safety": {"profile": "mock"},
            }
        ),
    )
    return {type(sample): sample for sample in samples}


SAMPLES = _samples()
_ids = [model.__name__ for model in CONTRACTS]


def test_every_exported_contract_has_a_sample():
    assert set(SAMPLES) == set(CONTRACTS)


@pytest.mark.parametrize("model", CONTRACTS, ids=_ids)
def test_contract_roundtrip(model):
    instance = SAMPLES[model]

    restored = model.model_validate_json(instance.model_dump_json())

    assert restored == instance


@pytest.mark.parametrize("model", CONTRACTS, ids=_ids)
def test_contract_rejects_unknown_field(model):
    data = {**SAMPLES[model].model_dump(mode="json"), "surprise": 1}

    with pytest.raises(ValidationError, match="surprise"):
        model.model_validate(data)


@pytest.mark.parametrize("model", CONTRACTS, ids=_ids)
def test_sample_validates_against_generated_schema(model):
    jsonschema.validate(SAMPLES[model].model_dump(mode="json"), model.model_json_schema())


def test_schema_export_is_idempotent(tmp_path):
    first = {p.name: p.read_bytes() for p in export_schemas(tmp_path / "a")}
    second = {p.name: p.read_bytes() for p in export_schemas(tmp_path / "b")}

    assert first == second
    assert len(first) == len(CONTRACTS) >= 15
    assert json.loads(first["GoalSpec.schema.json"])["title"] == "GoalSpec"


def test_contracts_are_immutable():
    goal = SAMPLES[GoalSpec]

    with pytest.raises(ValidationError, match="frozen"):
        goal.goal_id = "other"  # type: ignore[misc]
    assert goal.model_copy(update={"goal_id": "other"}).goal_id == "other"


def test_schema_version_must_match_pattern():
    with pytest.raises(ValidationError, match="schema_version"):
        GoalSpec(goal_id="g", objective="x", schema_version="1.0")


def test_identifiers_must_be_dotted_lowercase():
    with pytest.raises(ValidationError, match="skill_id"):
        SkillNode(node_id="n", skill_id="Manipulation-Pick")
    with pytest.raises(ValidationError, match="task_pack"):
        DeploymentProfile.model_validate(
            {**SAMPLES[DeploymentProfile].model_dump(mode="json"), "task_pack": "../etc"}
        )


def test_plan_proposal_requires_matching_payload():
    native = NativeArtifact(format="btcpp4_xml", content="<root/>", validator_id="bt_check")

    with pytest.raises(ValidationError, match="requires exactly the payload"):
        PlanProposal(
            proposal_id="p",
            kind=PlanArtifactKind.TASK_GRAPH,
            planner_id="x",
            task_graph=_graph(),
            native=native,
            world_snapshot_id="ws",
        )
    with pytest.raises(ValidationError, match="requires exactly the payload"):
        PlanProposal(
            proposal_id="p",
            kind=PlanArtifactKind.POLICY_GOAL,
            planner_id="x",
            world_snapshot_id="ws",
        )
    policy = PolicyGoal(instruction="pick the bottle", horizon_s=5.0)
    assert (
        PlanProposal(
            proposal_id="p",
            kind=PlanArtifactKind.POLICY_GOAL,
            planner_id="x",
            policy_goal=policy,
            world_snapshot_id="ws",
        ).policy_goal
        == policy
    )


def test_empty_task_graph_is_rejected():
    with pytest.raises(ValidationError, match="root"):
        TaskGraph.model_validate({})
    with pytest.raises(ValidationError, match="at least 1"):
        SequenceNode(node_id="s", children=())


def test_task_graph_rejects_duplicate_node_ids():
    leaf = SkillNode(node_id="same", skill_id="x.y")

    with pytest.raises(ValidationError, match="duplicate node_id"):
        TaskGraph(root=SequenceNode(node_id="s", children=(leaf, leaf)))


def test_task_graph_rejects_unknown_recovery_ref():
    with pytest.raises(ValidationError, match="unknown recovery_ref"):
        TaskGraph(root=SkillNode(node_id="a", skill_id="x.y", recovery_ref="nope"))


def test_loops_and_waits_must_be_bounded():
    child = SkillNode(node_id="c", skill_id="x.y")
    with pytest.raises(ValidationError, match="max_iterations"):
        LoopNode.model_validate({"node_id": "l", "child": child})
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        LoopNode(node_id="l", child=child, max_iterations=0)
    with pytest.raises(ValidationError, match="greater than 0"):
        WaitEventNode(node_id="w", condition=FactPredicate(predicate="p"), timeout_s=0)


def test_parallel_needs_two_branches():
    with pytest.raises(ValidationError, match="at least 2"):
        ParallelNode(node_id="p", children=(SkillNode(node_id="a", skill_id="x.y"),))


def test_deeply_nested_graph_roundtrips():
    node: object = SkillNode(node_id="leaf", skill_id="x.y")
    for depth in range(30):
        node = SequenceNode(node_id=f"s{depth}", children=(node,))
    graph = TaskGraph.model_validate({"root": node})

    assert TaskGraph.model_validate_json(graph.model_dump_json()) == graph


def test_task_graph_dispatches_yaml_dicts_on_kind():
    graph = TaskGraph.model_validate(
        {
            "root": {
                "kind": "sequence",
                "node_id": "s",
                "children": [{"kind": "skill", "node_id": "a", "skill_id": "x.y"}],
            }
        }
    )

    assert isinstance(graph.root, SequenceNode)
    assert isinstance(graph.root.children[0], SkillNode)
    with pytest.raises(ValidationError, match="kind"):
        TaskGraph.model_validate({"root": {"kind": "teleport", "node_id": "s"}})


def test_skill_contract_validates_port_references_and_effects():
    base = SAMPLES[SkillContract].model_dump()

    with pytest.raises(ValidationError, match="unknown input port"):
        SkillContract.model_validate(
            {**base, "expected_effects": [{"predicate": "holding", "args": ["robot", "$thing"]}]}
        )
    with pytest.raises(ValidationError, match="no expected effects"):
        SkillContract.model_validate({**base, "expected_effects": []})
    with pytest.raises(ValidationError, match="duplicate input port"):
        SkillContract.model_validate({**base, "inputs": [base["inputs"][0], base["inputs"][0]]})


def test_skill_contract_port_lookup_and_binding():
    contract = SAMPLES[SkillContract]

    assert contract.input("object") is not None and contract.input("nope") is None
    assert contract.output("grasp") is not None
    assert contract.referenced_ports() == frozenset({"object"})
    assert bind_args(("robot", "$object"), {"object": "bottle_17"}) == ("robot", "bottle_17")


def test_fact_value_must_be_json_serialisable():
    with pytest.raises(ValidationError, match="JSON-serialisable"):
        Fact(predicate="p", value=object(), source="s", observation_time=0.0)


def test_fact_staleness_uses_validity_window():
    fact = _fact()

    assert not fact.is_stale(12.5 + 4.9)
    assert fact.is_stale(12.5 + 5.0)
    assert not fact.model_copy(update={"validity_s": None}).is_stale(1e9)


def test_world_snapshot_holds_only_on_fresh_matching_facts():
    snapshot = SAMPLES[WorldSnapshot]
    holds = FactPredicate(predicate="holding", args=("robot", "bottle_17"))

    assert snapshot.holds(holds, now=13.0)
    assert not snapshot.holds(holds, now=30.0)
    assert not snapshot.holds(holds.model_copy(update={"expected": False}), now=13.0)
    assert not snapshot.holds(FactPredicate(predicate="missing"), now=13.0)
    assert snapshot.is_stale(snapshot.facts[0], now=30.0)


def test_mission_event_payload_must_be_json():
    with pytest.raises(ValidationError, match="JSON-serialisable"):
        MissionEvent(
            mission_id="m", sequence=0, time=0.0, kind="goal_received", payload={"x": {1, 2}}
        )


def test_real_mode_requires_a_real_safety_profile():
    data = SAMPLES[DeploymentProfile].model_dump(mode="json")
    data["deployment"] = {"mode": "real", "backend": "ros2_control"}

    with pytest.raises(ValidationError, match="real safety profile"):
        DeploymentProfile.model_validate(data)
    assert DeploymentProfile.model_validate({**data, "safety": {"profile": "piper_cell_v1"}})


def test_profile_rejects_duplicate_extensions():
    data = SAMPLES[DeploymentProfile].model_dump(mode="json")
    data["extensions"] = [{"id": "a_b"}, {"id": "a_b", "required": True}]

    with pytest.raises(ValidationError, match="unique"):
        DeploymentProfile.model_validate(data)


@pytest.mark.parametrize("bad", ["inf", "nan"])
def test_durations_must_be_finite(bad):
    data = SAMPLES[DeploymentProfile].model_dump(mode="json")
    data["execution"] = {"plugin": "sequential", "lease_ttl_s": bad}

    with pytest.raises(ValidationError, match="lease_ttl_s"):
        DeploymentProfile.model_validate(data)
    with pytest.raises(ValidationError, match="max_stop_time_s"):
        CancellationSpec(max_stop_time_s=float(bad))
