"""AI-powered semantic merge resolution using Gemini API or local LLM."""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .validator import ValidationIssue, format_issues


@dataclass
class MergeOption:
    """A single option for user to choose when resolving an ambiguous merge."""
    key: str
    label: str
    description: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "description": self.description}

    @classmethod
    def from_dict(cls, data: dict) -> "MergeOption":
        return cls(
            key=data.get("key", ""),
            label=data.get("label", ""),
            description=data.get("description", ""),
        )


@dataclass
class MergeDecision:
    """A per-domain merge decision from the AI analysis."""
    domain: str
    action: str  # "accept_ours", "accept_theirs", "merge", "needs_user_input"
    confidence: str  # "high", "medium", "low"
    reasoning: str
    options: List[MergeOption] = field(default_factory=list)
    resolved_data: Optional[dict] = None

    def to_dict(self) -> dict:
        result = {
            "domain": self.domain,
            "action": self.action,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }
        if self.options:
            result["options"] = [o.to_dict() for o in self.options]
        if self.resolved_data is not None:
            result["resolved_data"] = self.resolved_data
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "MergeDecision":
        options = [MergeOption.from_dict(o) for o in data.get("options", [])]
        return cls(
            domain=data.get("domain", ""),
            action=data.get("action", ""),
            confidence=data.get("confidence", "medium"),
            reasoning=data.get("reasoning", ""),
            options=options,
            resolved_data=data.get("resolved_data"),
        )


@dataclass
class MergeAnalysis:
    """Complete analysis result from the AI merge analyzer."""
    summary: str
    decisions: List[MergeDecision]
    resolved: Dict[str, dict] = field(default_factory=dict)

    def needs_user_input(self) -> bool:
        """Check if any decision requires user input."""
        return any(d.action == "needs_user_input" for d in self.decisions)

    def get_questions(self) -> List[MergeDecision]:
        """Get decisions that need user input."""
        return [d for d in self.decisions if d.action == "needs_user_input"]

    def get_auto_resolved(self) -> List[MergeDecision]:
        """Get decisions that were auto-resolved."""
        return [d for d in self.decisions if d.action != "needs_user_input"]

    @classmethod
    def from_dict(cls, data: dict) -> "MergeAnalysis":
        decisions = [MergeDecision.from_dict(d) for d in data.get("decisions", [])]
        return cls(
            summary=data.get("summary", ""),
            decisions=decisions,
            resolved=data.get("resolved", {}),
        )


@dataclass
class LLMConfig:
    """Configuration for LLM - either Gemini or OpenAI-compatible API."""
    provider: str  # "gemini" or "openai"
    api_key: Optional[str] = None  # For Gemini or OpenAI-compatible services
    base_url: Optional[str] = None  # For OpenAI-compatible API (e.g., Ollama, OpenRouter, etc.)
    model: Optional[str] = None  # Model name for OpenAI-compatible API


