# Giteo — Testing Guide

Step-by-step walkthrough to test giteo end-to-end with DaVinci Resolve Free.

---

## How It Works

Everything happens from **inside DaVinci Resolve**. After a one-time terminal setup, collaborators never need to touch the command line. The full workflow lives in Resolve's **Workspace > Scripts** menu:

| Resolve Menu Item | What It Does |
|---|---|
| **Giteo - Save Version** | Snapshot the timeline and commit |
| **Giteo - New Branch** | Create a branch (e.g. "color-grade") |
| **Giteo - Switch Branch** | Checkout a branch and restore the timeline |
| **Giteo - Merge Branch** | Merge another branch into yours |
| **Giteo - Push** | Push your branch to GitHub for collaborators |
| **Giteo - Pull & Restore** | Pull collaborator's changes and restore timeline |
| **Giteo - Status** | See current branch, changes, and recent history |

The only things that require terminal are **one-time setup** (install, init, add GitHub remote).

---

## Prerequisites

- **DaVinci Resolve Free** (18.x or newer) installed
- **Python 3.8+** with a virtual environment
- **git** installed (system binary)
- At least **2 short video clips** on disk (any format Resolve can import — `.mov`, `.mp4`, etc.)
- A **GitHub repo** (if testing collaboration between two people)

---

## Part 1: One-Time Setup (Terminal)

These steps are done once per machine. After this, everything is in Resolve.

### 1a. Install giteo

```bash
cd /Users/lucasjin/Documents/Hackathons/giteo
source .venv/bin/activate
pip install -e .
```

Verify:

```bash
giteo --version
# → giteo 0.1.0
```

### 1b. Install Resolve plugin scripts

```bash
giteo install-resolve
```

Expected output:

```
  Linked: Giteo - Save Version.py → .../resolve_plugin/giteo_commit.py
  Linked: Giteo - New Branch.py → .../resolve_plugin/giteo_branch.py
  Linked: Giteo - Merge Branch.py → .../resolve_plugin/giteo_merge.py
  Linked: Giteo - Switch Branch.py → .../resolve_plugin/giteo_restore.py
  Linked: Giteo - Status.py → .../resolve_plugin/giteo_status.py
  Linked: Giteo - Push.py → .../resolve_plugin/giteo_push.py
  Linked: Giteo - Pull & Restore.py → .../resolve_plugin/giteo_pull.py

  Installed 7 scripts to Resolve.
  Restart Resolve, then find them under Workspace > Scripts.
```

### 1c. Initialize a giteo project

```bash
mkdir ~/Desktop/giteo-test-project
giteo init ~/Desktop/giteo-test-project
```

Expected:

```
  Initialized giteo project in /Users/.../giteo-test-project
  Created: .giteo/, timeline/, assets/
  Initial snapshot committed.
```

### 1d. (For collaboration) Add a GitHub remote

```bash
cd ~/Desktop/giteo-test-project
git remote add origin git@github.com:yourteam/giteo-test-project.git
git push -u origin main
```

Now share that repo URL with your collaborators. They clone it:

```bash
git clone git@github.com:yourteam/giteo-test-project.git ~/Desktop/giteo-test-project
```

### 1e. (Optional) Set project dir to skip the folder picker

```bash
export GITEO_PROJECT_DIR=~/Desktop/giteo-test-project
```

Or just let the first Resolve script prompt you — it remembers the path for next time.

---

## Part 2: Solo Workflow (All in Resolve)

This tests the basic save/branch/switch loop with one person.

### Step 1 — Set up the timeline

1. Open **DaVinci Resolve Free**
2. Create a new project (e.g. "Giteo Test Project")
3. Go to the **Edit** page
4. Import 2 clips into the Media Pool (File > Import > Media)
5. Create a timeline ("Main Edit") and drag both clips onto V1


Your timeline:

```
V1: [ Clip_A.mov ][ Clip_B.mov ]
A1: [ Clip_A audio ][ Clip_B audio ]
```

### Step 2 — Verify scripts are visible

Go to **Workspace > Scripts**. You should see all 7 Giteo items. If not, restart Resolve.

### Step 3 — Save the initial version

1. **Workspace > Scripts > Giteo - Save Version**
2. First time: a folder picker dialog appears — select `~/Desktop/giteo-test-project`
3. Enter commit message: `initial rough cut with 2 clips`
4. Click OK

**What happened:** The serializer extracted your entire timeline state into JSON files (`cuts.json`, `color.json`, `audio.json`, etc.) and committed them with git.

**Verify (optional, from terminal):**

```bash
cd ~/Desktop/giteo-test-project
giteo log
# → abc1234 (HEAD -> main) giteo: initial rough cut with 2 clips
# → def5678 giteo: initial snapshot

cat timeline/cuts.json | python3 -m json.tool | head -20
# Shows your 2 clips with frame ranges, track indices, etc.
```

### Step 4 — Create a branch

1. **Workspace > Scripts > Giteo - New Branch**
2. Enter: `color-grade`
3. Click OK

