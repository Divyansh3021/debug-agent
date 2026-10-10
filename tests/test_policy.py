from debug_agent.policy import approval_decision, evaluate_policy


def test_missing_behavioral_evidence_needs_data():
    decision = evaluate_policy(
        {"severity": "sev2", "environment": "production"},
        {"capabilities": {"metrics": 1, "traces": 0, "logs": 0}},
    )
    assert decision["autonomy"] == "needs_data"


def test_sev1_is_observe_only_when_evidence_exists():
    decision = evaluate_policy(
        {"severity": "sev1", "environment": "production", "sensitive_domains": ["payments"]},
        {"capabilities": {"traces": 1}},
    )
    assert decision["autonomy"] == "observe_only"


def test_production_payments_are_propose_only():
    decision = evaluate_policy(
        {"severity": "sev2", "environment": "production", "sensitive_domains": ["payments"]},
        {"capabilities": {"logs": 2}},
    )
    assert decision["autonomy"] == "propose"


def test_staging_without_sensitive_domain_can_auto_fix():
    decision = evaluate_policy(
        {"severity": "sev3", "environment": "staging", "sensitive_domains": []},
        {"capabilities": {"traces": 1}},
    )
    assert decision["autonomy"] == "auto_fix"


def test_approval_matrix():
    assert approval_decision(autonomy="propose", risk="medium", validation_status="passed")["decision"] == "draft_pr"
    assert approval_decision(autonomy="auto_fix", risk="low", validation_status="passed")["decision"] == "auto_apply"
    assert approval_decision(autonomy="auto_fix", risk="medium", validation_status="passed")["decision"] == "draft_pr"
    assert approval_decision(autonomy="auto_fix", risk="high", validation_status="passed")["decision"] == "escalate"
    assert approval_decision(autonomy="propose", risk="low", validation_status="failed")["decision"] == "escalate"
