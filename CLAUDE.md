# Giteo — Git for Video Editing

## Project Purpose

Giteo brings git-style version control to video editing. Traditional video editing workflows are linear — one person finishes before the next can start. Giteo lets collaborators (editors, colorists, sound designers) work in parallel on branches and merge their changes, just like software developers do with code.

**Core insight:** Version control the *edit decisions and timeline metadata* (as structured JSON), not raw video files. Use actual `git` as the backend.

**What this is NOT:** "Git for raw video files." We never version control media binaries. We version control the timeline decisions — clip placements, color grades, audio levels, markers — as lightweight JSON.

### Target Users
- Video editors (cutting, arranging)
- Colorists (color grading)
- Sound designers (audio levels, effects)
- Assistant editors (markers, notes, organization)

### The Problem
1. Editor A finishes a rough cut → hands off to Colorist B → hands off to Sound Designer C → sequential, slow
2. If Editor A wants to try a different cut while B is grading, they can't without breaking B's work
3. No structured history of what changed, when, or why
4. No way to merge parallel creative work

### The Solution
Each collaborator works on a branch. Giteo serializes the NLE's timeline state into domain-split JSON files (cuts, color, audio, etc.) so that different roles naturally edit different files. Git merges them cleanly.

---

## Product Philosophy

- **Metadata, not media** — timeline decisions are the merge surface, not video files
- **Use git, don't reimplement it** — git handles commits, branches, merges, diffs. We handle serialization. All user-facing commands go through `giteo`, never raw `git`.
- **Domain-split JSON** — separate files for cuts, color, audio, effects, markers. Different roles = different files = clean merges.
- **AI-assisted semantic merging** — git handles the easy merges; when cross-domain conflicts arise (e.g., a deleted clip still referenced in color grading), an LLM resolves them intelligently.
- **Snapshot-based** — each commit captures full timeline state. Simpler than event sourcing, works naturally with git.
- **No media storage, no database** — we version control JSON metadata only. Video/image files stay on disk where they are. Git is the only persistence layer.
- **CLI-first** — no GUI overhead. Resolve plugin scripts serve as in-NLE UI.
- **Additive integration** — work with existing NLEs (DaVinci Resolve), don't replace them
- **Every phase is demo-able** — the system is useful at every stage of completion

---

## System Architecture

```
┌──────────────────────────────────┐
│  DaVinci Resolve (Free)          │
│  Workspace > Scripts menu        │
│  ┌────────────────────────────┐  │
│  │ Giteo: Save Version        │  │
│  │ Giteo: New Branch          │  │
│  │ Giteo: Switch Branch       │  │
│  │ Giteo: Merge               │  │
│  │ Giteo: Show History        │  │
│  └──────────┬─────────────────┘  │
└─────────────┼────────────────────┘
              │ Resolve Python API
              ▼
┌──────────────────────────────────┐
│  giteo-core (Python)             │
│                                  │
│  Serializer:    serializer.py     │
│  Deserializer:  deserializer.py  │
│  JSON writer:   json_writer.py   │
│  Git wrapper:   core.py          │
│  AI merge:      ai_merge.py      │
│  Diff formatter: differ.py       │
│  CLI:           cli.py           │
└──────────┬───────────────────────┘
           │ subprocess
           ▼
┌──────────────────────────────────┐
│  Git (system binary)             │
│  Standard .git repo on JSON files│
│  Share via GitHub for remote     │
└──────────────────────────────────┘
```

No server, no database, no web UI. Teams share repos via GitHub just like code.

### DaVinci Resolve Free — Integration Details

Scripts placed in `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit/` appear in **Workspace > Scripts** menu. When run from this menu, scripts receive `resolve`, `fusion`, and `bmd` variables — full timeline API access. No Studio license required.

### Fallback Strategy

