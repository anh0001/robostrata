"""Mission supervisor: goal → plan → validation → one executive → verified mission result.

One mission per context at a time, and one executive per mission.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

from robot_framework.core.errors import (
    FrameworkError,
    MissionAlreadyRunningError,
    PlanRejectedError,
)
from robot_framework.core.interfaces import Executive, ExecutiveOutcome, MissionHandle, TaskPlanner
from robot_framework.core.skill_runtime import SkillRuntime
from robot_framework.core.validation import PlanValidator, ValidatedPlan
from robot_framework.spec import (
    GoalSpec,
    LifecycleState,
    MissionResult,
    MissionStatus,
    PlanProposal,
    RejectionReason,
    SuccessCriterion,
    VerificationStatus,
    WorldSnapshot,
)

if TYPE_CHECKING:
    from robot_framework.core.context import FrameworkContext

log = logging.getLogger(__name__)

DEADLINE_EXCEEDED = "deadline_exceeded"

_STATUS_FOR_STATE = {
    LifecycleState.SUCCEEDED: MissionStatus.SUCCEEDED,
    LifecycleState.CANCELED: MissionStatus.CANCELED,
    LifecycleState.OUTCOME_UNKNOWN: MissionStatus.OUTCOME_UNKNOWN,
}


def rejection_reasons(error: PlanRejectedError) -> tuple[RejectionReason, ...]:
    raw: list[dict[str, Any]] = error.details.get("reasons", [])
    if not raw:
        return (RejectionReason(code=error.code, detail=error.message),)
    return tuple(RejectionReason.model_validate(reason) for reason in raw)


def mission_status(outcome: ExecutiveOutcome, failure: str | None) -> MissionStatus:
    """An unresolved OUTCOME_UNKNOWN anywhere dominates: callers must reconcile before retrying."""
    unknown = outcome.state is LifecycleState.OUTCOME_UNKNOWN or any(
        result.state is LifecycleState.OUTCOME_UNKNOWN for result in outcome.skill_results
    )
    if unknown:
        return MissionStatus.OUTCOME_UNKNOWN
    if failure:
        return MissionStatus.FAILED
    return _STATUS_FOR_STATE.get(outcome.state, MissionStatus.FAILED)


def _reject(code: str, detail: str) -> PlanRejectedError:
    return PlanRejectedError(
        detail, details={"reasons": [RejectionReason(code=code, detail=detail).model_dump()]}
    )


class MissionSupervisor:
    def __init__(self, ctx: FrameworkContext) -> None:
        self._ctx = ctx
        self._busy = False
        self._live: MissionHandle | None = None
        self._pending_cancel: str | None = None
        self._started_at = 0.0

    @property
    def is_running(self) -> bool:
        return self._busy

    def planner(self) -> TaskPlanner:
        return self._ctx.planners.get(self._ctx.profile.planning.plugin)

    def executive(self) -> Executive:
        return self._ctx.executives.get(self._ctx.profile.execution.plugin)

    async def prepare(self, goal: GoalSpec) -> ValidatedPlan:
        """Plan and validate without executing; raises ``PlanRejectedError`` with reasons."""
        self._check_goal(goal)
        proposal = await self._propose(goal)
        self._ctx.recorder.record("plan_proposed", {"proposal": proposal.model_dump(mode="json")})
        expected = self._ctx.profile.planning.output_kind
        if proposal.kind is not expected:
            raise _reject(
                "unexpected_artifact_kind",
                f"profile expects '{expected.value}' from the planner, got '{proposal.kind.value}'",
            )
        return PlanValidator(self._ctx).validate(proposal, self._ctx.robot, self.executive())

    async def run(self, goal: GoalSpec) -> MissionResult:
        if self._busy:
            raise MissionAlreadyRunningError(
                "a mission is already running in this context",
                details={"mission_id": self._ctx.recorder.mission_id},
            )
        self._busy = True
        self._pending_cancel = None
        try:
            return await self._run(goal)
        finally:
            self._busy = False
            self._live = None

    async def cancel(self, reason: str = "operator_request") -> None:
        """Cancel the running mission. A cancel that arrives while the mission is still being
        planned is remembered and stops the mission before anything executes."""
        if not self._busy:
            return
        self._ctx.recorder.record("mission_canceled", {"reason": reason})
        if self._live is None:
            self._pending_cancel = reason
            return
        await self._live.cancel(reason)

    async def _propose(self, goal: GoalSpec) -> PlanProposal:
        planner = self.planner()
        try:
            return await planner.propose(goal, self._ctx.world.snapshot(), self._ctx.skills.items())
        except PlanRejectedError:
            raise
        except Exception as exc:
            log.exception("planner failed", extra={"planner_id": planner.planner_id})
            raise _reject(
                "planner_error",
                f"planner '{planner.planner_id}' failed: {type(exc).__name__}: {exc}",
            ) from exc

    async def _run(self, goal: GoalSpec) -> MissionResult:
        mission_id = f"mission_{uuid.uuid4().hex[:12]}"
        self._started_at = self._ctx.clock.now()
        self._ctx.recorder.start_mission(mission_id)
        self._ctx.recorder.record("goal_received", {"goal": goal.model_dump(mode="json")})
        try:
            validated = await self.prepare(goal)
        except PlanRejectedError as exc:
            return self._rejected(mission_id, goal, exc)
        self._ctx.recorder.record(
            "plan_validated",
            {
                "proposal_id": validated.proposal.proposal_id,
                "skills": list(validated.skill_refs),
                "resource_scope": sorted(validated.resource_scope),
            },
        )
        if self._pending_cancel is not None:
            canceled = ExecutiveOutcome(LifecycleState.CANCELED, ())
            return await self._finished(mission_id, goal, validated.proposal, canceled, None)
        outcome, failure = await self._execute(validated, goal)
        return await self._finished(mission_id, goal, validated.proposal, outcome, failure)

    def _check_goal(self, goal: GoalSpec) -> None:
        if goal.human_policy.require_plan_confirmation:
            raise _reject(
                "operator_confirmation_unsupported",
                "plan confirmation was requested but this build has no operator channel",
            )
        hard = [c.name for c in goal.constraints if c.hard]
        if hard:
            raise _reject(
                "unsupported_constraint",
                f"no component in this build enforces hard constraint(s) {hard}",
            )

    async def _execute(
        self, validated: ValidatedPlan, goal: GoalSpec
    ) -> tuple[ExecutiveOutcome, str | None]:
        runtime = SkillRuntime(self._ctx)
        try:
            handle = await self.executive().start(validated.proposal, runtime, self._ctx)
        except Exception as exc:
            reason = (
                f"{exc.code}: {exc.message}"
                if isinstance(exc, FrameworkError)
                else f"internal_error: {type(exc).__name__}: {exc}"
            )
            return ExecutiveOutcome(LifecycleState.FAILED, ()), reason
        self._live = handle
        if self._pending_cancel is not None:
            await handle.cancel(self._pending_cancel)
        try:
            return await handle.wait(goal.deadline_s), None
        except asyncio.TimeoutError:
            log.warning("mission deadline exceeded", extra={"goal_id": goal.goal_id})
            await handle.cancel(DEADLINE_EXCEEDED)
            return await handle.wait(), DEADLINE_EXCEEDED
        except asyncio.CancelledError:
            # The caller abandoned run(); the robot must still be stopped before run() returns.
            await asyncio.shield(asyncio.ensure_future(handle.cancel("supervisor_cancelled")))
            raise

    async def _finished(
        self,
        mission_id: str,
        goal: GoalSpec,
        proposal: PlanProposal,
        outcome: ExecutiveOutcome,
        failure: str | None,
    ) -> MissionResult:
        failure = failure or outcome.error
        status = mission_status(outcome, failure)
        if status is MissionStatus.SUCCEEDED:
            unmet = await self._unmet_criteria(goal)
            if unmet:
                status, failure = MissionStatus.FAILED, f"success_criteria_unmet: {unmet}"
        verified = tuple(
            fact
            for result in outcome.skill_results
            if result.verification_status is VerificationStatus.VERIFIED
            for fact in result.observed_effects
        )
        result = MissionResult(
            mission_id=mission_id,
            status=status,
            goal_id=goal.goal_id,
            proposal_id=proposal.proposal_id,
            skill_results=outcome.skill_results,
            verified_effects=verified,
            failure_reason=failure,
            events_ref=self._events_ref(),
        )
        self._ctx.recorder.record(
            "mission_finished", {"status": status.value, "failure_reason": failure}
        )
        return result

    async def _unmet_criteria(self, goal: GoalSpec) -> list[str]:
        """Success criteria need fresh evidence observed during this mission."""
        for criterion in goal.success_criteria:
            await self._ctx.world.observe(criterion.predicate, criterion.args)
        snapshot = self._ctx.world.snapshot()
        return [
            f"{c.predicate}({', '.join(c.args)})={c.expected}"
            for c in goal.success_criteria
            if not self._criterion_holds(snapshot, c)
        ]

    def _criterion_holds(self, snapshot: WorldSnapshot, criterion: SuccessCriterion) -> bool:
        fact = snapshot.lookup(criterion.predicate, criterion.args)
        return (
            fact is not None
            and fact.observation_time >= self._started_at
            and snapshot.holds(criterion, snapshot.time)
        )

    def _rejected(self, mission_id: str, goal: GoalSpec, error: PlanRejectedError) -> MissionResult:
        reasons = rejection_reasons(error)
        self._ctx.recorder.record(
            "plan_rejected", {"reasons": [reason.model_dump(mode="json") for reason in reasons]}
        )
        self._ctx.recorder.record(
            "mission_finished", {"status": MissionStatus.REJECTED.value, "failure_reason": None}
        )
        return MissionResult(
            mission_id=mission_id,
            status=MissionStatus.REJECTED,
            goal_id=goal.goal_id,
            rejection_reasons=reasons,
            events_ref=self._events_ref(),
        )

    def _events_ref(self) -> str | None:
        sink = self._ctx.recorder.sink
        return str(sink) if sink is not None else None
