"""Package loaders, registry, extension loading and backend wiring."""

import pytest

from builders import REPO_ROOT, ScriptedGrounding, make_context, sim, skill_node, write_profile
from robot_framework.core.clock import MockClock
from robot_framework.core.context import build_context
from robot_framework.core.errors import (
    ContractValidationError,
    ExtensionRequiredError,
    FrameworkError,
    UnsupportedOperationError,
)
from robot_framework.core.interfaces import GroundingPlugin, SkillProvider
from robot_framework.core.mission_supervisor import MissionSupervisor
from robot_framework.core.recorder import MissionRecorder
from robot_framework.core.registry import Registry
from robot_framework.core.resource_manager import CommandAuthority, ResourceManager
from robot_framework.core.skill_runtime import SkillRuntime
from robot_framework.extensions.loader import ExtensionLoader, default_extension_factories
from robot_framework.extensions.null import NullGroundingPlugin
from robot_framework.packages.loader import (
    ROOT_ENV,
    load_contract,
    load_task_pack,
    pack_file,
    read_yaml,
    resolve_root,
)
from robot_framework.robot_backends.mock import MockRobotBackend
from robot_framework.spec import AssessmentStatus, ExtensionRef, GoalSpec, LifecycleState


def test_example_task_pack_loads():
    pack = load_task_pack(REPO_ROOT, "examples")

    assert set(pack.tasks) == {"bottle_delivery"}
    assert {s.skill_id for s in pack.skills} == {
        "navigation.go_to",
        "perception.observe_target",
        "manipulation.pick",
        "manipulation.place",
    }


def test_invalid_yaml_and_missing_files_raise_contract_errors(tmp_path):
    broken = tmp_path / "broken.yaml"
    broken.write_text("a: [unclosed")

    with pytest.raises(ContractValidationError, match="invalid YAML") as exc_info:
        read_yaml(broken)
    assert exc_info.value.details["file"] == str(broken)
    with pytest.raises(ContractValidationError, match="cannot read"):
        read_yaml(tmp_path / "missing.yaml")


def test_schema_errors_carry_the_pydantic_error_list(tmp_path):
    path = tmp_path / "goal.yaml"
    path.write_text("goal_id: g\nobjective: Not-An-Identifier\nextra: 1\n")

    with pytest.raises(ContractValidationError, match="not a valid GoalSpec") as exc_info:
        load_contract(path, GoalSpec)

    fields = {tuple(e["loc"]) for e in exc_info.value.details["errors"]}
    assert fields == {("objective",), ("extra",)}


def test_task_pack_errors(tmp_path):
    with pytest.raises(ContractValidationError, match="not found"):
        load_task_pack(tmp_path, "nothing_here")
    pack_dir = tmp_path / "task_packs" / "dupes"
    pack_dir.mkdir(parents=True)
    task = (REPO_ROOT / "task_packs/examples/bottle_delivery.task.yaml").read_text()
    (pack_dir / "a.task.yaml").write_text(task)
    (pack_dir / "b.task.yaml").write_text(task)
    with pytest.raises(ContractValidationError, match="duplicate task ids"):
        load_task_pack(tmp_path, "dupes")


def test_pack_files_cannot_escape_the_pack():
    pack = load_task_pack(REPO_ROOT, "examples")

    assert pack_file(pack, "goals/deliver_bottle.goal.yaml").is_file()
    with pytest.raises(ContractValidationError, match="escapes"):
        pack_file(pack, "../../README.md")


def test_resolve_root_prefers_override_then_environment(tmp_path, monkeypatch):
    profile = tmp_path / "deployment_profiles" / "p.yaml"
    monkeypatch.delenv(ROOT_ENV, raising=False)

    default = resolve_root(profile)
    monkeypatch.setenv(ROOT_ENV, "/somewhere")

    assert default == tmp_path.resolve()
    assert str(resolve_root(profile)) == "/somewhere"
    assert resolve_root(profile, override=tmp_path) == tmp_path


