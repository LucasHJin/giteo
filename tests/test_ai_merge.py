"""Tests for ai_merge.py — AI-powered semantic merge resolution."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from giteo.ai_merge import (
    MergeAnalysis,
    MergeDecision,
    MergeOption,
    _build_analysis_prompt,
    _build_clarification_prompt,
    _extract_json_from_response,
    ai_analyze_merge,
    ai_resolve_clarifications,
)
from giteo.cli import _detect_overlapping_domains
from giteo.validator import ValidationIssue


class TestMergeOption:
    def test_to_dict(self):
        opt = MergeOption(key="A", label="Keep ours", description="Use current branch")
        result = opt.to_dict()
        assert result == {"key": "A", "label": "Keep ours", "description": "Use current branch"}

    def test_from_dict(self):
        data = {"key": "B", "label": "Keep theirs", "description": "Use incoming"}
        opt = MergeOption.from_dict(data)
        assert opt.key == "B"
        assert opt.label == "Keep theirs"
        assert opt.description == "Use incoming"

    def test_from_dict_missing_fields(self):
        data = {"key": "C"}
        opt = MergeOption.from_dict(data)
        assert opt.key == "C"
        assert opt.label == ""
        assert opt.description == ""


class TestMergeDecision:
    def test_to_dict_simple(self):
        decision = MergeDecision(
            domain="cuts",
            action="accept_theirs",
            confidence="high",
            reasoning="Only theirs modified cuts",
        )
        result = decision.to_dict()
        assert result["domain"] == "cuts"
        assert result["action"] == "accept_theirs"
        assert result["confidence"] == "high"
        assert result["reasoning"] == "Only theirs modified cuts"
        assert "options" not in result

    def test_to_dict_with_options(self):
        decision = MergeDecision(
            domain="color",
            action="needs_user_input",
            confidence="low",
            reasoning="Both changed saturation",
            options=[
                MergeOption(key="A", label="Keep ours", description="1.2"),
                MergeOption(key="B", label="Keep theirs", description="0.9"),
            ],
        )
        result = decision.to_dict()
        assert len(result["options"]) == 2
        assert result["options"][0]["key"] == "A"

    def test_from_dict(self):
        data = {
            "domain": "audio",
            "action": "merge",
            "confidence": "medium",
            "reasoning": "Compatible changes",
            "options": [{"key": "X", "label": "Option X", "description": "desc"}],
        }
        decision = MergeDecision.from_dict(data)
        assert decision.domain == "audio"
        assert decision.action == "merge"
        assert len(decision.options) == 1


class TestMergeAnalysis:
    def test_needs_user_input_false(self):
        analysis = MergeAnalysis(
            summary="Simple merge",
            decisions=[
                MergeDecision(domain="cuts", action="accept_theirs", confidence="high", reasoning=""),
            ],
        )
        assert analysis.needs_user_input() is False

    def test_needs_user_input_true(self):
        analysis = MergeAnalysis(
            summary="Complex merge",
            decisions=[
                MergeDecision(domain="cuts", action="accept_theirs", confidence="high", reasoning=""),
                MergeDecision(domain="color", action="needs_user_input", confidence="low", reasoning=""),
            ],
        )
        assert analysis.needs_user_input() is True

    def test_get_questions(self):
        analysis = MergeAnalysis(
            summary="Mixed merge",
            decisions=[
                MergeDecision(domain="cuts", action="accept_theirs", confidence="high", reasoning=""),
                MergeDecision(domain="color", action="needs_user_input", confidence="low", reasoning=""),
                MergeDecision(domain="audio", action="needs_user_input", confidence="low", reasoning=""),
            ],
        )
        questions = analysis.get_questions()
        assert len(questions) == 2
        assert questions[0].domain == "color"
        assert questions[1].domain == "audio"

    def test_get_auto_resolved(self):
        analysis = MergeAnalysis(
            summary="Mixed merge",
            decisions=[
                MergeDecision(domain="cuts", action="accept_theirs", confidence="high", reasoning=""),
                MergeDecision(domain="color", action="needs_user_input", confidence="low", reasoning=""),
            ],
        )
        auto = analysis.get_auto_resolved()
        assert len(auto) == 1
        assert auto[0].domain == "cuts"

    def test_from_dict(self):
        data = {
            "summary": "Test merge",
            "decisions": [
                {"domain": "cuts", "action": "accept_ours", "confidence": "high", "reasoning": "no changes"},
            ],
            "resolved": {"cuts": {"video_tracks": []}},
        }
        analysis = MergeAnalysis.from_dict(data)
        assert analysis.summary == "Test merge"
        assert len(analysis.decisions) == 1
        assert "cuts" in analysis.resolved


class TestExtractJsonFromResponse:
    def test_plain_json(self):
        content = '{"key": "value"}'
        result = _extract_json_from_response(content)
        assert result == {"key": "value"}

    def test_json_code_block(self):
        content = 'Some text\n```json\n{"key": "value"}\n```\nMore text'
        result = _extract_json_from_response(content)
        assert result == {"key": "value"}

    def test_generic_code_block(self):
        content = 'Text\n```\n{"key": "value"}\n```'
        result = _extract_json_from_response(content)
        assert result == {"key": "value"}

    def test_invalid_json_raises(self):
        content = "not valid json"
        with pytest.raises(json.JSONDecodeError):
            _extract_json_from_response(content)


class TestBuildAnalysisPrompt:
    def test_includes_all_file_versions(self):
        base = {"cuts": {"video_tracks": []}}
        ours = {"cuts": {"video_tracks": [{"index": 1}]}}
        theirs = {"cuts": {"video_tracks": [{"index": 2}]}}

        prompt = _build_analysis_prompt(base, ours, theirs, [], [])

        assert "BASE (common ancestor)" in prompt
        assert "OURS (current branch" in prompt
        assert "THEIRS (incoming branch" in prompt
        assert '"video_tracks"' in prompt

    def test_includes_conflicted_files(self):
        prompt = _build_analysis_prompt({}, {}, {}, [], ["timeline/cuts.json", "timeline/color.json"])
        assert "GIT CONFLICTED FILES" in prompt
        assert "timeline/cuts.json" in prompt
        assert "timeline/color.json" in prompt

    def test_includes_validation_issues(self):
        issues = [
            ValidationIssue(severity="error", category="orphaned_ref", message="Test issue"),
        ]
        prompt = _build_analysis_prompt({}, {}, {}, issues, [])
        assert "DETECTED VALIDATION ISSUES" in prompt
        assert "Test issue" in prompt


class TestBuildClarificationPrompt:
    def test_includes_user_answers(self):
        analysis = MergeAnalysis(
            summary="Test",
            decisions=[
                MergeDecision(
                    domain="color",
                    action="needs_user_input",
                    confidence="low",
                    reasoning="Both changed",
                    options=[
                        MergeOption(key="A", label="Keep ours", description="1.2"),
                        MergeOption(key="B", label="Keep theirs", description="0.9"),
                    ],
                ),
            ],
        )
        user_answers = {"color": "A"}
        ours = {"color": {"grades": {}}}
        theirs = {"color": {"grades": {}}}

        prompt = _build_clarification_prompt(analysis, user_answers, ours, theirs)

        assert "User chose option A" in prompt
        assert "Keep ours" in prompt


class TestDetectOverlappingDomains:
    def test_no_overlap(self):
        base = {"cuts": {"a": 1}, "color": {"b": 2}}
        ours = {"cuts": {"a": 1}, "color": {"b": 3}}  # Only ours changed color
        theirs = {"cuts": {"a": 2}, "color": {"b": 2}}  # Only theirs changed cuts

        result = _detect_overlapping_domains(base, ours, theirs)
        assert result == []

    def test_single_overlap(self):
        base = {"cuts": {"a": 1}, "color": {"b": 2}}
        ours = {"cuts": {"a": 2}, "color": {"b": 2}}  # Ours changed cuts
        theirs = {"cuts": {"a": 3}, "color": {"b": 2}}  # Theirs also changed cuts

        result = _detect_overlapping_domains(base, ours, theirs)
        assert result == ["cuts"]

    def test_multiple_overlaps(self):
        base = {"cuts": {"a": 1}, "color": {"b": 2}, "audio": {"c": 3}}
        ours = {"cuts": {"a": 2}, "color": {"b": 3}, "audio": {"c": 3}}
        theirs = {"cuts": {"a": 3}, "color": {"b": 4}, "audio": {"c": 3}}

        result = _detect_overlapping_domains(base, ours, theirs)
        assert "cuts" in result
        assert "color" in result
        assert "audio" not in result

    def test_no_changes(self):
        base = {"cuts": {"a": 1}}
        ours = {"cuts": {"a": 1}}
        theirs = {"cuts": {"a": 1}}

        result = _detect_overlapping_domains(base, ours, theirs)
        assert result == []


class TestAiAnalyzeMerge:
    @patch("giteo.ai_merge._get_genai_model")
    def test_successful_analysis(self, mock_get_model):
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "summary": "Editor made cuts, colorist graded",
            "decisions": [
                {"domain": "cuts", "action": "accept_theirs", "confidence": "high", "reasoning": "Only theirs changed"},
            ],
            "resolved": {"cuts": {"video_tracks": []}},
        })
        mock_model.generate_content.return_value = mock_response
        mock_get_model.return_value = mock_model

        result = ai_analyze_merge({}, {}, {}, [], [])

        assert result is not None
        assert result.summary == "Editor made cuts, colorist graded"
        assert len(result.decisions) == 1
        assert result.decisions[0].domain == "cuts"

    @patch("giteo.ai_merge._get_genai_model")
    def test_invalid_json_returns_none(self, mock_get_model):
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "not valid json"
        mock_model.generate_content.return_value = mock_response
        mock_get_model.return_value = mock_model

        result = ai_analyze_merge({}, {}, {}, [], [])
        assert result is None

    @patch("giteo.ai_merge._get_genai_model")
    def test_api_error_returns_none(self, mock_get_model):
        mock_get_model.side_effect = ValueError("No API key")

        result = ai_analyze_merge({}, {}, {}, [], [])
        assert result is None


class TestAiResolveClarifications:
    @patch("giteo.ai_merge._get_genai_model")
    def test_successful_clarification(self, mock_get_model):
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "color": {"grades": {"item_001": {"saturation": 1.2}}},
        })
        mock_model.generate_content.return_value = mock_response
        mock_get_model.return_value = mock_model

        analysis = MergeAnalysis(
            summary="Test",
            decisions=[
                MergeDecision(
                    domain="color",
                    action="needs_user_input",
                    confidence="low",
                    reasoning="Both changed",
                    options=[MergeOption(key="A", label="Ours", description="")],
                ),
            ],
        )
        user_answers = {"color": "A"}

        result = ai_resolve_clarifications(analysis, user_answers, {}, {})

        assert result is not None
        assert "color" in result

    @patch("giteo.ai_merge._get_genai_model")
    def test_no_questions_returns_empty(self, mock_get_model):
        analysis = MergeAnalysis(
            summary="Test",
            decisions=[
                MergeDecision(domain="cuts", action="accept_theirs", confidence="high", reasoning=""),
            ],
        )

        result = ai_resolve_clarifications(analysis, {}, {}, {})
        assert result == {}
        mock_get_model.assert_not_called()


class TestIntegration:
    """Integration tests with mocked Gemini API."""

    @patch("giteo.ai_merge._get_genai_model")
    def test_full_auto_resolve_flow(self, mock_get_model):
        """Test a merge where AI auto-resolves everything (no user input needed)."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "summary": "Clean merge: editor changed cuts, colorist changed color",
            "decisions": [
                {"domain": "cuts", "action": "accept_theirs", "confidence": "high", "reasoning": "Only incoming branch modified cuts"},
                {"domain": "color", "action": "accept_ours", "confidence": "high", "reasoning": "Only current branch modified color"},
            ],
            "resolved": {
                "cuts": {"video_tracks": [{"index": 1, "items": []}]},
                "color": {"grades": {"item_001": {"saturation": 1.1}}},
            },
        })
        mock_model.generate_content.return_value = mock_response
        mock_get_model.return_value = mock_model

        base = {"cuts": {"video_tracks": []}, "color": {"grades": {}}}
        ours = {"cuts": {"video_tracks": []}, "color": {"grades": {"item_001": {"saturation": 1.1}}}}
        theirs = {"cuts": {"video_tracks": [{"index": 1, "items": []}]}, "color": {"grades": {}}}

        analysis = ai_analyze_merge(base, ours, theirs, [], [])

        assert analysis is not None
        assert not analysis.needs_user_input()
        assert len(analysis.resolved) == 2

    @patch("giteo.ai_merge._get_genai_model")
    def test_mixed_flow_with_questions(self, mock_get_model):
        """Test a merge where some domains need user input."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "summary": "Both branches modified color grades",
            "decisions": [
                {"domain": "cuts", "action": "accept_theirs", "confidence": "high", "reasoning": "Only theirs changed"},
                {
                    "domain": "color",
                    "action": "needs_user_input",
                    "confidence": "low",
                    "reasoning": "Both branches changed saturation for clip item_001",
                    "options": [
                        {"key": "A", "label": "Keep ours (1.2)", "description": "Warmer tones"},
                        {"key": "B", "label": "Keep theirs (0.9)", "description": "Cooler tones"},
                    ],
                },
            ],
            "resolved": {
                "cuts": {"video_tracks": [{"index": 1, "items": []}]},
            },
        })
        mock_model.generate_content.return_value = mock_response
        mock_get_model.return_value = mock_model

        analysis = ai_analyze_merge({}, {}, {}, [], [])

        assert analysis is not None
        assert analysis.needs_user_input()
        assert len(analysis.get_questions()) == 1
        assert len(analysis.get_auto_resolved()) == 1
        assert analysis.get_questions()[0].domain == "color"
        assert len(analysis.get_questions()[0].options) == 2
