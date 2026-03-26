#!/usr/bin/env python3
"""Demo script to test LLM merge resolution with sample timeline data.

This script demonstrates the AI merge functionality using sample timeline data
without requiring a full vit project or DaVinci Resolve.

Works with any OpenAI-compatible API:
- Local: Ollama, LM Studio, etc.
- Hosted: OpenAI, OpenRouter, Together AI, Groq, Azure, etc.
- Or use Google's Gemini API directly

Usage:
    # With Ollama (local)
    export VIT_LLM_URL=http://localhost:11434/v1
    export VIT_LLM_MODEL=qwen2.5-coder:14b
    python llm_demo.py

    # With OpenAI
    export VIT_LLM_URL=https://api.openai.com/v1
    export VIT_LLM_MODEL=gpt-4
    export GEMINI_API_KEY=your_openai_key
    python llm_demo.py

    # With OpenRouter
    export VIT_LLM_URL=https://openrouter.ai/api/v1
    export VIT_LLM_MODEL=anthropic/claude-3.5-sonnet
    export GEMINI_API_KEY=your_openrouter_key
    python llm_demo.py

    # With Gemini
    export GEMINI_API_KEY=your_gemini_key
    python llm_demo.py
"""

import json
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vit.ai_merge import (
    load_llm_config,
    ai_analyze_merge,
    LLMConfig,
)
from vit.validator import ValidationIssue


# Sample timeline data representing a realistic merge scenario
SAMPLE_BASE = {
    "cuts": {
        "video_tracks": [
            {
                "index": 1,
                "items": [
                    {
                        "id": "item_001",
                        "name": "Interview_A",
                        "media_ref": "sha256:abc123",
                        "record_start_frame": 0,
                        "record_end_frame": 720,
                        "source_start_frame": 0,
                        "source_end_frame": 720,
                        "track_index": 1,
                        "transform": {"Pan": 0.0, "Tilt": 0.0, "ZoomX": 1.0, "ZoomY": 1.0, "Opacity": 100.0}
                    },
                    {
                        "id": "item_002",
                        "name": "B_Roll_City",
                        "media_ref": "sha256:def456",
                        "record_start_frame": 720,
                        "record_end_frame": 1440,
                        "source_start_frame": 0,
                        "source_end_frame": 720,
                        "track_index": 1,
                        "transform": {"Pan": 0.0, "Tilt": 0.0, "ZoomX": 1.0, "ZoomY": 1.0, "Opacity": 100.0}
                    }
                ]
            }
        ]
    },
    "color": {
        "grades": {
            "item_001": {
                "num_nodes": 1,
                "nodes": [{"index": 1, "label": "Corrector", "lut": ""}],
                "saturation": 1.0,
                "contrast": 1.0
            },
            "item_002": {
                "num_nodes": 1,
                "nodes": [{"index": 1, "label": "Corrector", "lut": ""}],
                "saturation": 1.0,
                "contrast": 1.0
            }
        }
    },
    "audio": {
        "audio_tracks": [
            {
                "index": 1,
                "items": [
                    {
                        "id": "audio_001",
                        "media_ref": "sha256:abc123",
                        "start_frame": 0,
                        "end_frame": 720,
                        "volume": 0.0,
                        "pan": 0.0
                    },
                    {
                        "id": "audio_002",
                        "media_ref": "sha256:def456",
                        "start_frame": 720,
                        "end_frame": 1440,
                        "volume": 0.0,
                        "pan": 0.0
                    }
                ]
            }
        ]
    },
    "markers": {"markers": []},
    "metadata": {
        "project_name": "Documentary",
        "timeline_name": "Main Edit",
        "frame_rate": 24.0,
        "resolution": {"width": 1920, "height": 1080},
        "track_count": {"video": 1, "audio": 1}
    }
}


