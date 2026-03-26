# AI-Powered Semantic Merge

## Known Edge Cases Git Can't Handle

| Problem | Example | Why git fails |
|---------|---------|---------------|
| Orphaned references | Editor deletes clip `item_003` in `cuts.json`; colorist graded `item_003` in `color.json` | Merge "succeeds" but color grade points at nothing |
| Audio/video sync | Editor trims clip in `cuts.json`; sound designer adjusted audio for old length in `audio.json` | Merge succeeds but audio out of sync |
| Overlapping clips | Two editors add clips to same track at same timecode | Git may merge both → invalid timeline |
| Track count mismatch | One branch adds V3 track, another doesn't | `metadata.json` conflicts, structural issue in `cuts.json` |
| Speed/audio mismatch | Editor changes speed in `cuts.json`; sound designer adjusted audio for old speed | Video/audio speed values diverge |
| Speed/duration stale | Editor changes speed; parallel branch modifies same clip's duration | Merged record_end_frame doesn't match speed-adjusted source |

## Merge Flow

```
vit merge <branch>
    │
    ▼
1. Try git merge
    │
    ├─ Git conflict? ──────────────────────┐
    │                                       │
    ▼                                       ▼
2. Git merge succeeded              3. Extract ours/theirs/base
    │                                  for conflicting files
    ▼                                       │
4. Post-merge validation                    │
   (validator.py)                           │
    │                                       │
    ├─ Valid? → Done ✓                      │
    │                                       │
    ├─ Issues found? ──────────────────────►│
    │                                       │
    ▼                                       ▼
5. Send to LLM (ai_merge.py)
   - All domain JSON files (both versions)
   - Schema context
   - List of detected issues
   - Instructions for semantic resolution
    │
    ▼
6. LLM returns resolved JSON
    │
    ▼
7. Show user what AI changed, ask for confirmation
    │
    ▼
8. Write resolved files, commit
```

## LLM Prompt Template

```python
prompt = f"""
You are resolving a merge conflict in a video editing timeline.

The timeline is split into domain files: cuts.json, color.json, audio.json, etc.
Clips are linked across files by their "id" field.

BASE (common ancestor):
{base_json}

OURS (current branch):
{ours_json}

THEIRS (incoming branch):
{theirs_json}

DETECTED ISSUES:
{validation_issues}

Rules:
- If a clip was deleted in one branch, remove its references from ALL domain files
- Audio clip boundaries must match their corresponding video clip boundaries
- No two clips may overlap on the same track at the same timecode
- Preserve as much work from both branches as possible
- When in doubt, prefer the branch that made the more recent commit

Return the resolved JSON for each domain file.
"""
```

## LLM Provider Support

Vit supports multiple LLM providers:

| Provider | Setup | Best For |
|----------|-------|----------|
| **Gemini** | `GEMINI_API_KEY=your_key` | Default, no extra dependencies |
| **OpenAI-compatible** | `VIT_LLM_URL=<url>` `VIT_LLM_MODEL=<model>` | Ollama (local), OpenAI, OpenRouter, Together AI, Groq, Azure |

### Configuration Examples

```bash
# Gemini (default)
export GEMINI_API_KEY=your_key_here

# Ollama (local)
export VIT_LLM_URL=http://localhost:11434/v1
export VIT_LLM_MODEL=qwen2.5-coder:14b

# OpenAI
export VIT_LLM_URL=https://api.openai.com/v1
export VIT_LLM_MODEL=gpt-4
export GEMINI_API_KEY=your_openai_key  # Uses same env var for API key

# OpenRouter
export VIT_LLM_URL=https://openrouter.ai/api/v1
export VIT_LLM_MODEL=anthropic/claude-3.5-sonnet
export GEMINI_API_KEY=your_openrouter_key
```

### Requirements

- **Gemini**: `pip install google-generativeai`
- **OpenAI-compatible**: `pip install openai`

## Implementation Notes

- Uses Gemini API via `google-generativeai` Python SDK, or any OpenAI-compatible API via `openai` Python SDK
- Called only when git can't merge cleanly OR post-merge validation finds issues
- For common case (different domains, no cross-references), AI is never invoked
- User always sees what the AI changed before commit
- Falls back to manual conflict resolution if AI merge declined