If Resolve Free's scripting API proves too limited, pivot to Final Cut Pro X via FCPXML export/import (File > Export XML / File > Import > XML), parsed with OpenTimelineIO. The giteo-core layer and domain-split JSON format stay the same — only the serializer/deserializer changes.

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.x | Resolve API is Python |
| Version control | System `git` binary | Battle-tested; don't reimplement |
| Git interaction | `subprocess` | No extra dependencies |
| Data format | JSON (`indent=2, sort_keys=True`) | Human-readable, git-diffable |
| AI merge | Gemini API (`google-generativeai` Python SDK) | Semantic conflict resolution |
| Terminal output | `rich` | Pretty diffs and logs |
| NLE integration | Resolve Workspace Scripts | Scripts appear in Resolve's menu |
| Storage | Local filesystem only | No database, no media storage — just JSON in a git repo |

---

## Repository Structure

```
giteo/
├── giteo/                          # Python package
│   ├── __init__.py
│   ├── cli.py                      # CLI entry point
│   ├── core.py                     # Git wrapper (subprocess)
│   ├── models.py                   # Dataclasses for timeline entities
│   ├── serializer.py               # Resolve timeline → domain-split JSON
│   ├── deserializer.py             # Domain-split JSON → Resolve timeline
│   ├── json_writer.py              # Write domain-split JSON files
│   ├── ai_merge.py                 # LLM-powered semantic merge resolution
│   ├── validator.py                # Post-merge validation (orphaned refs, sync issues)
│   └── differ.py                   # Human-readable diff formatting
├── resolve_plugin/                 # Scripts for Resolve's Scripts menu
│   ├── giteo_commit.py
│   ├── giteo_branch.py
│   ├── giteo_merge.py
│   ├── giteo_status.py
│   └── giteo_restore.py
├── tests/
│   ├── test_serializer.py
│   ├── test_core.py
│   ├── test_differ.py
│   └── mock_resolve.py
├── setup.py
├── CLAUDE.md
└── README.md
```

### Giteo-managed project structure (user's video project)

```
my-video-project/                   # This IS the git repo
├── .git/
├── .giteo/
│   └── config.json                 # Project config
├── timeline/
│   ├── cuts.json                   # Clip placements, in/out points, tracks, speed changes
│   ├── color.json                  # Color grading data per clip
│   ├── audio.json                  # Audio levels, effects
│   ├── effects.json                # Video effects, transitions
│   ├── markers.json                # Markers and notes
│   └── metadata.json               # Frame rate, resolution, settings
└── assets/
    └── manifest.json               # Media file registry (paths, checksums)
```

---

## Domain Model

### Domain-Split JSON — Why It Matters

Instead of one `timeline.json`, we split into files by editing domain. This is the key to conflict-free merges:

| File | What it tracks | Who typically edits it |
|------|---------------|----------------------|
| `cuts.json` | Clip placements, in/out points, track assignments, transforms, speed/retime | Editor |
| `color.json` | Color grading data per clip | Colorist |
| `audio.json` | Audio tracks, levels, panning | Sound designer |
| `effects.json` | Video effects, transitions | Editor / VFX |
| `markers.json` | Timeline markers, notes, comments | Anyone |
| `metadata.json` | Frame rate, resolution, timecode, track counts | Rarely changes |

When Editor A changes `cuts.json` on `main` and Colorist B changes `color.json` on `color-grade`, `git merge` combines them with zero conflicts.

### JSON Schemas

**`timeline/cuts.json`**
```json
{
  "video_tracks": [
    {
      "index": 1,
      "items": [
        {
          "id": "item_001",
          "name": "Interview_A_001",
          "media_ref": "sha256:abcdef...",
          "record_start_frame": 0,
          "record_end_frame": 720,
          "source_start_frame": 100,
          "source_end_frame": 820,
          "track_index": 1,
          "transform": {
            "Pan": 0.0,
            "Tilt": 0.0,
            "ZoomX": 1.0,
            "ZoomY": 1.0,
            "Opacity": 100.0,
            "RotationAngle": 15.0,
            "CropLeft": 50.0,
            "CropRight": 50.0,
            "FlipX": true
          },
          "speed": {
            "speed_percent": 50.0,
            "retime_process": 3,
            "retime_process_name": "optical_flow",
            "motion_estimation": 4,
            "motion_estimation_name": "enhanced_better"
          },
          "composite_mode": 5,
          "composite_mode_name": "screen"
        }
      ]
    }
  ]
}
```