You're now on the `color-grade` branch. Any changes you save go here, not `main`.

### Step 5 — Make changes and save

1. Select Clip_A, go to the **Color** page, make any visible adjustment (e.g. push the Lift/Gamma/Gain wheels, add a node, apply a LUT)
2. Back on the **Edit** page, add a marker (press `M`), name it "Fix color here"
3. **Workspace > Scripts > Giteo - Save Version**
4. Message: `color grading + marker on clip A`

**How color grades are captured:** The Resolve API doesn't expose a "read CDL values" method, so giteo exports each clip's grade as a DRX (DaVinci Resolve eXchange) still — a small binary file containing the full grade (all nodes, CDL, curves, etc.). These live in `timeline/grades/` and are tracked by git. Any color change produces a different DRX file, which git detects.

### Step 6 — Switch back to main

1. **Workspace > Scripts > Giteo - Switch Branch**
2. Select `main` from the list
3. Click OK

The timeline restores to the original state — no color changes, no marker.

### Step 7 — Make different changes on main

1. Trim Clip_B shorter (drag the end)
2. **Workspace > Scripts > Giteo - Save Version**
3. Message: `trimmed clip B`

### Step 8 — Merge the branches

1. **Workspace > Scripts > Giteo - Merge Branch**
2. Select `color-grade`
3. Click OK

**Result:** Editor trimmed `cuts.json` on main, colorist changed `color.json` + `markers.json` on the branch. Git merges them with zero conflicts because they touched different files.

Dialog shows: "Merged 'color-grade' into 'main' cleanly."

The timeline now has both the trimmed Clip_B **and** the color grade + marker.

### Step 9 — Check status

1. **Workspace > Scripts > Giteo - Status**
2. Shows current branch, working tree state, and last 5 commits

---

## Part 3: Collaboration Workflow (Two People, All in Resolve)

This is the real test — two people editing the same project in parallel.

### Setup

- **Person A (Editor):** Has the project initialized with a GitHub remote (see Part 1)
- **Person B (Colorist):** Cloned the same repo to their machine

Both machines need:
- giteo installed in `.venv`
- `giteo install-resolve` run once
- Resolve restarted after install
- The same media files accessible at the same paths (shared drive / Dropbox / manual copy)

### The Workflow

**Person A (Editor) — rough cut:**

1. Open Resolve, import clips, build a rough cut on the timeline
2. **Giteo - Save Version** → message: `rough cut v1`
3. **Giteo - Push** → pushes `main` to GitHub

**Person B (Colorist) — gets the rough cut:**

4. **Giteo - Pull & Restore** → pulls `main` from GitHub, timeline loads with the rough cut
5. **Giteo - New Branch** → creates `color-grade`
6. Go to the Color page, grade the clips
7. **Giteo - Save Version** → message: `initial color pass`
8. **Giteo - Push** → pushes `color-grade` to GitHub

**Person A (Editor) — continues editing while B was grading:**

9. **Giteo - New Branch** → creates `fine-cut`
10. Trim clips, rearrange, add b-roll
11. **Giteo - Save Version** → message: `fine cut with b-roll`
12. **Giteo - Switch Branch** → back to `main`
13. **Giteo - Pull & Restore** → gets Person B's `color-grade` branch
14. **Giteo - Merge Branch** → merges `color-grade` into `main`
15. **Giteo - Merge Branch** → merges `fine-cut` into `main`

**Result:** The timeline on `main` now has:
- Person A's fine cut (clip arrangement, trimming) from `cuts.json`
- Person B's color grading from `color.json`
- All merged cleanly because different people edited different domain files

16. **Giteo - Push** → pushes the merged `main` to GitHub

**Person B (Colorist) — gets the merged result:**

17. **Giteo - Switch Branch** → back to `main`
18. **Giteo - Pull & Restore** → gets the merged timeline with both their grading and A's fine cut

---

## Part 4: Conflict Scenario (AI-Assisted Merge)

This tests what happens when two people edit the **same domain**.

### Setup

Both people start from the same `main` commit.

**Person A:**
1. Creates branch `edit-v2`
2. Deletes Clip_B from the timeline
3. Saves and pushes

**Person B:**
4. Creates branch `color-v2`
5. Color grades Clip_B (which A just deleted)
6. Saves and pushes

**Person A merges:**
7. Switches to `main`
8. Merges `edit-v2` (succeeds — Clip_B removed from `cuts.json`)
9. Merges `color-v2`

**What happens:** Git merges cleanly (different files), but **post-merge validation** catches that `color.json` references `item_001_001` (Clip_B) which no longer exists in `cuts.json`. This is an orphaned reference.

If `GEMINI_API_KEY` is set, giteo offers AI-assisted resolution: the LLM reads both versions, sees the orphan, and removes the stale color grade. The user confirms before it's applied.

**To test AI merge from terminal:**