# "OURS" branch: Editor trimmed the interview and added a new B-roll clip
SAMPLE_OURS = {
    "cuts": {
        "video_tracks": [
            {
                "index": 1,
                "items": [
                    {
                        "id": "item_001",
                        "name": "Interview_A",
                        "media_ref": "sha256:abc123",
                        "record_start_frame": 0,
                        "record_end_frame": 600,  # Trimmed shorter
                        "source_start_frame": 0,
                        "source_end_frame": 600,
                        "track_index": 1,
                        "transform": {"Pan": 0.0, "Tilt": 0.0, "ZoomX": 1.0, "ZoomY": 1.0, "Opacity": 100.0}
                    },
                    {
                        "id": "item_002",
                        "name": "B_Roll_City",
                        "media_ref": "sha256:def456",
                        "record_start_frame": 600,
                        "record_end_frame": 1320,
                        "source_start_frame": 0,
                        "source_end_frame": 720,
                        "track_index": 1,
                        "transform": {"Pan": 0.0, "Tilt": 0.0, "ZoomX": 1.0, "ZoomY": 1.0, "Opacity": 100.0}
                    },
                    {
                        "id": "item_003",  # Added new clip
                        "name": "B_Roll_Harbor",
                        "media_ref": "sha256:ghi789",
                        "record_start_frame": 1320,
                        "record_end_frame": 1800,
                        "source_start_frame": 0,
                        "source_end_frame": 480,
                        "track_index": 1,
                        "transform": {"Pan": 0.0, "Tilt": 0.0, "ZoomX": 1.0, "ZoomY": 1.0, "Opacity": 100.0}
                    }
                ]
            }
        ]
    },
    "color": {
        "grades": {
            "item_001": {
                "num_nodes": 1,
                "nodes": [{"index": 1, "label": "Corrector", "lut": ""}],
                "saturation": 1.0,
                "contrast": 1.0
            },
            "item_002": {
                "num_nodes": 1,
                "nodes": [{"index": 1, "label": "Corrector", "lut": ""}],
                "saturation": 1.0,
                "contrast": 1.0
            }
            # Note: item_003 has no grade yet
        }
    },
    "audio": {
        "audio_tracks": [
            {
                "index": 1,
                "items": [
                    {
                        "id": "audio_001",
                        "media_ref": "sha256:abc123",
                        "start_frame": 0,
                        "end_frame": 600,  # Trimmed to match video
                        "volume": 0.0,
                        "pan": 0.0
                    },
                    {
                        "id": "audio_002",
                        "media_ref": "sha256:def456",
                        "start_frame": 600,
                        "end_frame": 1320,
                        "volume": 0.0,
                        "pan": 0.0
                    }
                ]
            }
        ]
    },
    "markers": {"markers": []},
    "metadata": {
        "project_name": "Documentary",
        "timeline_name": "Main Edit",
        "frame_rate": 24.0,
        "resolution": {"width": 1920, "height": 1080},
        "track_count": {"video": 1, "audio": 1}
    }
}


# "THEIRS" branch: Colorist graded the interview with warmer tones
SAMPLE_THEIRS = {
    "cuts": {
        "video_tracks": [
            {
                "index": 1,
                "items": [
                    {
                        "id": "item_001",
                        "name": "Interview_A",
                        "media_ref": "sha256:abc123",
                        "record_start_frame": 0,
                        "record_end_frame": 720,
                        "source_start_frame": 0,
                        "source_end_frame": 720,
                        "track_index": 1,
                        "transform": {"Pan": 0.0, "Tilt": 0.0, "ZoomX": 1.0, "ZoomY": 1.0, "Opacity": 100.0}
                    },
                    {
                        "id": "item_002",
                        "name": "B_Roll_City",
                        "media_ref": "sha256:def456",
                        "record_start_frame": 720,
                        "record_end_frame": 1440,
                        "source_start_frame": 0,
                        "source_end_frame": 720,
                        "track_index": 1,
                        "transform": {"Pan": 0.0, "Tilt": 0.0, "ZoomX": 1.0, "ZoomY": 1.0, "Opacity": 100.0}
                    }
                ]
            }
        ]
    },
    "color": {
        "grades": {
            "item_001": {
                "num_nodes": 2,
                "nodes": [
                    {"index": 1, "label": "Corrector", "lut": ""},
                    {"index": 2, "label": "Warm", "lut": ""}
                ],
                "saturation": 1.2,  # Boosted saturation
                "contrast": 1.1,
                "temperature": 5500,
                "tint": 5
            },
            "item_002": {
                "num_nodes": 1,
                "nodes": [{"index": 1, "label": "Corrector", "lut": ""}],
                "saturation": 1.0,
                "contrast": 1.0
            }
        }
    },
    "audio": {
        "audio_tracks": [
            {
                "index": 1,
                "items": [
                    {
                        "id": "audio_001",
                        "media_ref": "sha256:abc123",
                        "start_frame": 0,
                        "end_frame": 720,
                        "volume": -2.0,  # Reduced volume
                        "pan": 0.0
                    },
                    {
                        "id": "audio_002",
                        "media_ref": "sha256:def456",
                        "start_frame": 720,
                        "end_frame": 1440,
                        "volume": 0.0,
                        "pan": 0.0
                    }
                ]
            }
        ]
    },
    "markers": {
        "markers": [
            {
                "frame": 240,
                "color": "Blue",
                "name": "Color review",
                "note": "Check skin tones",
                "duration": 1
            }
        ]
    },
    "metadata": {
        "project_name": "Documentary",
        "timeline_name": "Main Edit",
        "frame_rate": 24.0,
        "resolution": {"width": 1920, "height": 1080},
        "track_count": {"video": 1, "audio": 1}
    }
}