**`timeline/color.json`**
```json
{
  "grades": {
    "item_001": {
      "contrast": 1.0,
      "saturation": 1.1,
      "lut": null
    }
  }
}
```

**`timeline/audio.json`**
```json
{
  "audio_tracks": [
    {
      "index": 1,
      "items": [
        {
          "id": "audio_001",
          "media_ref": "sha256:abcdef...",
          "start_frame": 0,
          "end_frame": 720,
          "volume": 0.0,
          "pan": 0.0
        }
      ]
    }
  ]
}
```

**`timeline/markers.json`**
```json
{
  "markers": [
    {
      "frame": 240,
      "color": "Blue",
      "name": "Fix jump cut",
      "note": "Transition feels abrupt",
      "duration": 1
    }
  ]
}
```

**`timeline/metadata.json`**
```json
{
  "project_name": "My Documentary",
  "timeline_name": "Main Edit v3",
  "frame_rate": 24.0,
  "resolution": { "width": 1920, "height": 1080 },
  "start_timecode": "01:00:00:00",
  "track_count": { "video": 3, "audio": 4 }
}
```

**`assets/manifest.json`**
```json
{
  "assets": {
    "sha256:abcdef...": {
      "filename": "Interview_A_001.mov",
      "original_path": "/Volumes/Media/Interview_A_001.mov",
      "duration_frames": 14400,
      "codec": "ProRes 422",
      "resolution": "1920x1080"
    }
  }
}
```

---

## Giteo Commands

All interaction goes through `giteo`. Users never run raw `git`.

| User action | Giteo command | Under the hood |
|-------------|---------------|----------------|
| Start tracking | `giteo init` | Create `.giteo/`, `git init`, initial snapshot |
| Stage changes | `giteo add` | Serialize timeline → JSON, `git add timeline/ assets/` |
| Save a version | `giteo commit -m "rough cut done"` | `giteo add` + `git commit` |
| Try different approach | `giteo branch experiment` | `git checkout -b experiment` |
| Switch versions | `giteo checkout main` | `git checkout main`, deserialize JSON → Resolve timeline |
| Combine work | `giteo merge color-grade` | `git merge` → validate → AI resolve if needed |
| See what changed | `giteo diff` | `git diff` formatted as human-readable timeline changes |
| View history | `giteo log` | `git log` with giteo formatting |
| Undo last version | `giteo revert` | `git revert HEAD` |
| Share to remote | `giteo push` | `git push` (standard GitHub remote) |
| Get remote changes | `giteo pull` | `git pull`, deserialize updated JSON → Resolve timeline |
| Check state | `giteo status` | `git status` with giteo formatting |

---

## Resolve Plugin Scripts

Each script in `resolve_plugin/` is a standalone Python file that runs from Resolve's Workspace > Scripts menu. Pattern:

```python
# The resolve variable is injected by DaVinci Resolve when running from Scripts menu
import sys
import os

# Add giteo package to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from giteo.serializer import serialize_timeline
from giteo.core import git_add, git_commit

project = resolve.GetProjectManager().GetCurrentProject()
timeline = project.GetCurrentTimeline()

# Serialize and commit
serialize_timeline(timeline, project_dir)
git_add(project_dir, ["timeline/", "assets/"])
git_commit(project_dir, message)
```

Install scripts by symlinking to:
`~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit/`

---

## AI-Powered Semantic Merging

Git's text-based merge works well when different people edit different domain files (cuts vs. color). But it breaks down when changes are semantically coupled across files. This is where AI steps in.

### Known Edge Cases Git Can't Handle

| Problem | Example | Why git fails |
|---------|---------|---------------|
| Orphaned references | Editor deletes clip `item_003` in `cuts.json`; colorist graded `item_003` in `color.json` | Merge "succeeds" (different files) but color grade points at nothing |
| Audio/video sync | Editor trims clip in `cuts.json`; sound designer adjusted audio for the old length in `audio.json` | Merge succeeds but audio is out of sync with video |
| Overlapping clips | Two editors add clips to same track at same timecode | Git may merge both additions into `cuts.json`, producing an invalid timeline |
| Track count mismatch | One branch adds V3 track, another doesn't | `metadata.json` conflicts, but the structural issue is in `cuts.json` |
| Speed/audio mismatch | Editor changes clip speed in `cuts.json`; sound designer adjusted audio for the old speed in `audio.json` | Merge succeeds but video/audio speed values diverge |
| Speed/duration stale | Editor changes clip speed but a parallel branch modifies the same clip's duration | Merged record_end_frame doesn't match the speed-adjusted source duration |

