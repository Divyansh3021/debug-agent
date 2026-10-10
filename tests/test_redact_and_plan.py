import json

from debug_agent.jsonutil import parse_json_object
from debug_agent.models import ASYNC_BRANCH_OLD, ScriptedModel
from debug_agent.redact import redact
from debug_agent.workspace import ApplyError, apply_actions, prepare_workspace


def test_redact_replaces_common_secret_shapes():
    cleaned, count = redact(
        {
            "message": "api_key=sk-live-DEMOKEY123456",
            "authorization": "Bearer demo.token.value",
            "nested": ["token=abc.def.ghi"],
        }
    )
    blob = json.dumps(cleaned)
    assert "DEMOKEY" not in blob
    assert "demo.token" not in blob
    assert "abc.def" not in blob
    assert count >= 3


def test_parse_json_object_accepts_fenced_json():
    parsed = parse_json_object('```json\n{"ok": true}\n```')
    assert parsed == {"ok": True}


def test_scripted_edit_matches_the_scenario_source():
    source = (
        __import__("pathlib").Path("scenarios/checkout_async_capture/src/checkout/capture.py")
        .read_text(encoding="utf-8")
    )
    assert source.count(ASYNC_BRANCH_OLD) == 1


def test_scripted_model_switches_from_flag_to_edit():
    model = ScriptedModel()
    first = json.loads(model.complete(system="s", user="task: mitigate\nattempt: 0\n"))
    second = json.loads(model.complete(system="s", user="task: mitigate\nattempt: 1\n"))
    assert first["actions"][0]["kind"] == "flag"
    assert second["actions"][0]["kind"] == "edit"
    assert second["risk"] == "medium"


def test_edit_must_match_once(tmp_path):
    scenario = tmp_path / "scenario"
    source = scenario / "src"
    source.mkdir(parents=True)
    target = source / "checkout"
    target.mkdir()
    file = target / "capture.py"
    file.write_text("alpha\nalpha\n", encoding="utf-8")
    workspace = prepare_workspace(scenario, tmp_path / "run")
    try:
        apply_actions(
            workspace,
            [{"kind": "edit", "payload": {"path": "src/checkout/capture.py", "old": "alpha\n", "new": "beta\n"}}],
        )
    except ApplyError as exc:
        assert "found it 2" in str(exc)
    else:
        raise AssertionError("expected the edit to be rejected")
