from bridge.app.llm_models import LlmApprovalDecisionContext


def test_llm_approval_context_model_dump_llm_excludes_internal_fields() -> None:
    ctx = LlmApprovalDecisionContext(
        approval_kind="exec",
        approval_id="approval-1",
        tool_name="exec",
        command="echo hello",
        summary="safe summary",
    )

    dumped = ctx.model_dump(field_mode="llm")

    assert dumped == {
        "approval_kind": "exec",
        "approval_id": "approval-1",
        "tool_name": "exec",
        "command": "echo hello",
        "summary": "safe summary",
    }


def test_llm_approval_context_schema_llm_excludes_internal_fields() -> None:
    schema = LlmApprovalDecisionContext["llm"].model_json_schema()

    assert "prompt_purpose" not in (schema.get("properties") or {})