### Merge Flow

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

### What the LLM Receives

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

### Implementation (`ai_merge.py`)

- Uses Gemini API via `google-generativeai` Python SDK
- Called only when git can't merge cleanly OR post-merge validation finds issues
- For the common case (different domains, no cross-references), AI is never invoked — git handles it
- User always sees what the AI changed before it's committed
- Falls back to manual conflict resolution if AI merge is declined

---

## Storage Model

**No database. No media storage.** The entire system is JSON files in a git repo.

- **Timeline metadata** (`timeline/*.json`): version controlled via git. This is all giteo manages.
- **Media files** (video, audio, images): stay wherever they are on disk. Never copied, moved, or versioned by giteo. `assets/manifest.json` records their paths and checksums so we know what media the timeline references — but the files themselves are the user's responsibility.
- **Persistence**: git is the database. Commit history = version history. Branches = parallel workstreams. No Postgres, no SQLite, no Redis.
- **Sharing**: push/pull to GitHub. Collaborators need the same media files on their machines (e.g., shared drive, Dropbox, NAS), but the giteo repo itself is tiny (just JSON).

---

## Human-Readable Diffs

`giteo diff` translates raw JSON diffs into domain-specific language:

```
  Timeline: Main Edit v3
  Branch: color-grade → main

  CUTS:
  + Added clip 'B-Roll_Harbor.mov' on V2 at 00:00:10:00 (5s)
  - Removed clip 'Cutaway_003.mov' from V1
  ~ Trimmed 'Interview_A.mov' end: 00:00:30:00 → 00:00:28:12
  ~ clip 'B-Roll_Harbor.mov': Speed 100% (normal) → 50% (0.5x slow)
  ~ clip 'B-Roll_Harbor.mov': Retime method project_default → optical_flow

  COLOR:
  ~ clip 'Interview_A.mov': saturation 1.0 → 1.2
  ~ clip 'Interview_A.mov': contrast 1.0 → 1.15

  MARKERS:
  + Added marker at 00:01:05:00: "Fix audio sync here"
```

---

## Known Resolve API Limitations

Reference: https://deric.github.io/DaVinciResolve-API-Docs/

### Extended Timeline Item Properties (v20.3+)

Beyond the original Pan/Tilt/Zoom/Opacity, the API exposes additional properties via `GetProperty`/`SetProperty`:

| Property | Type | Range | Notes |
|----------|------|-------|-------|
| `RotationAngle` | float | -360.0 to 360.0 | Clip rotation |
| `AnchorPointX/Y` | float | -4x to 4x dimensions | Transform anchor |
| `Pitch` / `Yaw` | float | -1.5 to 1.5 | 3D perspective |
| `FlipX` / `FlipY` | bool | — | Horizontal/vertical flip |
| `CropLeft/Right/Top/Bottom` | float | 0 to dimension | Framing crop |
| `CropSoftness` | float | -100.0 to 100.0 | Crop edge softness |
| `CropRetain` | bool | — | Retain image position |
| `CompositeMode` | int | 0-31 | Blending mode (0=normal) |
| `DynamicZoomEase` | int | 0-3 | Zoom animation easing |
| `Distortion` | float | -1.0 to 1.0 | Lens distortion |
| `GetClipEnabled()` / `SetClipEnabled(bool)` | bool | — | Enable/disable clip (v20+) |

All of these return **static values only** — no keyframe data. They are serialized in `cuts.json` (transform block for spatial properties, top-level for composite/zoom/enabled).

### Speed/Retime — Constant Speed Only

The Resolve scripting API supports **constant speed changes** via `GetProperty`/`SetProperty`. Variable speed ramps (speed curves) are NOT accessible.

