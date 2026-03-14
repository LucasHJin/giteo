# Giteo — Git for Video Editing

## Project Purpose

Giteo brings git-style version control to video editing. Collaborators (editors, colorists, sound designers) work in parallel on branches and merge changes, like developers with code.

**Core insight:** Version control *edit decisions and timeline metadata* (as JSON), not raw video files. Use actual `git` as the backend.

**What this is NOT:** "Git for raw video files." We version control timeline decisions — clip placements, color grades, audio levels, markers — as lightweight JSON, never media binaries.

### Target Users
Video editors, colorists, sound designers, assistant editors.

### The Problem
Sequential handoffs (Editor → Colorist → Sound) are slow. No parallel work, no structured history, no merge of creative branches.

### The Solution
Each collaborator works on a branch. Giteo serializes the NLE timeline into domain-split JSON (cuts, color, audio, etc.) so different roles edit different files. Git merges them cleanly.

---

## Product Philosophy

- **Metadata, not media** — timeline decisions are the merge surface
- **Use git, don't reimplement it** — all commands go through `giteo`, never raw `git`
- **Domain-split JSON** — cuts, color, audio, effects, markers = different files = clean merges
- **AI-assisted semantic merging** — LLM resolves cross-domain conflicts (e.g., deleted clip still in color.json)
- **Snapshot-based** — each commit = full timeline state
- **No media storage, no database** — JSON in git only
- **CLI-first** — Resolve plugin scripts serve as in-NLE UI

---

## System Architecture

```
Resolve (Scripts menu) → giteo-core (Python) → Git (system binary)
```

- **giteo-core:** serializer.py, deserializer.py, json_writer.py, core.py, ai_merge.py, differ.py, cli.py
- **Resolve scripts:** `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit/`
- **Fallback:** If Resolve API too limited → FCPXML + OpenTimelineIO; giteo-core stays the same.

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.x |
| Version control | System `git` binary |
| Data format | JSON (`indent=2, sort_keys=True`) |
| AI merge | Gemini API (`google-generativeai`) |
| Terminal | `rich` |

---

## Repository Structure

```
giteo/
├── giteo/           # cli.py, core.py, models.py, serializer.py, deserializer.py,
│                   # json_writer.py, ai_merge.py, validator.py, differ.py
├── resolve_plugin/  # giteo_commit.py, giteo_branch.py, giteo_merge.py, giteo_status.py, giteo_restore.py
├── tests/
└── docs/           # Optional top-up: JSON_SCHEMAS.md, RESOLVE_API_LIMITATIONS.md, AI_MERGE_DETAILS.md
```

### Giteo-managed project (user's video repo)

```
my-video-project/
├── .git/
├── .giteo/config.json
├── timeline/       # cuts.json, color.json, audio.json, effects.json, markers.json, metadata.json
└── assets/        # manifest.json (paths, checksums)
```

---

## Domain Model

### Domain-Split JSON

| File | Tracks | Who edits |
|------|--------|-----------|
| `cuts.json` | Clip placements, in/out, transforms, speed | Editor |
| `color.json` | Color grading per clip | Colorist |
| `audio.json` | Levels, panning | Sound designer |
| `effects.json` | Effects, transitions | Editor / VFX |
| `markers.json` | Markers, notes | Anyone |
| `metadata.json` | Frame rate, resolution, track counts | Rarely |

Different roles = different files = conflict-free merges. **Full JSON schemas:** `@docs/JSON_SCHEMAS.md`

---

## Giteo Commands

| Action | Command | Under the hood |
|--------|---------|----------------|
| Start tracking | `giteo init` | `.giteo/`, `git init`, initial snapshot |
| Stage | `giteo add` | Serialize → JSON, `git add timeline/ assets/` |
| Save version | `giteo commit -m "msg"` | `giteo add` + `git commit` |
| New approach | `giteo branch experiment` | `git checkout -b` |
| Switch | `giteo checkout main` | `git checkout`, deserialize → Resolve |
| Combine | `giteo merge color-grade` | `git merge` → validate → AI if needed |
| See changes | `giteo diff` | Human-readable timeline diff |
| History | `giteo log` | Formatted `git log` |
| Undo | `giteo revert` | `git revert HEAD` |
| Share | `giteo push` / `giteo pull` | Standard git remote |
| Status | `giteo status` | Giteo-formatted status |

---

## Resolve Plugin Scripts

Standalone Python files in `resolve_plugin/`. Pattern: add giteo to path, get `resolve`/`project`/`timeline`, call `serialize_timeline` + `git_add` + `git_commit`. Symlink to Resolve's Edit scripts folder.

---

## AI-Powered Semantic Merging

Git merges work when different domains are edited. AI steps in for cross-domain issues: orphaned refs (deleted clip in color.json), audio/video sync, overlapping clips, speed mismatches. **Details:** `@docs/AI_MERGE_DETAILS.md`

Flow: Try git merge → post-merge validation (validator.py) → if issues, send to LLM (ai_merge.py) → user confirms → write resolved files.

---

## Storage Model

**No database. No media storage.** JSON in git only. Media files stay on disk; `manifest.json` records paths/checksums. Git = persistence. Share via GitHub.

---

## Human-Readable Diffs

`giteo diff` example:

```
CUTS: + Added clip 'B-Roll_Harbor.mov' on V2 at 00:00:10:00
      - Removed clip 'Cutaway_003.mov'
      ~ Trimmed 'Interview_A.mov' end: 00:00:30:00 → 00:00:28:12
COLOR: ~ clip 'Interview_A.mov': saturation 1.0 → 1.2
MARKERS: + Added marker at 00:01:05:00: "Fix audio sync here"
```

---

## Resolve API Limitations

**Reference:** `@docs/RESOLVE_API_LIMITATIONS.md`

Key points: Extended props (RotationAngle, Crop, Flip, etc.) are static only — no keyframes. Speed/retime: constant only, no ramps. Color: write-only (no GetCDL/GetLUT). No timeline/clip deletion API. Timeline restore: `SetName()` on old timeline causes clip duplication — use three-phase flow (create → populate → rename).

---

## Engineering Guidelines

- **Founding engineer mindset** — MVP under time pressure
- **Simple over clever** — subprocess for git, json.dumps
- **No premature abstractions** — one serializer first
- **JSON formatting** — `indent=2, sort_keys=True` always
- **Fail loudly** — clear errors, no silent swallows
- **Focused modules** — core.py = git, serializer.py = timeline→JSON

---

## Testing Strategy

Serializer tests (mock Resolve), git wrapper tests, merge tests, validation tests, AI merge tests, diff formatter tests, roundtrip tests. Run: `python -m pytest tests/`

---

## Scope Boundaries

**In scope:** Resolve serializer/deserializer, full giteo CLI, domain-split JSON, AI merge (Gemini), post-merge validation, human-readable diff, asset manifest, 5 Resolve plugin scripts.

**Out of scope:** Web UI, hosted platform, database, media storage/sync, conflict GUI, locking, real-time collab, other NLEs (fallback only), LUT versioning, auth.
