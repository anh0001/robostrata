"""Mock skill providers with fault injection.

A provider's physical effect is a command: the final envelope carries ``set_facts`` that the mock
backend applies to ground truth only when the command authority accepts it. Providers never write
the world model directly; only the verifier's observations reach it.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from robot_framework.core.clock import Clock
from robot_framework.core.interfaces import ExecutionHandle, RobotBackend
from robot_framework.robot_backends.mock import SET_FACTS_KEY
from robot_framework.spec import (
    CancellationSpec,
    CommandEnvelope,
    ControlMode,
    FailureCategory,
    FailureDiagnosis,
    HardwareRequirement,
    ProgressReport,
    ProviderKind,
    ProviderManifest,
    ProviderOutcome,
    ProviderStatus,
    ResourceLease,
    SkillInvocation,
)

FactAssignment = dict[str, Any]
ROBOT_ENTITY = "robot"
MOCK_PROVIDER_VERSION = "0.1.0"
MOCK_MAX_STOP_TIME_S = 0.5


@dataclass(frozen=True)
class MockFaults:
    """Fault-injection knobs. Durations are real (``asyncio.sleep``); keep them small."""

    duration_s: float = 0.01
    steps: int = 2
    fail_after_s: float | None = None
    lie_success: bool = False
    drop_ack: bool = False
    effect_happened: bool = True
    cancel_latency_s: float = 0.0
    refuse_cancel: bool = False

    def effect_happens(self) -> bool:
        return not self.lie_success and (not self.drop_ack or self.effect_happened)


def assignment(predicate: str, args: tuple[str, ...], value: Any) -> FactAssignment:
    return {"predicate": predicate, "args": list(args), "value": value}


class MockExecutionHandle:
    def __init__(self, invocation_id: str, clock: Clock) -> None:
        self.invocation_id = invocation_id
        self._clock = clock
        self._cancel_requested = asyncio.Event()
        self._task: asyncio.Task[ProviderOutcome] | None = None
        self._fraction = 0.0
        self._message = "started"

    def attach(self, task: asyncio.Task[ProviderOutcome]) -> None:
        self._task = task

    @property
    def task(self) -> asyncio.Task[ProviderOutcome]:
        if self._task is None:
            raise RuntimeError(f"handle {self.invocation_id} has no running task")
        return self._task

    async def wait(self, timeout_s: float | None = None) -> ProviderOutcome:
        return await asyncio.wait_for(asyncio.shield(self.task), timeout_s)

    async def cancel(self, reason: str) -> None:
        self._message = f"cancel requested: {reason}"
        self._cancel_requested.set()

    def progress(self) -> ProgressReport:
        return ProgressReport(
            fraction=self._fraction, message=self._message, time=self._clock.now()
        )

    def report(self, fraction: float, message: str) -> None:
        self._fraction = fraction
        self._message = message

    async def sleep_or_cancel(self, seconds: float, *, honour_cancel: bool) -> bool:
        """Sleep; return True early if a cancel was requested and is being honoured."""
        if not honour_cancel:
            await asyncio.sleep(seconds)
            return False
        try:
            await asyncio.wait_for(self._cancel_requested.wait(), seconds)
        except asyncio.TimeoutError:
            return False
        return True


class MockProviderBase:
    def __init__(
        self, manifest: ProviderManifest, clock: Clock, faults: MockFaults | None = None
    ) -> None:
        self.manifest = manifest
        self.faults = faults if faults is not None else MockFaults()
        self._clock = clock
        self._handles: tuple[MockExecutionHandle, ...] = ()
        self._scheduled: tuple[MockFaults, ...] = ()

    @property
    def started(self) -> tuple[str, ...]:
        """Invocation ids this provider was started for, in order."""
        return tuple(handle.invocation_id for handle in self._handles)

    def configure(self, faults: MockFaults) -> None:
        """Faults used by every start that has no scheduled faults."""
        self.faults = faults

    def schedule(self, *faults: MockFaults) -> None:
        """Faults for the next starts, one per start, before falling back to ``faults``."""
        self._scheduled = tuple(faults)

    async def drain(self) -> None:
        """Wait for every started execution to finish (test hygiene)."""
        await asyncio.gather(*(h.task for h in self._handles), return_exceptions=True)

    def effects(self, params: Mapping[str, Any]) -> tuple[FactAssignment, ...]:
        raise NotImplementedError

    async def start(
        self, request: SkillInvocation, lease: ResourceLease, backend: RobotBackend
    ) -> ExecutionHandle:
        faults = self._scheduled[0] if self._scheduled else self.faults
        self._scheduled = self._scheduled[1:]
        handle = MockExecutionHandle(request.invocation_id, self._clock)
        handle.attach(asyncio.ensure_future(self._run(request, lease, backend, handle, faults)))
        self._handles = (*self._handles, handle)
        return handle

    async def _run(
        self,
        request: SkillInvocation,
        lease: ResourceLease,
        backend: RobotBackend,
        handle: MockExecutionHandle,
        faults: MockFaults,
    ) -> ProviderOutcome:
        loop = asyncio.get_running_loop()
        started = loop.time()
        for step in range(faults.steps):
            stop = await handle.sleep_or_cancel(
                faults.duration_s / faults.steps, honour_cancel=not faults.refuse_cancel
            )
            if stop:
                await asyncio.sleep(faults.cancel_latency_s)
                return self._outcome(request, "CANCELED", "cancelled", "stopped on request")
            if faults.fail_after_s is not None and loop.time() - started >= faults.fail_after_s:
                return self._outcome(request, "FAILURE", "hardware_fault", "injected fault")
            final = step == faults.steps - 1
            effects = (
                self.effects(request.bound_params) if final and faults.effect_happens() else ()
            )
            ack = await backend.dispatch(self._envelope(request, lease, step, effects))
            if not ack.accepted:
                return self._outcome(request, "FAILURE", "command_rejected", ack.reason or "")
            handle.report((step + 1) / faults.steps, f"step {step + 1}/{faults.steps}")
        if faults.drop_ack:
            return self._outcome(request, "UNKNOWN", "ack_lost", "final acknowledgement lost")
        return ProviderOutcome(
            invocation_id=request.invocation_id,
            status="SUCCESS",
            evidence_references=(f"claim:{self.manifest.provider_id}:{request.invocation_id}",),
        )

    def _envelope(
        self,
        request: SkillInvocation,
        lease: ResourceLease,
        step: int,
        effects: tuple[FactAssignment, ...],
    ) -> CommandEnvelope:
        return CommandEnvelope(
            envelope_id=f"env_{uuid.uuid4().hex[:12]}",
            issuer_id=request.invocation_id,
            lease_id=lease.lease_id,
            epoch=lease.epoch,
            target_resources=lease.resources,
            control_mode=lease.control_mode,
            payload={"skill_id": request.skill_id, "step": step, SET_FACTS_KEY: list(effects)},
            issued_at_monotonic=self._clock.monotonic(),
        )

    @staticmethod
    def _outcome(
        request: SkillInvocation, status: ProviderStatus, category: FailureCategory, detail: str
    ) -> ProviderOutcome:
        return ProviderOutcome(
            invocation_id=request.invocation_id,
            status=status,
            diagnosis=FailureDiagnosis(category=category, detail=detail),
        )


class MockObserveProvider(MockProviderBase):
    def effects(self, params: Mapping[str, Any]) -> tuple[FactAssignment, ...]:
        return (assignment("pose_known", (str(params["target"]),), True),)


class MockNavigateProvider(MockProviderBase):
    def effects(self, params: Mapping[str, Any]) -> tuple[FactAssignment, ...]:
        return (assignment("at", (ROBOT_ENTITY, str(params["location"])), True),)


class MockPickProvider(MockProviderBase):
    def effects(self, params: Mapping[str, Any]) -> tuple[FactAssignment, ...]:
        return (assignment("holding", (ROBOT_ENTITY, str(params["object"])), True),)


class MockPlaceProvider(MockProviderBase):
    def effects(self, params: Mapping[str, Any]) -> tuple[FactAssignment, ...]:
        obj, location = str(params["object"]), str(params["location"])
        return (
            assignment("holding", (ROBOT_ENTITY, obj), False),
            assignment("at", (obj, location), True),
        )


def mock_manifest(
    provider_id: str,
    skill_id: str,
    capability: str,
    control_mode: ControlMode,
    *,
    max_stop_time_s: float = MOCK_MAX_STOP_TIME_S,
) -> ProviderManifest:
    return ProviderManifest(
        provider_id=provider_id,
        kind=ProviderKind.SKILL,
        implements=(skill_id,),
        hardware=(HardwareRequirement(capability=capability),),
        domains=("mock",),
        version=MOCK_PROVIDER_VERSION,
        cancellation=CancellationSpec(mode="immediate", max_stop_time_s=max_stop_time_s),
        control_mode=control_mode,
    )


def build_mock_providers(clock: Clock) -> tuple[MockProviderBase, ...]:
    return (
        MockObserveProvider(
            mock_manifest(
                "mock.observe", "perception.observe_target", "perception.rgbd", ControlMode.NONE
            ),
            clock,
        ),
        MockNavigateProvider(
            mock_manifest(
                "mock.navigate", "navigation.go_to", "navigation.ground", ControlMode.VELOCITY
            ),
            clock,
        ),
        MockPickProvider(
            mock_manifest(
                "mock.pick", "manipulation.pick", "manipulation.single_arm", ControlMode.TRAJECTORY
            ),
            clock,
        ),
        MockPlaceProvider(
            mock_manifest(
                "mock.place",
                "manipulation.place",
                "manipulation.single_arm",
                ControlMode.TRAJECTORY,
            ),
            clock,
        ),
    )