def print_scenario():
    """Print the merge scenario description."""
    print("=" * 60)
    print("VIT AI MERGE DEMO")
    print("=" * 60)
    print()
    print("Scenario: Editor and Colorist working in parallel")
    print()
    print("BASE (common ancestor):")
    print("  - Interview clip (item_001): 0-720 frames")
    print("  - B-roll clip (item_002): 720-1440 frames")
    print()
    print("OURS (Editor's branch):")
    print("  - Trimmed interview to 0-600 frames")
    print("  - Added new B-roll (item_003): 1320-1800 frames")
    print("  - Audio trimmed to match")
    print()
    print("THEIRS (Colorist's branch):")
    print("  - Color graded interview with warmer tones")
    print("  - Boosted saturation to 1.2")
    print("  - Reduced interview audio volume to -2dB")
    print("  - Added marker for color review")
    print()
    print("Expected conflicts:")
    print("  - Cuts: Editor added/trimmed clips")
    print("  - Color: Colorist graded (but item_003 has no grade)")
    print("  - Audio: Both modified (trim + volume)")
    print()


def print_config():
    """Print current LLM configuration."""
    config = load_llm_config()
    print("-" * 60)
    print("LLM Configuration:")
    print("-" * 60)
    if config.provider == "openai":
        print(f"  Provider: OpenAI-compatible API")
        print(f"  URL: {config.base_url}")
        print(f"  Model: {config.model}")
    else:
        print(f"  Provider: Gemini")
        key_display = "***" if config.api_key else "(not set)"
        print(f"  API Key: {key_display}")
    print()


def main():
    print_scenario()
    print_config()

    # Check configuration
    config = load_llm_config()
    if config.provider == "gemini" and not config.api_key:
        print("ERROR: No LLM configured!")
        print()
        print("Options:")
        print()
        print("1. Use any OpenAI-compatible API (Ollama, OpenAI, OpenRouter, etc.):")
        print("   export VIT_LLM_URL=http://localhost:11434/v1  # or your API URL")
        print("   export VIT_LLM_MODEL=qwen2.5-coder:14b        # or your model")
        print("   export GEMINI_API_KEY=your_api_key            # if required")
        print()
        print("2. Use Gemini:")
        print("   export GEMINI_API_KEY=your_key_here")
        print()
        sys.exit(1)

    print("Sending merge analysis request to LLM...")
    if config.provider == "local":
        print("(This can take a while)")
    print()

    try:
        analysis = ai_analyze_merge(
            base_files=SAMPLE_BASE,
            ours_files=SAMPLE_OURS,
            theirs_files=SAMPLE_THEIRS,
            issues=[],  # No pre-detected validation issues
            conflicted_files=[]  # No git-level conflicts
        )

        if analysis is None:
            print("ERROR: AI analysis failed. Check your LLM configuration.")
            sys.exit(1)

        print("=" * 60)
        print("AI MERGE ANALYSIS RESULT")
        print("=" * 60)
        print()
        print(f"Summary: {analysis.summary}")
        print()

        print("Decisions:")
        for decision in analysis.decisions:
            icon = {"high": "✓", "medium": "~", "low": "?"}.get(decision.confidence, "?")
            print(f"  [{icon}] {decision.domain}: {decision.action}")
            print(f"      Confidence: {decision.confidence}")
            print(f"      Reasoning: {decision.reasoning}")
            if decision.options:
                print(f"      Options:")
                for opt in decision.options:
                    print(f"        {opt.key}) {opt.label}: {opt.description}")
            print()

        if analysis.resolved:
            print("Auto-resolved domains:")
            for domain in analysis.resolved.keys():
                print(f"  - {domain}")
            print()

        if analysis.needs_user_input():
            print("⚠ This merge requires user input for some decisions.")
        else:
            print("✓ All decisions can be auto-resolved!")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
