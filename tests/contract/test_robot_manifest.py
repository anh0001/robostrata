import pytest

from builders import REPO_ROOT
from robot_framework.packages.loader import load_robot_manifest
from robot_framework.spec import RobotManifest


def manifest(edges=(), components=None, capabilities=()):
    components = components or [
        {"component_id": "a", "type": "base", "resources": [{"resource_id": "res_a"}]},
        {"component_id": "b", "type": "arm", "resources": [{"resource_id": "res_b"}]},
        {"component_id": "c", "type": "camera"},
    ]
    return RobotManifest.model_validate(
        {
            "robot_id": "test_robot",
            "components": components,
            "edges": [{"parent": p, "child": c} for p, c in edges],
            "capabilities": list(capabilities),
        }
    )


def test_example_manifest_is_a_component_graph():
    robot = load_robot_manifest(REPO_ROOT, "mock_mobile_manipulator")

    assert robot.resource_ids() == frozenset({"base", "arm_0", "gripper_0"})
    assert robot.structural_capabilities() == frozenset(
        {"navigation.ground", "manipulation.single_arm", "perception.rgbd"}
    )
    assert {(e.parent, e.child) for e in robot.edges} == {
        ("base", "arm_0"),
        ("arm_0", "gripper_0"),
        ("arm_0", "camera_0"),
    }


def test_diamond_shaped_graph_is_accepted():
    robot = manifest(edges=[("a", "b"), ("a", "c"), ("b", "c")])

    assert len(robot.edges) == 3


def test_robot_manifest_rejects_cycle():
    with pytest.raises(ValueError, match="cycle"):
        manifest(edges=[("a", "b"), ("b", "a")])


def test_robot_manifest_rejects_self_loop():
    with pytest.raises(ValueError, match="cycle"):
        manifest(edges=[("a", "a")])


def test_robot_manifest_rejects_duplicate_resource():
    components = [
        {"component_id": "a", "type": "arm", "resources": [{"resource_id": "arm_0"}]},
        {"component_id": "b", "type": "arm", "resources": [{"resource_id": "arm_0"}]},
    ]

    with pytest.raises(ValueError, match="duplicate resource"):
        manifest(components=components)


def test_robot_manifest_rejects_duplicate_component():
    components = [{"component_id": "a", "type": "arm"}, {"component_id": "a", "type": "base"}]

    with pytest.raises(ValueError, match="duplicate component"):
        manifest(components=components)


def test_robot_manifest_rejects_dangling_edge():
    with pytest.raises(ValueError, match="unknown components"):
        manifest(edges=[("a", "ghost")])


def test_capability_binding_must_reference_components():
    with pytest.raises(ValueError, match="capability bindings"):
        manifest(capabilities=[{"capability": "perception.rgbd", "components": ["ghost"]}])


def test_dynamic_capabilities_are_not_structural():
    robot = manifest(
        capabilities=[
            {"capability": "tool.vacuum", "components": ["b"], "structural": False},
            {"capability": "perception.rgbd", "components": ["c"]},
        ]
    )

    assert robot.structural_capabilities() == frozenset({"perception.rgbd"})
