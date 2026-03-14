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
- **Use git, don't reimplement it** — git handles commits, branches, merges, diffs. We handle serialization.
- **Domain-split JSON** — separate files for cuts, color, audio, effects, markers. Different roles = different files = clean merges.
- **Snapshot-based** — each commit captures full timeline state. Simpler than event sourcing, works naturally with git.
- **CLI-first** — no GUI overhead. Resolve plugin scripts serve as in-NLE UI.
- **Additive integration** — work with existing NLEs (DaVinci Resolve, Final Cut Pro), don't replace them
- **Every phase is demo-able** — the system is useful at every stage of completion

---

## System Architecture

```
Path A: DaVinci Resolve (primary)              Path B: Final Cut Pro X (via FCPXML)
┌────────────────────────────┐                  ┌────────────────────────┐
│  DaVinci Resolve (Free)    │                  │  Final Cut Pro X       │
│  Workspace > Scripts menu  │                  │  File > Export XML     │
│  ┌──────────────────────┐  │                  │  → myproject.fcpxml    │
│  │ Giteo: Save Version  │  │                  └──────────┬─────────────┘
│  │ Giteo: New Branch    │  │                             │
│  │ Giteo: Switch Branch │  │                             ▼
│  │ Giteo: Merge         │  │                  ┌────────────────────────┐
│  └──────────┬───────────┘  │                  │ giteo import foo.fcpxml│
└─────────────┼──────────────┘                  │ (OpenTimelineIO reads) │
              │ Resolve API                     └──────────┬─────────────┘
              ▼                                            ▼
┌─────────────────────────────────────────────────────────────┐
│  giteo-core (Python)                                        │
│                                                             │
│  Serializers:    resolve.py  |  fcpxml.py  → json_writer.py │
│  Deserializers:  resolve.py  |  fcpxml.py                   │
│  Git wrapper:    core.py (subprocess → system git)          │
│  Diff formatter: differ.py (human-readable timeline diffs)  │
│  CLI:            cli.py (argparse)                          │
└──────────────────────┬──────────────────────────────────────┘
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

### Final Cut Pro X — Integration Details

FCP exports structured FCPXML via File > Export XML. Python parses this with OpenTimelineIO. Re-import merged results via File > Import > XML.

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.x | Resolve API is Python; OTIO is Python |
| Version control | System `git` binary | Battle-tested; don't reimplement |
| Git interaction | `subprocess` | No extra dependencies |
| Data format | JSON (`indent=2, sort_keys=True`) | Human-readable, git-diffable |
| FCPXML parsing | `opentimelineio` | Handles FCPXML and other NLE formats |
| Terminal output | `rich` | Pretty diffs and logs |
| NLE integration | Resolve Workspace Scripts + FCPXML import/export | Works with free Resolve + FCP X |

---

## Repository Structure

```
giteo/
├── giteo/                          # Python package
│   ├── __init__.py
│   ├── cli.py                      # CLI entry point
│   ├── core.py                     # Git wrapper (subprocess)
│   ├── models.py                   # Dataclasses for timeline entities
│   ├── serializers/
│   │   ├── __init__.py
│   │   ├── resolve.py              # Resolve API → domain-split JSON
│   │   ├── fcpxml.py               # FCPXML (via OTIO) → domain-split JSON
│   │   └── json_writer.py          # Shared domain-split JSON writer
│   ├── deserializers/
│   │   ├── __init__.py
│   │   ├── resolve.py              # Domain-split JSON → Resolve timeline
│   │   └── fcpxml.py               # Domain-split JSON → FCPXML
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
│   ├── cuts.json                   # Clip placements, in/out points, tracks
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
| `cuts.json` | Clip placements, in/out points, track assignments, transforms | Editor |
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
            "Opacity": 100.0
          }
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

## Git Operations Mapping

| User action | Giteo command | Under the hood |
|-------------|---------------|----------------|
| Save a version | `giteo commit -m "rough cut done"` | Serialize timeline → JSON, `git add`, `git commit` |
| Try different approach | `giteo branch experiment` | `git checkout -b experiment` |
| Switch versions | `giteo checkout main` | `git checkout main`, deserialize JSON → NLE timeline |
| Combine work | `giteo merge color-grade` | `git merge color-grade` |
| See what changed | `giteo diff` | `git diff` formatted as human-readable timeline changes |
| View history | `giteo log` | `git log` with giteo formatting |
| Undo last version | `giteo revert` | `git revert HEAD` |
| Start tracking | `giteo init` | Create `.giteo/`, `git init`, initial snapshot |
| Import from FCP | `giteo import project.fcpxml` | Parse FCPXML → domain-split JSON → commit |
| Export to FCP | `giteo export --format fcpxml` | JSON → FCPXML for FCP import |

---

## Resolve Plugin Scripts

Each script in `resolve_plugin/` is a standalone Python file that runs from Resolve's Workspace > Scripts menu. Pattern:

```python
# The resolve variable is injected by DaVinci Resolve when running from Scripts menu
import sys
import os

# Add giteo package to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from giteo.serializers.resolve import serialize_timeline
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

## Human-Readable Diffs

`giteo diff` translates raw JSON diffs into domain-specific language:

```
  Timeline: Main Edit v3
  Branch: color-grade → main

  CUTS:
  + Added clip 'B-Roll_Harbor.mov' on V2 at 00:00:10:00 (5s)
  - Removed clip 'Cutaway_003.mov' from V1
  ~ Trimmed 'Interview_A.mov' end: 00:00:30:00 → 00:00:28:12

  COLOR:
  ~ clip 'Interview_A.mov': saturation 1.0 → 1.2
  ~ clip 'Interview_A.mov': contrast 1.0 → 1.15

  MARKERS:
  + Added marker at 00:01:05:00: "Fix audio sync here"
```

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
4. **Diff formatter tests** — verify human-readable output from known JSON diffs
5. **Roundtrip tests** — serialize → commit → modify → deserialize → verify structure preserved
6. **FCPXML tests** — parse sample FCPXML, verify domain-split JSON, write back, compare

Run tests with: `python -m pytest tests/`

---

## Scope Boundaries

### In Scope (36-hour MVP)
- DaVinci Resolve serializer/deserializer (free version, via Scripts menu)
- FCPXML import/export for Final Cut Pro X (via OpenTimelineIO)
- Git operations: init, commit, branch, checkout, merge, diff, log, revert
- Domain-split JSON (cuts, color, audio, effects, markers, metadata)
- Human-readable diff output
- Asset manifest (file paths + checksums, no binary versioning)
- CLI interface
- Resolve plugin scripts (5 menu items)

### Out of Scope
- Web UI / review interface
- Remote server / hosted platform (just use GitHub)
- Proxy generation / media file sync
- Custom merge engine (git's text merge is sufficient)
- Conflict resolution GUI
- Locking / concurrent edit prevention
- Real-time collaboration
- Premiere Pro / Avid support
- LUT or effects binary versioning
- User authentication
