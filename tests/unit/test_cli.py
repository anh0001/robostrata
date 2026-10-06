import json

import pytest
import yaml

from builders import AE_REQUIRED_PROFILE, BASELINE_PROFILE, REPO_ROOT, write_profile
from robot_framework.cli import main
from robot_framework.spec import MissionEvent
from robot_framework.spec.export import CONTRACTS


def test_validate_prints_the_validated_plan(capsys):
    code = main(["--log-level", "WARNING", "validate", str(BASELINE_PROFILE)])

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["status"] == "valid"
    assert report["skills"] == [
        "navigation.go_to",
        "perception.observe_target",
        "manipulation.pick",
        "manipulation.place",
    ]


def test_validate_refuses_profile_with_missing_required_extension(capsys):
    code = main(["--log-level", "WARNING", "validate", str(AE_REQUIRED_PROFILE)])

    error = json.loads(capsys.readouterr().err)
    assert code == 2
    assert error["error"] == "extension_required"
    assert error["details"]["extension_id"] == "anhar_affordance_effectivity"


def test_run_succeeds_and_records_the_mission(tmp_path, capsys):
    record = tmp_path / "mission.jsonl"

    code = main(["--log-level", "WARNING", "run", str(BASELINE_PROFILE), "--record", str(record)])

    result = json.loads(capsys.readouterr().out)
    events = [MissionEvent.model_validate_json(line) for line in record.read_text().splitlines()]
    assert code == 0 and result["status"] == "SUCCEEDED"
    assert events[0].kind == "goal_received" and events[-1].kind == "mission_finished"


def test_run_exits_one_when_the_mission_does_not_succeed(tmp_path, capsys):
    goal = yaml.safe_load(
        (REPO_ROOT / "task_packs/examples/goals/deliver_bottle.goal.yaml").read_text()
    )
    goal["objective"] = "make_coffee"
    goal_path = tmp_path / "coffee.goal.yaml"
    goal_path.write_text(yaml.safe_dump(goal))

    code = main(["--log-level", "WARNING", "run", str(BASELINE_PROFILE), "--goal", str(goal_path)])

    assert code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "REJECTED"


def test_schemas_export_writes_one_file_per_contract(tmp_path, capsys):
    code = main(["--log-level", "WARNING", "schemas", "export", str(tmp_path / "schemas")])

    assert code == 0
    assert len(list((tmp_path / "schemas").glob("*.schema.json"))) == len(CONTRACTS)
    assert len(capsys.readouterr().out.splitlines()) == len(CONTRACTS)


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"default_goal": None}, "contract_validation"),
        ({"deployment": {"mode": "simulation", "backend": "gazebo"}}, "unsupported"),
        ({"deployment": {"mode": "mock", "backend": "isaac"}}, "unsupported"),
        ({"planning": {"plugin": "btgenbot2"}}, "contract_validation"),
        ({"default_goal": "../../etc/passwd"}, "contract_validation"),
    ],
)
def test_misconfigured_profiles_fail_with_a_stable_error_code(
    tmp_path, monkeypatch, capsys, changes, error
):
    profile = write_profile(tmp_path, monkeypatch, **changes)

    code = main(["--log-level", "WARNING", "validate", str(profile)])

    assert code == 2
    assert json.loads(capsys.readouterr().err)["error"] == error


def test_internal_errors_have_their_own_exit_code(monkeypatch, capsys):
    def explode(*args, **kwargs):
        raise RuntimeError("unexpected bug")

    monkeypatch.setattr("robot_framework.cli.build_context", explode)

    code = main(["--log-level", "ERROR", "validate", str(BASELINE_PROFILE)])

    error = json.loads(capsys.readouterr().err)
    assert code == 3
    assert error == {"error": "internal_error", "message": "RuntimeError: unexpected bug"}
