# Vit — Git for Video Editing

## Project Purpose

Vit brings git-style version control to video editing. Collaborators (editors, colorists, sound designers) work in parallel on branches and merge changes, like developers with code.

**Core insight:** Version control *edit decisions and timeline metadata* (as JSON), not raw video files. Use actual `git` as the backend.

**What this is NOT:** "Git for raw video files." We version control timeline decisions — clip placements, color grades, audio levels, markers — as lightweight JSON, never media binaries.

### Target Users
Video editors, colorists, sound designers, assistant editors.

### The Problem
Sequential handoffs (Editor → Colorist → Sound) are slow. No parallel work, no structured history, no merge of creative branches.

### The Solution
Each collaborator works on a branch. Vit serializes the NLE timeline into domain-split JSON (cuts, color, audio, etc.) so different roles edit different files. Git merges them cleanly.

---

## Product Philosophy

- **Metadata, not media** — timeline decisions are the merge surface
- **Use git, don't reimplement it** — all commands go through `vit`, never raw `git`
- **Domain-split JSON** — cuts, color, audio, effects, markers = different files = clean merges
- **AI-assisted semantic merging** — LLM resolves cross-domain conflicts (e.g., deleted clip still in color.json)
- **Snapshot-based** — each commit = full timeline state
- **No media storage, no database** — JSON in git only
- **CLI-first** — Resolve plugin scripts serve as in-NLE UI

---

## System Architecture

```
Resolve Panel (primary)  → vit-core (Python) → Git (system binary)
CLI (`vit` command)      → vit-core (Python) → Git (system binary)  [power users / fallback]
```

- **Primary interface:** Resolve plugin panel (`vit_panel_launcher.py` + `vit_panel_tkinter.py`), accessed via Resolve's Scripts menu. This is what end users (editors, colorists) interact with.
- **vit-core:** serializer.py, deserializer.py, json_writer.py, core.py, ai_merge.py, differ.py, cli.py
- **Resolve scripts dir:** `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit/`
- **Fallback:** If Resolve API too limited → FCPXML + OpenTimelineIO; vit-core stays the same.

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.x |
| Version control | System `git` binary |
| Data format | JSON (`indent=2, sort_keys=True`) |
| AI merge | Gemini API (`google-generativeai`) or OpenAI-compatible API (`openai`) |
| Terminal | `rich` |

---

## Repository Structure

```
vit/
├── vit/           # cli.py, core.py, models.py, serializer.py, deserializer.py,
│                   # json_writer.py, ai_merge.py, validator.py, differ.py
├── resolve_plugin/  # vit_commit.py, vit_branch.py, vit_merge.py, vit_status.py, vit_restore.py
├── tests/
└── docs/           # Optional top-up: JSON_SCHEMAS.md, RESOLVE_API_LIMITATIONS.md, AI_MERGE_DETAILS.md
```

### Vit-managed project (user's video repo)

```
my-video-project/
├── .git/
├── .vit/config.json
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

## Vit Commands

These are CLI commands for power users and scripting. Most users access equivalent actions via the Resolve panel GUI.

| Action | Command | Under the hood |
|--------|---------|----------------|
| Start tracking | `vit init` | `.vit/`, `git init`, initial snapshot |
| Stage | `vit add` | Serialize → JSON, `git add timeline/ assets/` |
| Save version | `vit commit -m "msg"` | `vit add` + `git commit` |
| New approach | `vit branch experiment` | `git checkout -b` |
| Switch | `vit checkout main` | `git checkout`, deserialize → Resolve |
| Combine | `vit merge color-grade` | `git merge` → validate → AI if needed |
| See changes | `vit diff` | Human-readable timeline diff |
| History | `vit log` | Formatted `git log` |
| Undo | `vit revert` | `git revert HEAD` |
| Share | `vit push` / `vit pull` | Standard git remote |
| Status | `vit status` | Vit-formatted status |

---

## Resolve Plugin Scripts

**Primary user interface.** The panel (`vit_panel_launcher.py` + `vit_panel_tkinter.py`) is the main way users interact with Vit — launched from Resolve's Scripts menu. It exposes commit, branch, merge, push/pull, and status as GUI actions.

`vit_panel_launcher.py` handles all backend actions (serialize, deserialize, git ops) and serves responses to the UI layer. `vit_panel_tkinter.py` is the Tkinter-based fallback UI.

All scripts follow the pattern: add vit to path, get `resolve`/`project`/`timeline`, call into vit-core. Symlink the folder to Resolve's Edit scripts dir.

---

## AI-Powered Semantic Merging

Git merges work when different domains are edited. AI steps in for cross-domain issues: orphaned refs (deleted clip in color.json), audio/video sync, overlapping clips, speed mismatches. **Details:** `@docs/AI_MERGE_DETAILS.md`

Flow: Try git merge → post-merge validation (validator.py) → if issues, send to LLM (ai_merge.py) → user confirms → write resolved files.

**AI in the GUI is enrichment-only.** The panel never blocks on AI — `analyze_branch_comparison` and `classify_commit_type` degrade to heuristic fallbacks if `GEMINI_API_KEY` is absent. AI conflict resolution (`merge_with_ai`) only runs in the CLI (`vit merge`); use `vit merge --no-ai` to skip it entirely. The GUI works 100% without a key.

---

## Storage Model

**No database. No media storage.** JSON in git only. Media files stay on disk; `manifest.json` records paths/checksums. Git = persistence. Share via GitHub.

---

## Human-Readable Diffs

`vit diff` example:

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

- **Simple over clever** — subprocess for git, json.dumps
- **No unnecessary abstractions** — solve the current problem cleanly
- **JSON formatting** — `indent=2, sort_keys=True` always
- **Fail loudly** — clear errors, no silent swallows
- **Focused modules** — core.py = git, serializer.py = timeline→JSON

---

## Testing Strategy

Serializer tests (mock Resolve), git wrapper tests, merge tests, validation tests, AI merge tests, diff formatter tests, roundtrip tests. Run: `python -m pytest tests/`

---

## Scope Boundaries

**In scope:** Resolve serializer/deserializer, full vit CLI, domain-split JSON, AI merge (Gemini), post-merge validation, human-readable diff, asset manifest, 5 Resolve plugin scripts.

**Out of scope:** Web UI, hosted platform, database, media storage/sync, conflict GUI, locking, real-time collab, other NLEs (fallback only), LUT versioning, auth.