MERGE_ANALYSIS_SYSTEM_PROMPT = """\
You are a video editing timeline merge analyzer. You analyze merge conflicts \
and cross-domain semantic issues in vit timeline files, then produce structured \
decisions for each domain.

The timeline is split into domain files: cuts.json, color.json, audio.json, \
effects.json, markers.json, metadata.json.

Clips are linked across files by their "id" field (e.g., "item_001_000").

MERGE RULES:
- If a clip was deleted in one branch, remove its references from ALL domain files
- Audio clip boundaries must match their corresponding video clip boundaries  
- No two clips may overlap on the same track at the same timecode
- Linked video and audio clips must have matching speed values
- If a clip's speed changes, its record duration (timeline footprint) changes too — \
verify that record_end_frame - record_start_frame ≈ source_duration / (speed_percent / 100)
- Preserve as much work from both branches as possible
- When in doubt, prefer the branch that made the more structural changes

YOUR TASK:
1. Analyze what changed in each domain between BASE, OURS, and THEIRS
2. For each domain that has changes, make a decision:
   - "accept_ours" - keep the current branch's version
   - "accept_theirs" - take the incoming branch's version  
   - "merge" - combine changes from both (provide the merged data)
   - "needs_user_input" - genuinely ambiguous, user must choose

3. Assign confidence levels:
   - "high" - clear decision, only one branch modified this domain
   - "medium" - both modified but changes are compatible
   - "low" - conflicting changes that could go either way

4. For "needs_user_input" decisions, provide 2-4 clear options the user can choose from

RESPONSE FORMAT (return ONLY this JSON, no other text):
{
  "summary": "Brief description of what each branch changed",
  "decisions": [
    {
      "domain": "cuts",
      "action": "accept_theirs",
      "confidence": "high",
      "reasoning": "Only THEIRS modified cuts; OURS left it unchanged."
    },
    {
      "domain": "color",
      "action": "needs_user_input",
      "confidence": "low", 
      "reasoning": "Both branches changed saturation for clip item_001.",
      "options": [
        {"key": "A", "label": "Keep ours", "description": "saturation 1.2 (warmer)"},
        {"key": "B", "label": "Keep theirs", "description": "saturation 0.9 (cooler)"},
        {"key": "C", "label": "Merge", "description": "saturation 1.05 (balanced)"}
      ]
    }
  ],
  "resolved": {
    "cuts": { ...full resolved cuts.json data... },
    "audio": { ...full resolved audio.json data if applicable... }
  }
}

IMPORTANT:
- Include domain in "resolved" only for domains you can auto-resolve (high/medium confidence)
- For "needs_user_input" domains, do NOT include them in "resolved" yet
- Provide complete JSON for resolved domains, not just the changes
- Be decisive! Only use "needs_user_input" when truly ambiguous (conflicting values for same field)
"""


MERGE_CLARIFICATION_SYSTEM_PROMPT = """\
You are a video editing timeline merge resolver. The user has answered clarifying \
questions about ambiguous merge decisions. Now produce the final resolved JSON.

Use the user's answers to determine the final values for conflicting fields.
Return ONLY a JSON object with the resolved domain files.
"""


def _build_analysis_prompt(
    base_files: Dict[str, dict],
    ours_files: Dict[str, dict],
    theirs_files: Dict[str, dict],
    issues: List[ValidationIssue],
    conflicted_files: List[str],
) -> str:
    """Build the merge analysis prompt for structured AI response."""
    parts = []

    parts.append("=== BASE (common ancestor) ===")
    parts.append(json.dumps(base_files, indent=2, sort_keys=True))
    parts.append("")

    parts.append("=== OURS (current branch - the branch we're merging INTO) ===")
    parts.append(json.dumps(ours_files, indent=2, sort_keys=True))
    parts.append("")

    parts.append("=== THEIRS (incoming branch - the branch we're merging FROM) ===")
    parts.append(json.dumps(theirs_files, indent=2, sort_keys=True))
    parts.append("")

    if conflicted_files:
        parts.append("=== GIT CONFLICTED FILES ===")
        for f in conflicted_files:
            parts.append(f"  - {f}")
        parts.append("")

    if issues:
        parts.append("=== DETECTED VALIDATION ISSUES ===")
        parts.append(format_issues(issues))
        parts.append("")

    parts.append("Analyze the changes and return your structured decision JSON.")

    return "\n".join(parts)