| Method | Exists? | Notes |
|--------|---------|-------|
| `GetProperty("Speed")` | **Yes** | Read speed as percentage (100.0 = normal, 200.0 = 2x, 50.0 = half) |
| `SetProperty("Speed", value)` | **Yes** | Set constant speed change |
| `GetProperty("RetimeProcess")` | **Yes** | Read retime interpolation method (0=project, 1=nearest, 2=frame_blend, 3=optical_flow) |
| `SetProperty("RetimeProcess", value)` | **Yes** | Set retime interpolation method |
| `GetProperty("MotionEstimation")` | **Yes** | Read motion estimation quality (0=project, 1..5) |
| `SetProperty("MotionEstimation", value)` | **Yes** | Set motion estimation quality |
| Speed ramp / variable speed | **NO** | No API to read or write speed curves/keyframes |
| Freeze frame | **NO** | No dedicated API; use `SetProperty("Speed", 0)` but behavior is undefined |

**Current approach:** Serialize `Speed`, `RetimeProcess`, and `MotionEstimation` per clip via `GetProperty()`. Speed data is stored in `cuts.json` (video) and `audio.json` (audio) alongside each clip item. The `speed` object is only written when the clip is retimed (speed != 100%). On restore, speed is applied via `SetProperty("Speed", value)` after clips are placed on the timeline.

**Merge behavior:** Speed changes live in `cuts.json`, so an editor changing speed on branch A while a colorist changes color on branch B will merge cleanly (different files). Post-merge validation catches mismatches between video speed and linked audio speed.

### Color — Write-Only API

The Resolve scripting API is **write-only** for color grading data. Do NOT attempt to read color values via these non-existent methods:

| Method | Exists? | Notes |
|--------|---------|-------|
| `SetCDL()` | **Yes** | Write CDL values (slope, offset, power, saturation) |
| `GetCDL()` | **NO** | Does not exist — cannot read CDL values |
| `SetLUT(nodeIndex, path)` | **Yes** | Write LUT per node |
| `GetLUT(nodeIndex)` | **NO** | Does not exist — cannot read LUT paths |
| `GetNumNodes()` | Undocumented | Works in practice but not in official API |
| `GetNodeLabel(nodeIndex)` | Undocumented | Works in practice but not in official API |
| `GetProperty("Contrast")` | Undocumented | May work for clip-level props, not per-node |
| Color wheels (Lift/Gamma/Gain) | **NO** | No read API for primary wheel values |

**Current approach:** Capture what `GetProperty()` gives us (contrast, saturation) + node structure, and export DRX stills as binary backup. The `ColorNodeGrade` model has fields for CDL/wheel values that can be populated by manual JSON editing or AI merge, even though the serializer can't read them from Resolve.

### Timeline — No Deletion API

There is **no API to delete clips from a timeline** or to delete a timeline from a project:

- `Timeline.DeleteClips()` — does NOT exist (was tried, fails silently)
- No `Project.DeleteTimeline()` method exists

**Current approach:** When restoring/switching branches, we create a fresh empty timeline via `MediaPool.CreateEmptyTimeline()`, populate it, and rename the old one with a `.giteo-old` suffix. Old timelines accumulate and must be deleted manually by the user.

### Timeline Restore — Clip Duplication Bug

**Symptom:** When switching back to main (or any branch) for the FIRST time, clips are duplicated (original clips + appended copies). Does NOT happen on subsequent switches. The duplicated clips are identical and reflect the same edits.

**Previous fix attempts that did NOT work:**

1. **Timestamp-based unique suffix for rename** — Used `f"{name}.giteo-old.{timestamp}"` instead of sequential `.giteo-old.1`, `.giteo-old.2`. Ensured rename wouldn't collide with previous `.giteo-old` timelines. **Result:** Still duplicated.

2. **Rename verification** — After `SetName()`, checked `GetName()` to verify the rename took effect. If silent failure, retried with alternative names. **Result:** Still duplicated.

3. **Safety check `_timeline_has_clips()`** — After `_create_fresh_timeline`, checked if the returned timeline actually had clips. If so, retried with a unique fallback name or bailed out. **Result:** Still duplicated.

