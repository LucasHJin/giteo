# Vit — Git for Video Editing

[![Vit Demo](https://img.youtube.com/vi/phS28hhJSP8/maxresdefault.jpg)](https://www.youtube.com/watch?v=phS28hhJSP8)

Vit brings git-style version control to video editing. Instead of versioning raw media files, Vit tracks **timeline metadata** — clip placements, color grades, audio levels, effects, and markers — as lightweight JSON, using Git as the backend.

Collaborators (editors, colorists, sound designers) work in parallel on branches and merge changes cleanly, just like developers with code.

## How It Works

Vit serializes your DaVinci Resolve timeline into **domain-split JSON files**:

| File | Contents | Typical Owner |
|------|----------|---------------|
| `cuts.json` | Clip placements, in/out points, transforms | Editor |
| `color.json` | Color grading per clip | Colorist |
| `audio.json` | Levels, panning | Sound Designer |
| `effects.json` | Effects, transitions | Editor / VFX |
| `markers.json` | Markers, notes | Anyone |
| `metadata.json` | Frame rate, resolution, track counts | Rarely changed |

Different roles edit different files, so Git merges them without conflicts. When cross-domain issues arise (e.g., a deleted clip still referenced in `color.json`), an AI-powered semantic merge resolves them.

## Installation

**Requirements:** Python 3.8+, Git, DaVinci Resolve (optional, for Resolve integration)

### One-Line Install (macOS/Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/LucasHJin/vit/main/install.sh | bash
```

### Manual Install

```bash
git clone https://github.com/LucasHJin/vit.git
cd vit
pip install .
vit install-resolve   # symlink plugin scripts into DaVinci Resolve
```

For the optional Qt-based GUI panel inside Resolve:

```bash
pip install ".[qt]"
```

## Usage Guide (GUI — Primary Workflow)

The main way to use Vit is through the **panel inside DaVinci Resolve** (`Workspace → Scripts → Vit Panel`). You only need the terminal for the one-time project setup.

### What you need before starting

- **A shared GitHub repo** (or any Git remote) — this is how collaborators share timeline changes. Create an empty repo on GitHub first (no README, no license).
- **Your footage shared separately** — Vit tracks edit decisions, not raw video files. Share footage the way you already do (shared drive, Dropbox, server). Collaborators relink in Resolve if paths differ.
- **An initialized vit project** — run `vit init` once in Terminal to create the `.vit/` config and initial timeline snapshot. This produces the JSON metadata files (`cuts.json`, `color.json`, etc.) that Vit versions from that point on.

> See [`docs/COLLABORATION.md`](docs/COLLABORATION.md) for the full step-by-step collaboration setup, including how to invite teammates and handle relinking footage.

---

### Person who starts the project (once, in Terminal)

```bash
# 1. Create and enter the project folder
vit init my-project
cd my-project

# 2. Connect to your shared GitHub repo
vit collab setup   # paste your empty repo URL when prompted
```

Open DaVinci Resolve, load your project and timeline, then open the Vit Panel (`Workspace → Scripts → Vit Panel`) and **Save Version** to create the first snapshot. Vit serializes the timeline to JSON and commits it. Send the `vit clone …` URL that Terminal prints to your collaborators.

---

### Collaborators joining (once, in Terminal)

```bash
# Clone the project
vit clone https://github.com/yourname/your-repo.git
cd your-repo

# Pull the latest timeline state
vit checkout main
```

Open Resolve, run **Vit Panel → Switch Branch**, choose your footage folder, and relink any offline clips. Then create your own branch:

```bash
vit branch your-name
```

From here on, everything happens in the panel.

---

### Daily workflow (entirely in the Resolve panel)

1. **Pull** — fetch the latest changes from the team
2. **Switch Branch** — restore the timeline to your branch
3. Edit in Resolve as usual
4. **Save Version** — serialize your timeline changes and commit
5. **Push** — share your work

---

### Merging work (lead / editor)

In the panel:

1. Pull to get everyone's latest commits
2. Switch to `main` (or whichever branch you merge into)
3. **Merge** → select the branch to bring in
4. Review the diff summary the panel shows; the panel uses AI to recommend a strategy when a key is set, or falls back to change-count heuristics without one
5. Push the merged result
6. Tell teammates to Pull and Switch Branch to see the merged timeline

For complex cross-domain conflicts (e.g., a clip deleted on one branch but color-graded on another), use `vit merge <branch>` in Terminal — it runs the full AI-assisted resolution flow.

---

## Quick Start (CLI)

The CLI mirrors everything the panel does, useful for scripting or when outside Resolve:

```bash
vit init                        # initialize project (required once)
vit commit -m "rough cut done"  # save a version
vit branch color-grade          # create a branch
vit checkout color-grade        # switch to it
vit commit -m "first color pass"
vit checkout main
vit merge color-grade           # merge back
vit diff                        # see what changed
vit log                         # version history
```

## Commands

| Command | Description |
|---------|-------------|
| `vit init` | Initialize a new vit project |
| `vit add` | Serialize timeline and stage changes |
| `vit commit -m "msg"` | Stage + commit |
| `vit branch <name>` | Create a new branch |
| `vit checkout <name>` | Switch branches (restores timeline in Resolve) |
| `vit merge <branch>` | Merge a branch (with AI conflict resolution) |
| `vit diff` | Human-readable timeline diff |
| `vit log` | Formatted version history |
| `vit revert` | Undo the last commit |
| `vit push` / `vit pull` | Sync with a remote |
| `vit status` | Show project status |

## Project Structure

```
vit/                      # Core library
  cli.py                  # CLI entry point
  core.py                 # Git operations wrapper
  serializer.py           # Resolve timeline -> JSON
  deserializer.py         # JSON -> Resolve timeline
  ai_merge.py             # AI-powered conflict resolution (Gemini)
  differ.py               # Human-readable diff formatting
  validator.py            # Post-merge validation
  models.py               # Data models
  json_writer.py          # Domain-split JSON I/O

resolve_plugin/           # DaVinci Resolve integration (primary UI)
  vit_panel_launcher.py   # Panel backend: all git + serialize/deserialize logic
  vit_panel_tkinter.py    # Tkinter panel UI (default)
  vit_panel_qt.py         # Qt panel UI (optional, pip install ".[qt]")
  vit_commit.py           # Script menu: commit
  vit_branch.py           # Script menu: branch
  vit_merge.py            # Script menu: merge
  vit_status.py           # Script menu: status
  vit_restore.py          # Script menu: restore timeline

tests/                    # Test suite
docs/                     # Reference docs
  COLLABORATION.md        # Step-by-step multi-user setup
  JSON_SCHEMAS.md         # Full schema for all domain JSON files
  RESOLVE_API_LIMITATIONS.md  # Known Resolve API constraints
  AI_MERGE_DETAILS.md     # AI merge architecture and prompts
```

## AI Features

Vit uses the **Gemini API** (`gemini-2.5-flash`) to assist with video editing workflows that go beyond what plain Git can handle. Key uses:

- **Semantic merge resolution** — When a merge creates cross-domain conflicts (e.g., one branch deletes a clip while another color-grades it), the AI analyzes BASE/OURS/THEIRS states across all domain files and produces structured per-domain decisions with confidence levels
- **Interactive conflict clarification** — For ambiguous merges (low-confidence decisions), the AI presents options to the user, then resolves the final JSON based on their choices
- **Post-merge validation** — A rule-based validator catches orphaned references, overlapping clips, audio/video sync mismatches, and speed/duration inconsistencies after every merge; these issues feed into the AI prompt for smarter resolution
- **Commit message suggestions** — `vit commit` can auto-generate a descriptive message from the timeline diff using video editing terminology (e.g., "Add B-roll on V2, trim interview end point")
- **Log summaries** — `vit log --summary` produces a natural-language overview of recent commits for the team
- **Branch comparison analysis** — The Resolve panel uses AI to compare two branches and recommend a merge strategy before you commit to it
- **Commit classification** — Commits are auto-categorized as audio, video, or color changes (with a fast heuristic fallback when AI is unavailable)

Set `GEMINI_API_KEY` in your environment or project `.env` file to enable AI features. All AI features degrade gracefully — Vit works fully without an API key, you just lose the smart merge and suggestions.

## Testing

```bash
python -m pytest tests/
```

## Contributions

We are not accepting external pull requests at this time.

Please feel free to fork the project and build on it independently!

## License

MIT