def _build_clarification_prompt(
    analysis: MergeAnalysis,
    user_answers: Dict[str, str],
    ours_files: Dict[str, dict],
    theirs_files: Dict[str, dict],
) -> str:
    """Build the follow-up prompt after user answers clarifying questions."""
    parts = []

    parts.append("=== ORIGINAL ANALYSIS ===")
    parts.append(f"Summary: {analysis.summary}")
    parts.append("")

    parts.append("=== USER'S ANSWERS ===")
    for decision in analysis.get_questions():
        answer = user_answers.get(decision.domain, "")
        parts.append(f"Domain '{decision.domain}': User chose option {answer}")
        for opt in decision.options:
            if opt.key == answer:
                parts.append(f"  -> {opt.label}: {opt.description}")
    parts.append("")

    parts.append("=== OURS (current branch) ===")
    parts.append(json.dumps(ours_files, indent=2, sort_keys=True))
    parts.append("")

    parts.append("=== THEIRS (incoming branch) ===")
    parts.append(json.dumps(theirs_files, indent=2, sort_keys=True))
    parts.append("")

    parts.append(
        "Based on the user's choices, return the final resolved JSON for the "
        "domains that needed user input. Return a JSON object like: "
        '{"color": {...}, "markers": {...}}'
    )

    return "\n".join(parts)


# Keep old prompt for backwards compatibility with ai_merge()
MERGE_SYSTEM_PROMPT = MERGE_ANALYSIS_SYSTEM_PROMPT


def _build_merge_prompt(
    base_files: Dict[str, dict],
    ours_files: Dict[str, dict],
    theirs_files: Dict[str, dict],
    issues: List[ValidationIssue],
    conflicted_files: List[str],
) -> str:
    """Build the merge resolution prompt for the LLM (legacy format)."""
    return _build_analysis_prompt(
        base_files, ours_files, theirs_files, issues, conflicted_files
    )


def _load_api_key() -> Optional[str]:
    """Load GEMINI_API_KEY from environment or .env file."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key

    # Try loading from .env in project root
    from .core import find_project_root
    root = find_project_root()
    if root:
        env_path = os.path.join(root, ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GEMINI_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"')

    return None


def _load_env_value(key: str) -> Optional[str]:
    """Load a value from environment or .env file."""
    value = os.environ.get(key)
    if value:
        return value

    from .core import find_project_root
    root = find_project_root()
    if root:
        env_path = os.path.join(root, ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{key}="):
                        return line.split("=", 1)[1].strip().strip('"')

    return None


def load_llm_config() -> LLMConfig:
    """Load LLM configuration from environment or .env file.
    
    Priority:
    1. If VIT_LLM_URL is set, use OpenAI-compatible API (Ollama, OpenRouter, etc.)
    2. If GEMINI_API_KEY is set, use Gemini
    3. Default to Gemini (will fail gracefully if no key)
    """
    openai_url = _load_env_value("VIT_LLM_URL")
    openai_model = _load_env_value("VIT_LLM_MODEL") or "qwen2.5-coder:14b"
    gemini_key = _load_api_key()
    
    if openai_url:
        return LLMConfig(
            provider="openai",
            base_url=openai_url,
            model=openai_model
        )
    
    return LLMConfig(
        provider="gemini",
        api_key=gemini_key
    )


class LocalLLMModel:
    """Wrapper for local LLM using OpenAI-compatible API."""
    
    def __init__(self, client, model: str, system_instruction: str):
        self.client = client
        self.model = model
        self.system_instruction = system_instruction
    
    def generate_content(self, prompt: str):
        """Generate content using local LLM."""
        messages = [
            {"role": "system", "content": self.system_instruction},
            {"role": "user", "content": prompt}
        ]
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,  # Lower temperature for more deterministic JSON
            max_tokens=8192
        )
        
        # Return an object with .text attribute to match Gemini interface
        class ResponseWrapper:
            def __init__(self, text):
                self.text = text
        
        return ResponseWrapper(response.choices[0].message.content)


def _get_llm_model(system_prompt: str):
    """Get a configured LLM model (Gemini or OpenAI-compatible API).
    
    Returns a model object with a generate_content() method.
    """
    config = load_llm_config()
    
    if config.provider == "openai":
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "'openai' package not installed. Run: pip install openai"
            )
        
        if not config.base_url:
            raise ValueError(
                "VIT_LLM_URL not set. Add it to .env or set the environment variable.\n"
                "Example: VIT_LLM_URL=http://localhost:11434/v1"
            )
        
        client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key or "not-needed"
        )
        
        return LocalLLMModel(
            client=client,
            model=config.model or "qwen2.5-coder:14b",
            system_instruction=system_prompt
        )
    
    # Default to Gemini
    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError(
            "'google-generativeai' package not installed. Run: pip install google-generativeai\n"
            "Or set VIT_LLM_URL to use an OpenAI-compatible API instead."
        )

    if not config.api_key:
        raise ValueError(
            "GEMINI_API_KEY not set. Add it to .env or set the environment variable.\n"
            "Or set VIT_LLM_URL to use an OpenAI-compatible API instead."
        )

    genai.configure(api_key=config.api_key)

    return genai.GenerativeModel(
        "gemini-2.5-flash",
        system_instruction=system_prompt,
    )


def _get_genai_model(system_prompt: str):
    """Get a configured model (Gemini or local LLM), handling import and setup.
    
    This is an alias for _get_llm_model for backward compatibility.
    """
    return _get_llm_model(system_prompt)


def _extract_json_from_response(content: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks."""
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip())


