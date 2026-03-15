"""Giteo: Debug V2 Placement — test importing .comp into media pool and placing on V2.

Run from Workspace > Scripts. Creates a test timeline, does NOT touch your real one.
"""
import sys
import os
import time
import traceback

try:
    _real = os.path.realpath(__file__)
except NameError:
    _real = None
if _real:
    _root = os.path.dirname(os.path.dirname(_real))
    if os.path.isdir(os.path.join(_root, "giteo")) and _root not in sys.path:
        sys.path.insert(0, _root)


def _log(msg):
    print(f"[debug-v2] {msg}")


def _dump_tracks(timeline, label):
    _log(f"--- {label} ---")
    vcount = timeline.GetTrackCount("video") or 0
    for idx in range(1, vcount + 1):
        clips = timeline.GetItemListInTrack("video", idx) or []
        _log(f"  V{idx}: {len(clips)} clip(s)")
        for i, c in enumerate(clips):
            name = c.GetName() or "?"
            start = c.GetStart()
            end = c.GetEnd()
            dur = c.GetDuration()
            try:
                ti = c.GetTrackTypeAndIndex()
                track_str = f"track={ti}"
            except Exception:
                track_str = ""
            fc = 0
            try:
                fc = c.GetFusionCompCount() or 0
            except Exception:
                pass
            _log(f"    [{i}] '{name}' start={start} end={end} dur={dur} "
                 f"{track_str} fusionComps={fc}")


