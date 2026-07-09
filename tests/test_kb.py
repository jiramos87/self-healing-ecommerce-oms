"""Runbook retrieval tests."""

from __future__ import annotations

from app.kb import CLASS_TO_FILE, retrieve_runbook


def test_retrieve_by_class() -> None:
    for class_name, filename in CLASS_TO_FILE.items():
        result = retrieve_runbook(class_name)
        assert result["class"] == class_name
        assert result["path"].endswith(filename)
        assert "## Symptom" in result["content"]
        assert "## Diagnosis guidance" in result["content"]
        assert "## Fix policy" in result["content"]


def test_cancelled_policy_is_no_action() -> None:
    result = retrieve_runbook("cancelled_order")
    assert "Expected behavior, no action, no artifact" in result["content"]


def test_keyword_fallback() -> None:
    result = retrieve_runbook("customer phone could not be normalized")
    assert result["class"] == "phone_format"


def test_unknown_input_defaults_sensibly() -> None:
    result = retrieve_runbook("completely unrelated gibberish xyz")
    assert result["class"] == "unknown_region"
    assert "## Symptom" in result["content"]
