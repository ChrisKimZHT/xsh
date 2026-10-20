from xsh.messages import Message
from xsh.prompt import build_prompt
from xsh.session import Session


def test_model_interpolation_preserves_project_instructions(tmp_path):
    instructions = "Keep {{model}} literal in project files."
    (tmp_path / "AGENTS.md").write_text(instructions, encoding="utf-8")

    prompt = build_prompt(tmp_path, model="provider/model-v2")

    assert "You are a coding assistant powered by the provider/model-v2 model." in prompt
    assert f"Workspace: {tmp_path.resolve()}" in prompt
    assert prompt.endswith(instructions)
    assert "Your shell tool runs" not in prompt


def test_shell_guidance_matches_available_tool(tmp_path):
    prompt = build_prompt(tmp_path, model="test-model", allow_shell=True)

    assert "It is not sandboxed" in prompt
    assert "no persistent terminal or background job support" in prompt
    assert "[exit code: N]" in prompt


def test_resumed_prompt_update_is_durable_and_preserves_history(tmp_path):
    path = tmp_path / "session.jsonl"
    session = Session.create(path, tmp_path, build_prompt(tmp_path, model="old-model"))
    session.append(Message(role="user", content="Continue working"))
    resumed = Session.load(path)
    updated = build_prompt(tmp_path, model="new-model", allow_shell=True)

    resumed.update_system_prompt(updated)
    reloaded = Session.load(path)

    assert reloaded.messages[0].content == updated
    assert "old-model" not in reloaded.messages[0].content
    assert len(reloaded.messages) == 2
    assert reloaded.messages[1].content == "Continue working"
    recorded = path.read_bytes()
    reloaded.update_system_prompt(updated)
    assert path.read_bytes() == recorded