def ai_analyze_merge(
    base_files: Dict[str, dict],
    ours_files: Dict[str, dict],
    theirs_files: Dict[str, dict],
    issues: List[ValidationIssue],
    conflicted_files: Optional[List[str]] = None,
) -> Optional[MergeAnalysis]:
    """Phase 1: Analyze merge and get structured decisions per domain.

    Args:
        base_files: Domain files from merge base
        ours_files: Domain files from current branch
        theirs_files: Domain files from incoming branch
        issues: Validation issues detected
        conflicted_files: Files with git merge conflicts

    Returns:
        MergeAnalysis with per-domain decisions, or None if analysis fails
    """
    try:
        model = _get_llm_model(MERGE_ANALYSIS_SYSTEM_PROMPT)
    except (ImportError, ValueError) as e:
        print(f"Error: {e}")
        return None

    prompt = _build_analysis_prompt(
        base_files, ours_files, theirs_files, issues, conflicted_files or []
    )

    try:
        response = model.generate_content(prompt)
        data = _extract_json_from_response(response.text)
        return MergeAnalysis.from_dict(data)

    except json.JSONDecodeError as e:
        print(f"Error: AI returned invalid JSON: {e}")
        return None
    except Exception as e:
        print(f"Error calling LLM API: {e}")
        return None


def ai_resolve_clarifications(
    analysis: MergeAnalysis,
    user_answers: Dict[str, str],
    ours_files: Dict[str, dict],
    theirs_files: Dict[str, dict],
) -> Optional[Dict[str, dict]]:
    """Phase 2: Resolve domains that needed user input based on user's answers.

    Args:
        analysis: The original MergeAnalysis with questions
        user_answers: Dict mapping domain name to chosen option key (e.g., {"color": "A"})
        ours_files: Domain files from current branch
        theirs_files: Domain files from incoming branch

    Returns:
        Dict of resolved domain files for the domains that needed clarification,
        or None if resolution fails
    """
    questions = analysis.get_questions()
    if not questions:
        return {}

    try:
        model = _get_llm_model(MERGE_CLARIFICATION_SYSTEM_PROMPT)
    except (ImportError, ValueError) as e:
        print(f"Error: {e}")
        return None

    prompt = _build_clarification_prompt(analysis, user_answers, ours_files, theirs_files)

    try:
        response = model.generate_content(prompt)
        return _extract_json_from_response(response.text)

    except json.JSONDecodeError as e:
        print(f"Error: AI returned invalid JSON: {e}")
        return None
    except Exception as e:
        print(f"Error calling LLM API: {e}")
        return None