```bash
cd ~/Desktop/giteo-test-project
export GEMINI_API_KEY=your-key-here
giteo merge color-v2
# → Post-merge validation found issues:
#   1 error(s):
#     [ERROR] orphaned_ref: Color grade references deleted clip 'item_001_001'
#
#   Attempting AI-assisted resolution...
#   AI proposed the following changes:
#   ...
#   Accept AI merge? [y/N]
```

---

## Part 5: CLI-Only Quick Test (No Resolve)

Tests git ops and validation without needing Resolve open.

```bash
source .venv/bin/activate

# Create test project
mkdir /tmp/giteo-cli-test
giteo init /tmp/giteo-cli-test
cd /tmp/giteo-cli-test

# Simulate adding a clip (normally the serializer does this)
python3 -c "
import json
cuts = json.load(open('timeline/cuts.json'))
cuts['video_tracks'] = [{'index': 1, 'items': [{
    'id': 'item_001_000', 'name': 'TestClip.mov',
    'media_ref': 'sha256:abc123',
    'record_start_frame': 0, 'record_end_frame': 720,
    'source_start_frame': 0, 'source_end_frame': 720,
    'track_index': 1,
    'transform': {'Pan': 0, 'Tilt': 0, 'ZoomX': 1, 'ZoomY': 1, 'Opacity': 100}
}]}]
json.dump(cuts, open('timeline/cuts.json', 'w'), indent=2, sort_keys=True)
"
giteo commit -m "added test clip"

# Branch off for color work
giteo branch color-work

python3 -c "
import json
color = {'grades': {'item_001_000': {'num_nodes': 2, 'nodes': [{'index': 1, 'label': 'Corrector 1', 'lut': ''}, {'index': 2, 'label': 'Warm LUT', 'lut': 'Rec709_Warm.cube'}], 'version_name': 'Version 1', 'drx_file': None}}}
json.dump(color, open('timeline/color.json', 'w'), indent=2, sort_keys=True)
"
giteo commit -m "color grade on branch"

# Back to main — color.json should be empty
giteo checkout main
cat timeline/color.json
# → {"grades": {}}

# Merge — color grade comes in
giteo merge color-work
cat timeline/color.json
# → {"grades": {"item_001_000": {"num_nodes": 2, ...}}}

# Validate
giteo validate
# → Validation passed — no issues found.

# View diff
giteo diff HEAD~1

# View history
giteo log

# Cleanup
cd ~
rm -rf /tmp/giteo-cli-test
```

### Run Unit Tests

```bash
cd /Users/lucasjin/Documents/Hackathons/giteo
source .venv/bin/activate
python -m pytest tests/ -v
# → 34 passed
```

---

## Troubleshooting

### Scripts don't appear in Resolve's menu

- Run `giteo install-resolve` from terminal
- **Restart Resolve** (scripts are loaded at launch)
- Verify: `ls ~/Library/Application\ Support/Blackmagic\ Design/DaVinci\ Resolve/Fusion/Scripts/Edit/`

### "Not a giteo project" or wrong project opens

- Delete `~/.giteo/last_project` to reset the saved project path
- Set `GITEO_PROJECT_DIR` env var before launching Resolve
- Or just select the correct folder when the picker appears

### Push/Pull says "No remote configured"

You need to add a GitHub remote once from terminal:

```bash
cd ~/Desktop/giteo-test-project
git remote add origin git@github.com:yourteam/giteo-test-project.git
git push -u origin main
```

After that, Push and Pull work from Resolve.

### Media files missing after collaborator pulls

Giteo only versions **timeline metadata** (JSON), not media files. All collaborators need the same media files at the same paths on their machines. Use a shared drive, Dropbox, or manually copy the files. The `assets/manifest.json` lists all referenced media paths.

### Serializer produces empty tracks

- Make sure there's an active timeline in Resolve (Edit page, timeline selected)
- Clips must be on tracks, not just in the Media Pool

### Merge conflicts in the same domain file

If two people edit the same domain (e.g., both change `cuts.json`), git may produce a conflict. Use `giteo merge <branch>` from terminal for AI-assisted resolution:

```bash
export GEMINI_API_KEY=your-key-here
giteo merge problematic-branch
```

### Color changes show "Nothing to commit"

Giteo captures color grades by exporting DRX stills from Resolve's Gallery. If grade export fails:
- The script switches to the Color page briefly to grab stills — make sure you're not in a modal dialog
- Check the Resolve console (Workspace > Console) for warnings like "GrabStill returned None"
- If Gallery access fails, only node structure (count, labels, LUTs) is tracked in `color.json`
- DRX export requires the Color page; the script auto-switches and switches back

### Deserialization doesn't fully restore the timeline

Timeline clearing depends on Resolve's API version. If clips aren't removed before restore:
1. Manually clear the timeline in Resolve (Select All > Delete)
2. Then run **Giteo - Switch Branch** again

### Deserialization doesn't restore color grades

Color grades are restored from DRX stills using `ApplyGradeFromDRX()`. If grades don't restore:
- Verify `timeline/grades/` contains `.drx` files
- The restore uses "No keyframes" mode (gradeMode=0) — the full grade applies to the clip