**Root cause hypothesis:** `AppendToTimeline()` operates on whatever Resolve internally considers the "current" timeline, NOT on the timeline object passed to our code. `SetCurrentTimeline()` is asynchronous — it doesn't take effect immediately (same pattern as `SetCurrentTimecode()` which needs retries + sleep in serializer.py). On the FIRST switch, the old timeline is still "current" internally when `AppendToTimeline` runs, so clips go onto the old (already populated) timeline. On subsequent switches, the previous `SetCurrentTimeline` has long since taken effect.

4. **Temp-name-first + wait/verify (v3)** — Created new timeline with unique temp name before touching old timeline. Added `_wait_for_current_timeline()` with sleep + retry loop to confirm `SetCurrentTimeline` took effect before `AppendToTimeline`. BUT: renames still happened inside `_create_fresh_timeline` before `AppendToTimeline` ran. **Result:** Still duplicated — calling `SetName()` on the old timeline after confirming the switch caused Resolve to re-focus on the old timeline.

**Root cause (confirmed):** `SetName()` on the old timeline causes Resolve to internally re-focus on it. Even though `SetCurrentTimeline(new)` was confirmed, the subsequent `old_timeline.SetName(...)` call (which happened inside `_create_fresh_timeline` before returning) switched Resolve's internal "current" back to the old timeline. `AppendToTimeline` then targeted the old (non-empty) timeline → duplication.

**Current approach (v4):** Three-phase flow in `deserialize_timeline`:
1. **Create** — `_create_fresh_timeline` creates new timeline with temp name, sets it current, waits for confirmation. Does NOT rename anything.
2. **Populate** — `AppendToTimeline` runs while no `SetName` calls can interfere with the current timeline.
3. **Rename** — Only AFTER all clips are populated, rename old timeline to `.giteo-old` and new timeline to the original name.

---

## Engineering Guidelines

- **Act as a founding engineer** building an MVP under extreme time pressure
- **Prefer simple over clever** — `subprocess.run(["git", ...])` over GitPython; `json.dumps` over protobuf
- **No premature abstractions** — if there's only one serializer working, don't build an adapter framework
- **Test the critical path** — serializer roundtrip and git merge behavior matter most
- **JSON formatting matters** — always use `indent=2, sort_keys=True` for clean git diffs
- **Fail loudly** — print clear error messages, don't silently swallow failures
- **Keep files focused** — each module does one thing. `core.py` = git wrapper. `serializer.py` = timeline → JSON.
- **Don't over-engineer for future NLEs** — get Resolve working first, then generalize only if needed

---

## Testing Strategy

1. **Serializer tests** — mock Resolve API, verify JSON output matches expected structure
2. **Git wrapper tests** — init repo, commit, branch, merge in a temp directory
3. **Merge tests** — two branches editing different domain files merge cleanly; same file produces a conflict
4. **Validation tests** — orphaned clip refs, audio/video sync mismatches, overlapping clips are detected
5. **AI merge tests** — given a known cross-domain conflict, AI produces valid resolved JSON
6. **Diff formatter tests** — verify human-readable output from known JSON diffs
7. **Roundtrip tests** — serialize → commit → modify → deserialize → verify structure preserved

Run tests with: `python -m pytest tests/`

---

## Scope Boundaries

### In Scope (36-hour MVP)
- DaVinci Resolve serializer/deserializer (free version, via Scripts menu)
- Full `giteo` CLI: init, add, commit, branch, checkout, merge, diff, log, revert, push, pull, status
- Domain-split JSON (cuts, color, audio, effects, markers, metadata)
- AI-powered semantic merge resolution (Gemini API)
- Post-merge validation (orphaned refs, sync issues, overlapping clips)
- Human-readable diff output
- Asset manifest (file paths + checksums, no binary versioning)
- Resolve plugin scripts (5 menu items)

### Out of Scope
- Web UI / review interface
- Hosted platform (just use GitHub as remote)
- Database of any kind (git is the persistence layer)
- Media file storage, sync, or versioning (just track paths in manifest)
- Conflict resolution GUI (terminal + AI is sufficient)
- Locking / concurrent edit prevention
- Real-time collaboration
- Premiere Pro / Final Cut Pro / Avid support (fallback only if Resolve fails)
- LUT or effects binary versioning
- User authentication
