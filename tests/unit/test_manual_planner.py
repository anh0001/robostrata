import pytest

from builders import delivery_goal, skill_node
from robot_framework.core.errors import PlanRejectedError
from robot_framework.planning.manual import ManualPlanner
from robot_framework.spec import (
    ConditionalNode,
    FactPredicate,
    LoopNode,
    ParallelNode,
    PlanArtifactKind,
    SequenceNode,
    TaskDefinition,
    TaskGraph,
    WaitEventNode,
)


def planner_for(root):
    task = TaskDefinition(task_id="t", objective="deliver_object", graph=TaskGraph(root=root))
    return ManualPlanner({"t": task})


def at(*args):
    return FactPredicate(predicate="at", args=args)


async def test_goal_references_are_bound_in_every_node_kind(ctx):
    root = SequenceNode(
        node_id="seq",
        children=(
            ConditionalNode(
                node_id="cond",
                condition=at("robot", "$goal.pickup_location"),
                then=skill_node("x.a", node_id="a", target="$goal.object"),
                otherwise=skill_node("x.b", node_id="b", spec={"to": ["$goal.delivery_location"]}),
            ),
            LoopNode(
                node_id="loop",
                max_iterations=2,
                until=at("$goal.object", "$goal.delivery_location"),
                child=skill_node("x.c", node_id="c"),
            ),
            WaitEventNode(
                node_id="wait", condition=at("door", "$goal.pickup_location"), timeout_s=1.0
            ),
            ParallelNode(
                node_id="par",
                children=(skill_node("x.d", node_id="d", n=1), skill_node("x.e", node_id="e")),
            ),
        ),
    )

    proposal = await planner_for(root).propose(delivery_goal(), ctx.world.snapshot(), {})

    cond, loop, wait, par = proposal.task_graph.root.children
    assert proposal.kind is PlanArtifactKind.TASK_GRAPH and proposal.planner_id == "manual"
    assert cond.condition.args == ("robot", "kitchen_table")
    assert cond.then.params == {"target": "bottle_17"}
    assert cond.otherwise.params == {"spec": {"to": ["desk_2"]}}
    assert loop.until.args == ("bottle_17", "desk_2")
    assert wait.condition.args == ("door", "kitchen_table")
    assert par.children[0].params == {"n": 1}


async def test_conditional_and_loop_without_optional_parts_are_kept(ctx):
    root = SequenceNode(
        node_id="seq",
        children=(
            ConditionalNode(
                node_id="cond", condition=at("robot", "home"), then=skill_node("x.a", node_id="a")
            ),
            LoopNode(node_id="loop", max_iterations=1, child=skill_node("x.b", node_id="b")),
        ),
    )

    proposal = await planner_for(root).propose(delivery_goal(), ctx.world.snapshot(), {})

    cond, loop = proposal.task_graph.root.children
    assert cond.otherwise is None and loop.until is None


async def test_missing_goal_parameter_rejects_the_plan(ctx):
    planner = planner_for(skill_node("x.a", node_id="a", target="$goal.colour"))

    with pytest.raises(PlanRejectedError, match="colour") as exc_info:
        await planner.propose(delivery_goal(), ctx.world.snapshot(), {})

    assert exc_info.value.details["reasons"][0]["code"] == "unresolved_goal_parameter"