def main():
    try:
        _resolve = resolve  # noqa: F821
    except NameError:
        _resolve = None
    if not _resolve:
        _log("ERROR: Not running inside DaVinci Resolve")
        return

    pm = _resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if not project:
        _log("ERROR: No project open")
        return
    media_pool = project.GetMediaPool()

    _log("=" * 60)
    _log("V2 PLACEMENT DEBUG")
    _log("=" * 60)

    test_name = f"giteo_v2_test_{int(time.time())}"
    test_tl = media_pool.CreateEmptyTimeline(test_name)
    if not test_tl:
        _log("ERROR: Could not create test timeline")
        return
    project.SetCurrentTimeline(test_tl)
    time.sleep(0.5)

    # Ensure V2 exists
    test_tl.AddTrack("video")
    _log(f"Track count: {test_tl.GetTrackCount('video')}")

    # ---- TEST A: Export a .comp file from an inserted Text+ ----
    _log("")
    _log("=== TEST A: Create Text+ and export .comp ===")
    result = test_tl.InsertFusionTitleIntoTimeline("Text+")
    if not result:
        _log("  Insert failed, cannot continue")
        return
    _log(f"  Inserted Text+ on V1")

    comp_dir = os.path.expanduser("~/Desktop/giteo_debug_comp")
    os.makedirs(comp_dir, exist_ok=True)
    comp_path = os.path.join(comp_dir, "test_text.comp")

    try:
        export_ok = result.ExportFusionComp(comp_path, 1)
        _log(f"  ExportFusionComp: {export_ok}")
        _log(f"  File exists: {os.path.exists(comp_path)}")
        if os.path.exists(comp_path):
            size = os.path.getsize(comp_path)
            _log(f"  File size: {size} bytes")
    except Exception as e:
        _log(f"  Export ERROR: {e}")
        return

    # Set some text so we can verify it survived
    try:
        comp = result.GetFusionCompByIndex(1)
        tools = comp.GetToolList(False, "TextPlus") or {}
        tool_list = list(tools.values()) if isinstance(tools, dict) else list(tools)
        if tool_list:
            tool_list[0].SetInput("StyledText", "V2_TEST_TEXT")
            _log("  Set text to 'V2_TEST_TEXT'")
            # Re-export with the new text
            result.ExportFusionComp(comp_path, 1)
            _log("  Re-exported with new text")
    except Exception as e:
        _log(f"  Set text ERROR: {e}")

    # ---- TEST B: Import .comp into media pool ----
    _log("")
    _log("=== TEST B: Import .comp into media pool ===")
    try:
        imported = media_pool.ImportMedia([comp_path])
        _log(f"  ImportMedia result: {imported}")
        _log(f"  Type: {type(imported)}")
        if imported:
            _log(f"  Length: {len(imported)}")
            for j, item in enumerate(imported):
                _log(f"  [{j}] {item}")
                _log(f"      Type: {type(item)}")
                try:
                    _log(f"      GetName: {item.GetName()}")
                except Exception:
                    pass
                try:
                    _log(f"      GetClipProperty('Type'): {item.GetClipProperty('Type')}")
                    _log(f"      GetClipProperty('Frames'): {item.GetClipProperty('Frames')}")
                except Exception as e:
                    _log(f"      GetClipProperty ERROR: {e}")
        else:
            _log("  ImportMedia returned empty/None — .comp import not supported")
    except Exception as e:
        _log(f"  ImportMedia ERROR: {e}")
        imported = None

    # ---- TEST C: AppendToTimeline on V2 with imported clip ----
    if imported:
        _log("")
        _log("=== TEST C: AppendToTimeline on V2 ===")
        pool_item = imported[0]
        try:
            appended = media_pool.AppendToTimeline([{
                "mediaPoolItem": pool_item,
                "startFrame": 0,
                "endFrame": 120,
                "trackIndex": 2,
                "recordFrame": 86400,
            }])
            _log(f"  AppendToTimeline result: {appended}")
            if appended:
                for j, a in enumerate(appended):
                    _log(f"  [{j}] {a}")
                    try:
                        ti = a.GetTrackTypeAndIndex()
                        _log(f"      Track: {ti}")
                        _log(f"      Start: {a.GetStart()}")
                        _log(f"      Name: {a.GetName()}")
                    except Exception as e:
                        _log(f"      Read ERROR: {e}")
        except Exception as e:
            _log(f"  AppendToTimeline ERROR: {e}")

        _dump_tracks(test_tl, "After AppendToTimeline on V2")

        # Check if the Fusion comp has our text
        v2_clips = test_tl.GetItemListInTrack("video", 2) or []
        if v2_clips:
            clip = v2_clips[-1]
            _log("")
            _log("=== TEST D: Check text on V2 clip ===")
            try:
                fc = clip.GetFusionCompCount()
                _log(f"  FusionCompCount: {fc}")
                if fc and fc >= 1:
                    c = clip.GetFusionCompByIndex(1)
                    tools = c.GetToolList() or {}
                    tl = list(tools.values()) if isinstance(tools, dict) else list(tools)
                    for t in tl:
                        try:
                            attrs = t.GetAttrs() or {}
                            reg = attrs.get("TOOLS_RegID", "?")
                            st = t.GetInput("StyledText")
                            _log(f"  Tool: {reg}, StyledText: {repr(st)}")
                        except Exception:
                            pass
                else:
                    _log("  No Fusion comp — would need AddFusionComp + manual setup")
                    try:
                        new_comp = clip.AddFusionComp()
                        _log(f"  AddFusionComp result: {new_comp}")
                    except Exception as e:
                        _log(f"  AddFusionComp ERROR: {e}")
            except Exception as e:
                _log(f"  Check ERROR: {e}")

    # ---- TEST E: InsertFusionCompositionIntoTimeline (blank Fusion comp) ----
    _log("")
    _log("=== TEST E: InsertFusionCompositionIntoTimeline ===")
    try:
        fc_result = test_tl.InsertFusionCompositionIntoTimeline()
        _log(f"  Result: {fc_result}")
        if fc_result:
            try:
                ti = fc_result.GetTrackTypeAndIndex()
                _log(f"  Track: {ti}")
                _log(f"  Start: {fc_result.GetStart()}")
                _log(f"  Name: {fc_result.GetName()}")
            except Exception as e:
                _log(f"  Read ERROR: {e}")
    except Exception as e:
        _log(f"  ERROR: {e}")

    _dump_tracks(test_tl, "Final state")

    # Cleanup
    try:
        import shutil
        shutil.rmtree(comp_dir, ignore_errors=True)
    except Exception:
        pass

    _log("")
    _log("=" * 60)
    _log(f"Done. Delete '{test_name}' manually from Resolve.")
    _log("Copy this output and share for debugging.")
    _log("=" * 60)


try:
    main()
except Exception:
    print(f"[debug-v2] SCRIPT ERROR:\n{traceback.format_exc()}")