def test_registry_enforces_unique_keys_and_protocols():
    registry: Registry[SkillProvider] = Registry("provider", SkillProvider)

    with pytest.raises(ContractValidationError, match="does not implement SkillProvider"):
        registry.register("bad", object())
    registry.register("ok", make_context().providers.get("mock.pick"))
    with pytest.raises(ContractValidationError, match="duplicate provider 'ok'"):
        registry.register("ok", make_context().providers.get("mock.pick"))
    with pytest.raises(KeyError, match="unknown provider 'nope'"):
        registry.get("nope")
    assert "ok" in registry and len(registry) == 1 and registry.kind == "provider"
    with pytest.raises(TypeError):
        registry.items()["x"] = None  # type: ignore[index]


def test_extension_loader_skips_unknown_optional_extensions():
    recorder = MissionRecorder(MockClock())

    loaded = ExtensionLoader(default_extension_factories(), recorder).load(
        [ExtensionRef(id="null_grounding"), ExtensionRef(id="not_installed")]
    )

    assert [e.extension_id for e in loaded] == ["null_grounding"]
    assert recorder.events("extension_warning")[0].payload["extension_id"] == "not_installed"


def test_extension_loader_refuses_missing_or_broken_required_extensions():
    factories = default_extension_factories()

    def broken(config):
        raise RuntimeError(f"cannot read {config}")

    factories.register("broken_ae", broken)
    loader = ExtensionLoader(factories)

    with pytest.raises(ExtensionRequiredError, match="is not installed"):
        loader.load([ExtensionRef(id="anhar_ae", required=True)])
    with pytest.raises(ExtensionRequiredError, match="cannot read ae.yaml"):
        loader.load([ExtensionRef(id="broken_ae", required=True, config="ae.yaml")])
    assert loader.load([ExtensionRef(id="broken_ae", config="ae.yaml")]) == ()


async def test_null_grounding_plugin_has_no_opinion():
    ctx = make_context()
    manifest = ctx.providers.get("mock.pick").manifest
    runtime = SkillRuntime(ctx)
    plugin = NullGroundingPlugin()

    report = await plugin.assess(
        runtime._validated(
            skill_node("manipulation.pick", object="b"), ctx.skills.get("manipulation.pick")
        ),
        manifest,
        ctx.world.snapshot(),
    )

    assert isinstance(plugin, GroundingPlugin) and isinstance(ScriptedGrounding(), GroundingPlugin)
    assert report.status is AssessmentStatus.NOT_APPLICABLE


async def test_mock_robot_backend_cannot_reset():
    resources = ResourceManager(MockClock(), frozenset({"arm_0"}))
    backend = MockRobotBackend(CommandAuthority(resources))

    assert backend.capabilities() == frozenset({"dispatch"})
    with pytest.raises(UnsupportedOperationError, match="does not support reset"):
        await backend.reset()


async def test_mock_simulation_backend_declares_and_records_sim_controls(ctx):
    backend = sim(ctx)

    await backend.step()
    await backend.pause()

    assert backend.capabilities() == frozenset({"dispatch", "reset", "step", "pause"})
    assert [e.kind for e in ctx.recorder.events()][-2:] == ["sim_step", "sim_pause"]


async def test_mock_robot_profile_runs_without_simulation_features(tmp_path, monkeypatch):
    profile = write_profile(
        tmp_path, monkeypatch, deployment={"mode": "mock", "backend": "mock_robot"}
    )
    ctx = build_context(profile, clock=MockClock(now=1000.0))

    result = await MissionSupervisor(ctx).run(ctx.default_goal)

    assert ctx.backend.backend_id == "mock_robot"
    assert result.status.value == "SUCCEEDED"
    assert all(r.state is LifecycleState.SUCCEEDED for r in result.skill_results)


def test_framework_errors_serialise_with_their_code():
    error = UnsupportedOperationError("no reset", details={"backend": "real"})

    assert error.to_dict() == {
        "error": "unsupported",
        "message": "no reset",
        "details": {"backend": "real"},
    }
    assert isinstance(error, FrameworkError)
