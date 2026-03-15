# DRX Export & Color API Debugging Log

## Root Cause
**Color grade serialization on DaVinci Resolve Free is fundamentally limited.**

The Resolve scripting API is **write-only for color** on the Free edition:
- `ExportStills()` always returns False (Studio-only)
- `GetProperty("Contrast")` etc. return None (Studio-only readback)
- `GetCDL()` does not exist
- No way to read CDL, color wheel, curve, qualifier, or power window values

## What IS Readable on Free
| API | Source | Returns |
|-----|--------|---------|
| `GetNumNodes()` | clip or graph | Node count (int) |
| `graph.GetNodeLabel(idx)` | NodeGraph | Label string |
| `graph.GetLUT(idx)` | NodeGraph | LUT path string |
| `graph.GetToolsInNode(idx)` | NodeGraph | Tool names as strings (e.g., `["Primary Offset"]`) |
| `clip.GetCurrentVersion()` | clip | `{"versionName": "...", "versionType": 0}` |
| `clip.GetNodeGraph()` | clip | Graph object (useful for reading + applying grades) |

## What IS Writable on Free
| API | Purpose |
|-----|---------|
| `SetCDL()` | Apply CDL values |
| `SetProperty("Contrast", val)` | Set clip adjustments |
| `SetLUT(idx, path)` | Apply LUT per node |
| `graph.ApplyGradeFromDRX(path, idx)` | Apply existing DRX file |

## Resolution
1. `_export_grade_stills` detects first ExportStills failure and stops (no per-clip warnings)
2. `_read_clip_grade_info` uses NodeGraph API (GetNodeLabel, GetLUT, GetToolsInNode) for better data
3. `ColorNodeGrade.tools` field added — stores tool names per node for change detection
4. `restore_timeline_overlays` fixed to pass `video_tracks` for correct item ID matching

## Practical Impact
On Free, giteo can:
- **Detect** color changes (node count, tool names, LUT changes)
- **Restore** grades from existing DRX files (from git history or Studio exports)
- **Apply** CDL, clip adjustments, and LUTs that were captured on Studio

On Free, giteo cannot:
- **Capture** the actual color correction values (CDL, wheels, curves)
- **Export** new DRX grade files

Full-fidelity color round-tripping requires DaVinci Resolve Studio.

## ExportStills Attempts (DO NOT RETRY)
All of the following were tested and failed on Free 20.3.2.9:
1. 6 arg signature variations (trailing slash, uppercase, dot prefix, empty, full path)
2. Export to /tmp/ (not a filesystem permissions issue)
3. 4 image formats: dpx, jpg, png, tif (not format-specific)
4. album.GetStills()[-1] instead of GrabStill() return (not stale reference)
5. 2-second delay before export (not render timing)
6. Fresh gallery + album objects re-fetched before export
7. SetCurrentStillAlbum to re-assert album selection
8. All combinations of the above
