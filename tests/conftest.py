"""Shared fixtures. Builders live in ``tests/builders.py`` so test modules can import them."""

import pytest

from builders import START_TIME, delivery_goal, make_context
from robot_framework.core.clock import MockClock
from robot_framework.core.context import FrameworkContext
from robot_framework.core.skill_runtime import SkillRuntime
from robot_framework.spec import GoalSpec


@pytest.fixture
def clock() -> MockClock:
    return MockClock(now=START_TIME)


@pytest.fixture
def ctx(clock: MockClock) -> FrameworkContext:
    return make_context(clock=clock)


@pytest.fixture
def runtime(ctx: FrameworkContext) -> SkillRuntime:
    return SkillRuntime(ctx)


@pytest.fixture
def goal() -> GoalSpec:
    return delivery_goal()