def ai_merge(
    base_files: Dict[str, dict],
    ours_files: Dict[str, dict],
    theirs_files: Dict[str, dict],
    issues: List[ValidationIssue],
    conflicted_files: Optional[List[str]] = None,
) -> Optional[Dict[str, dict]]:
    """Use LLM API to resolve merge conflicts (legacy one-shot API).

    Args:
        base_files: Domain files from merge base
        ours_files: Domain files from current branch
        theirs_files: Domain files from incoming branch
        issues: Validation issues detected
        conflicted_files: Files with git merge conflicts

    Returns:
        Dict of resolved domain files, or None if resolution fails
    """
    config = load_llm_config()
    
    if config.provider == "openai":
        try:
            from openai import OpenAI
        except ImportError:
            print("Error: 'openai' package not installed. Run: pip install openai")
            return None
        
        if not config.base_url:
            print("Error: VIT_LLM_URL not set.")
            return None
        
        client = OpenAI(base_url=config.base_url, api_key=config.api_key or "not-needed")
        
        prompt = _build_merge_prompt(
            base_files, ours_files, theirs_files, issues, conflicted_files or []
        )
        
        try:
            model = LocalLLMModel(
                client=client,
                model=config.model or "qwen2.5-coder:14b",
                system_instruction=MERGE_SYSTEM_PROMPT
            )
            response = model.generate_content(prompt)
            return _extract_json_from_response(response.text)
        except Exception as e:
            print(f"Error calling OpenAI-compatible API: {e}")
            return None
    
    # Gemini path
    try:
        import google.generativeai as genai
    except ImportError:
        print("Error: 'google-generativeai' package not installed. Run: pip install google-generativeai")
        return None

    api_key = _load_api_key()
    if not api_key:
        print("Error: GEMINI_API_KEY not set. Add it to .env or set the environment variable.")
        return None

    genai.configure(api_key=api_key)

    prompt = _build_merge_prompt(
        base_files, ours_files, theirs_files, issues, conflicted_files or []
    )

    try:
        model = genai.GenerativeModel(
            "gemini-2.5-flash",
            system_instruction=MERGE_SYSTEM_PROMPT,
        )
        response = model.generate_content(prompt)

        # Extract JSON from response
        content = response.text

        # The LLM might wrap it in ```json ... ```
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        resolved = json.loads(content.strip())
        return resolved

    except json.JSONDecodeError as e:
        print(f"Error: AI returned invalid JSON: {e}")
        return None
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return None


def _display_analysis(analysis: MergeAnalysis, branch: str) -> None:
    """Display the AI's merge analysis to the user."""
    print(f"\n  AI Merge Analysis for '{branch}'")
    print("  " + "=" * 50)
    print(f"  Summary: {analysis.summary}")
    print()

    auto_resolved = analysis.get_auto_resolved()
    questions = analysis.get_questions()

    if auto_resolved:
        print("  Auto-resolved decisions:")
        for decision in auto_resolved:
            conf_icon = {"high": "+", "medium": "~", "low": "?"}.get(decision.confidence, "?")
            print(f"    [{conf_icon}] {decision.domain}: {decision.action}")
            print(f"        {decision.reasoning}")
        print()

    if questions:
        print("  Decisions requiring your input:")
        for decision in questions:
            print(f"    [?] {decision.domain}: {decision.reasoning}")
            for opt in decision.options:
                print(f"        {opt.key}) {opt.label}")
                if opt.description:
                    print(f"           {opt.description}")
        print()


def _prompt_user_choices(analysis: MergeAnalysis) -> Optional[Dict[str, str]]:
    """Prompt user for choices on ambiguous merge decisions.

    Returns dict of domain -> chosen option key, or None if user aborts.
    """
    questions = analysis.get_questions()
    if not questions:
        return {}

    answers = {}
    print("  Please choose an option for each ambiguous decision:")
    print()

    for decision in questions:
        valid_keys = [opt.key.upper() for opt in decision.options]
        valid_keys_str = "/".join(valid_keys)

        while True:
            try:
                choice = input(f"    {decision.domain} [{valid_keys_str}]: ").strip().upper()
            except (EOFError, KeyboardInterrupt):
                print("\n  Merge cancelled.")
                return None

            if choice in valid_keys:
                answers[decision.domain] = choice
                break
            else:
                print(f"      Invalid choice. Please enter one of: {valid_keys_str}")

    return answers


