# Known Resolve API Limitations

Reference: https://deric.github.io/DaVinciResolve-API-Docs/

## Extended Timeline Item Properties (v20.3+)

Beyond Pan/Tilt/Zoom/Opacity, the API exposes additional properties via `GetProperty`/`SetProperty`:

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

All return **static values only** — no keyframe data. Serialized in `cuts.json` (transform block for spatial, top-level for composite/zoom/enabled).

## Speed/Retime — Constant Speed Only

| Method | Exists? | Notes |
|--------|---------|-------|
| `GetProperty("Speed")` | **Yes** | 100.0 = normal, 200.0 = 2x, 50.0 = half |
| `SetProperty("Speed", value)` | **Yes** | Set constant speed |
| `GetProperty("RetimeProcess")` | **Yes** | 0=project, 1=nearest, 2=frame_blend, 3=optical_flow |
| `SetProperty("RetimeProcess", value)` | **Yes** | Set retime interpolation |
| `GetProperty("MotionEstimation")` | **Yes** | 0=project, 1..5 |
| `SetProperty("MotionEstimation", value)` | **Yes** | Set motion estimation quality |
| Speed ramp / variable speed | **NO** | No API for speed curves/keyframes |
| Freeze frame | **NO** | Use `SetProperty("Speed", 0)` but behavior undefined |

**Current approach:** Serialize Speed, RetimeProcess, MotionEstimation per clip. Speed in `cuts.json` and `audio.json`. On restore, apply via `SetProperty("Speed", value)` after clips placed.

## Color — Write-Only API

| Method | Exists? | Notes |
|--------|---------|-------|
| `SetCDL()` | **Yes** | Write CDL values |
| `GetCDL()` | **NO** | Cannot read CDL |
| `SetLUT(nodeIndex, path)` | **Yes** | Write LUT per node |
| `GetLUT(nodeIndex)` | **NO** | Cannot read LUT paths |
| `GetNumNodes()` | Undocumented | Works in practice |
| Color wheels (Lift/Gamma/Gain) | **NO** | No read API |

**Current approach:** Capture contrast, saturation via `GetProperty()` + node structure. CDL/wheel fields in model can be populated by manual JSON or AI merge.

## Timeline — No Deletion API

- `Timeline.DeleteClips()` — does NOT exist
- No `Project.DeleteTimeline()` method

**Current approach:** On restore, create fresh timeline via `MediaPool.CreateEmptyTimeline()`, populate it, rename old to `.giteo-old`. Old timelines accumulate; user must delete manually.

## Timeline Restore — Clip Duplication Bug

**Symptom:** First switch to a branch duplicates clips. Does NOT happen on subsequent switches.

**Root cause (confirmed):** `SetName()` on the old timeline causes Resolve to re-focus on it. Even after `SetCurrentTimeline(new)` was confirmed, calling `old_timeline.SetName(...)` before `AppendToTimeline` switched Resolve's internal "current" back to the old timeline. `AppendToTimeline` then targeted the old (non-empty) timeline → duplication.

**Current approach (v4):** Three-phase flow in `deserialize_timeline`:
1. **Create** — `_create_fresh_timeline` creates new timeline with temp name, sets it current, waits for confirmation. Does NOT rename anything.
2. **Populate** — `AppendToTimeline` runs while no `SetName` calls can interfere.
3. **Rename** — Only AFTER all clips populated, rename old to `.giteo-old` and new to original name.
