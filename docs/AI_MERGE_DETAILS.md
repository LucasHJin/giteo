# AI-Powered Semantic Merge — Details

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
giteo merge <branch>
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

## Implementation Notes

- Uses Gemini API via `google-generativeai` Python SDK
- Called only when git can't merge cleanly OR post-merge validation finds issues
- For common case (different domains, no cross-references), AI is never invoked
- User always sees what the AI changed before commit
- Falls back to manual conflict resolution if AI merge declined