def _write_resolved_files(project_dir: str, resolved: Dict[str, dict]) -> None:
    """Write resolved domain files to disk."""
    from .json_writer import _write_json

    file_map = {
        "cuts": os.path.join(project_dir, "timeline", "cuts.json"),
        "color": os.path.join(project_dir, "timeline", "color.json"),
        "audio": os.path.join(project_dir, "timeline", "audio.json"),
        "effects": os.path.join(project_dir, "timeline", "effects.json"),
        "markers": os.path.join(project_dir, "timeline", "markers.json"),
        "metadata": os.path.join(project_dir, "timeline", "metadata.json"),
    }

    for key, filepath in file_map.items():
        if key in resolved:
            _write_json(filepath, resolved[key])


def merge_with_ai(
    project_dir: str,
    branch: str,
    base_files: Dict[str, dict],
    ours_files: Dict[str, dict],
    theirs_files: Dict[str, dict],
    issues: List[ValidationIssue],
    conflicted_files: List[str],
) -> bool:
    """Full AI merge flow with interactive clarification.

    Flow:
    1. Analyze merge with AI (get structured decisions per domain)
    2. Display summary and reasoning
    3. Auto-apply high-confidence decisions
    4. Prompt user for low-confidence decisions
    5. Resolve clarifications with AI if needed
    6. Show final diff, confirm, and write

    Returns True if merge was completed, False if aborted.
    """
    from .differ import format_diff

    print(f"\n  Analyzing merge with AI...")

    # Phase 1: Get structured analysis
    analysis = ai_analyze_merge(
        base_files, ours_files, theirs_files, issues, conflicted_files
    )

    if analysis is None:
        print("  AI merge analysis failed.")
        return False

    # Display analysis to user
    _display_analysis(analysis, branch)

    # Start building the final resolved state from auto-resolved decisions
    resolved = dict(analysis.resolved)

    # Phase 2: Handle user clarifications if needed
    if analysis.needs_user_input():
        user_answers = _prompt_user_choices(analysis)
        if user_answers is None:
            print("  AI merge aborted.")
            return False

        print("\n  Resolving your choices with AI...")
        clarified = ai_resolve_clarifications(
            analysis, user_answers, ours_files, theirs_files
        )

        if clarified is None:
            print("  Failed to resolve clarifications.")
            return False

        # Merge clarified results into resolved
        resolved.update(clarified)

    # Build final merged state
    merged_files = dict(ours_files)
    for key, value in resolved.items():
        merged_files[key] = value

    # Show final diff
    print("\n  Final changes to be applied:")
    print("  " + "-" * 50)
    diff_output = format_diff(ours_files, merged_files, branch_info=f"AI merge for '{branch}'")
    if diff_output.strip():
        print(diff_output)
    else:
        print("    (no changes)")
    print("  " + "-" * 50)

    # Confirm before writing
    try:
        response = input("\n  Apply these changes? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        response = "n"

    if response != "y":
        print("  AI merge declined.")
        return False

    # Write resolved files
    _write_resolved_files(project_dir, resolved)

    print("  AI merge resolution applied.")
    return True


# -- VIT UI: Branch Comparison Analysis ---------------------------------------

BRANCH_COMPARISON_PROMPT = """\
You are analyzing two branches of a video editing project to help a user decide how to merge them.

Branch A: "{branch_a}"
Branch B: "{branch_b}"

Changes in Branch A:
{changes_a}

Changes in Branch B:
{changes_b}

Analyze these changes and provide:
1. A brief summary of what each branch focused on
2. Whether there are potential conflicts
3. A recommendation for how to merge (which branch to prioritize, or if manual review is needed)

Return a JSON object with this structure:
{{
  "summary_a": "Brief description of what branch A changed",
  "summary_b": "Brief description of what branch B changed",
  "conflicts": ["list of potential conflict areas, if any"],
  "recommendation": "accept_a" | "accept_b" | "manual_review",
  "explanation": "Detailed explanation of the recommendation"
}}
"""


def analyze_branch_comparison(
    branch_a: str,
    branch_b: str,
    changes_a: Dict[str, list],
    changes_b: Dict[str, list],
) -> dict:
    """Analyze two branches and provide merge recommendation.

    Args:
        branch_a: Name of first branch
        branch_b: Name of second branch
        changes_a: Dict of changes in branch_a by category
        changes_b: Dict of changes in branch_b by category

    Returns:
        Dict with summary, conflicts, recommendation, and explanation
    """
    try:
        model = _get_llm_model("You are a video editing merge advisor.")
    except (ImportError, ValueError) as e:
        return {
            "summary_a": f"Branch with {sum(len(v) for v in changes_a.values())} changes",
            "summary_b": f"Branch with {sum(len(v) for v in changes_b.values())} changes",
            "conflicts": [],
            "recommendation": "manual_review",
            "explanation": f"AI analysis unavailable: {e}",
        }

    # Format changes for the prompt
    def format_changes(changes: dict) -> str:
        lines = []
        for category, items in changes.items():
            if items:
                lines.append(f"  {category.upper()}: {len(items)} changes")
                for item in items[:5]:  # Limit to first 5 per category
                    lines.append(f"    - {item.get('name', item.get('id', 'unknown'))}: {item.get('type', 'modified')}")
                if len(items) > 5:
                    lines.append(f"    - ... and {len(items) - 5} more")
        return "\n".join(lines) if lines else "  No changes"

    prompt = BRANCH_COMPARISON_PROMPT.format(
        branch_a=branch_a,
        branch_b=branch_b,
        changes_a=format_changes(changes_a),
        changes_b=format_changes(changes_b),
    )

    try:
        response = model.generate_content(prompt)
        return _extract_json_from_response(response.text)
    except Exception as e:
        # Fallback to simple heuristic
        a_count = sum(len(v) for v in changes_a.values())
        b_count = sum(len(v) for v in changes_b.values())

        if a_count == 0 and b_count > 0:
            return {
                "summary_a": "No changes",
                "summary_b": f"{b_count} changes",
                "conflicts": [],
                "recommendation": "accept_b",
                "explanation": f"Only {branch_b} has changes.",
            }
        elif b_count == 0 and a_count > 0:
            return {
                "summary_a": f"{a_count} changes",
                "summary_b": "No changes",
                "conflicts": [],
                "recommendation": "accept_a",
                "explanation": f"Only {branch_a} has changes.",
            }
        else:
            return {
                "summary_a": f"{a_count} changes",
                "summary_b": f"{b_count} changes",
                "conflicts": ["Both branches have changes"],
                "recommendation": "manual_review",
                "explanation": f"Both branches have changes. Manual review recommended. (AI error: {e})",
            }


# -- VIT UI: Commit Classification --------------------------------------------

COMMIT_CLASSIFICATION_PROMPT = """\
You are classifying a video editing commit to determine its primary focus area.

Commit: {hash}
Message: {message}
Files changed: {files}

Based on the files changed and commit message, determine the PRIMARY category of this commit.

Categories:
- "audio": Changes to audio tracks, volume, pan, audio effects
- "video": Changes to video clips, cuts, transforms, track positions
- "color": Changes to color grading, LUTs, color correction

Return a JSON object:
{{
  "category": "audio" | "video" | "color",
  "confidence": "high" | "medium" | "low",
  "reasoning": "Brief explanation"
}}
"""


def classify_commit_type(
    commit_hash: str,
    files_changed: List[str],
    message: str = "",
) -> str:
    """Use LLM to classify a commit's primary category.

    Args:
        commit_hash: Short commit hash
        files_changed: List of files changed in the commit
        message: Commit message

    Returns:
        Category string: "audio", "video", or "color"
    """
    # Quick heuristic check first
    audio_files = [f for f in files_changed if "audio" in f.lower()]
    color_files = [f for f in files_changed if "color" in f.lower()]
    video_files = [f for f in files_changed if "cuts" in f.lower() or "video" in f.lower()]

    # If clear majority, skip AI
    total = len(files_changed)
    if total > 0:
        if len(audio_files) > total * 0.6:
            return "audio"
        if len(color_files) > total * 0.6:
            return "color"
        if len(video_files) > total * 0.6:
            return "video"

    # Use AI for ambiguous cases
    try:
        model = _get_llm_model("You are a video editing commit classifier.")
    except (ImportError, ValueError):
        # Fallback to simple heuristic
        from .core import categorize_commit
        return categorize_commit(files_changed)

    prompt = COMMIT_CLASSIFICATION_PROMPT.format(
        hash=commit_hash,
        message=message or "No message",
        files=", ".join(files_changed) if files_changed else "None",
    )

    try:
        response = model.generate_content(prompt)
        data = _extract_json_from_response(response.text)
        category = data.get("category", "video")
        if category in ("audio", "video", "color"):
            return category
        return "video"
    except Exception:
        from .core import categorize_commit
        return categorize_commit(files_changed)


# -- VIT CLI: AI Commit Message Suggestion ------------------------------------

COMMIT_MESSAGE_PROMPT = """\
You are a video editing version control assistant. Based on the timeline changes below, \
write a short, descriptive commit message (1 line, max 72 characters).

Use video editing terminology. Focus on WHAT changed, not technical details.
Do NOT include prefixes like "vit:" or "feat:".

Examples of good messages:
- "Add B-roll on V2, trim interview end point"
- "Color grade interview clips, boost saturation"
- "Adjust dialogue levels, pan ambient to rear"
- "Add marker notes for review session"

Timeline changes:
{diff_text}

Return ONLY the commit message text, nothing else.
"""


def suggest_commit_message(diff_text: str) -> Optional[str]:
    """Use LLM to suggest a commit message based on timeline diff.

    Args:
        diff_text: Human-readable diff output from differ.py

    Returns:
        Suggested commit message string, or None if AI unavailable.
    """
    if not diff_text or not diff_text.strip():
        return None

    try:
        model = _get_llm_model("You are a video editing commit message writer.")
    except (ImportError, ValueError):
        return None

    prompt = COMMIT_MESSAGE_PROMPT.format(diff_text=diff_text[:2000])

    try:
        response = model.generate_content(prompt)
        message = response.text.strip().strip('"').strip("'")
        # Enforce max length
        if len(message) > 72:
            message = message[:69] + "..."
        return message
    except Exception:
        return None


# -- VIT CLI: AI Log Summary --------------------------------------------------

LOG_SUMMARY_PROMPT = """\
You are a video editing version control assistant. Summarize these recent commits \
into a brief natural-language overview (2-3 sentences max) for a video editing team.

Use video editing terminology. Group related work together.

Commits (newest first):
{commits_text}

Return ONLY the summary text, nothing else.
"""


def summarize_log(commits_text: str) -> Optional[str]:
    """Use LLM to summarize recent commit history.

    Args:
        commits_text: Formatted git log output

    Returns:
        Natural language summary, or None if AI unavailable.
    """
    if not commits_text or not commits_text.strip():
        return None

    try:
        model = _get_llm_model("You are a video editing project summarizer.")
    except (ImportError, ValueError):
        return None

    prompt = LOG_SUMMARY_PROMPT.format(commits_text=commits_text[:3000])

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception:
        return None
