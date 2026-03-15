"""Giteo: Debug Title Insertion — test how Resolve handles title/generator inserts.

Run from Workspace > Scripts. Creates a temporary test timeline, runs experiments,
logs everything, then cleans up. Does NOT touch your real timeline.
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
    print(f"[debug-insert] {msg}")


def _dump_tracks(timeline, label):
    """Log the state of all video tracks."""
    _log(f"--- {label} ---")
    vcount = timeline.GetTrackCount("video") or 0
    _log(f"  Video tracks: {vcount}")
    for idx in range(1, vcount + 1):
        clips = timeline.GetItemListInTrack("video", idx) or []
        _log(f"  V{idx}: {len(clips)} clip(s)")
        for i, c in enumerate(clips):
            name = c.GetName() or "?"
            start = c.GetStart()
            end = c.GetEnd()
            dur = c.GetDuration()
            _log(f"    [{i}] '{name}' start={start} end={end} dur={dur}")
            try:
                ti = c.GetTrackTypeAndIndex()
                _log(f"         GetTrackTypeAndIndex() = {ti}")
            except Exception as e:
                _log(f"         GetTrackTypeAndIndex() ERROR: {e}")


def _test_return_value(timeline):
    """Test what InsertFusionTitleIntoTimeline actually returns."""
    _log("=== TEST 1: Return value of InsertFusionTitleIntoTimeline ===")
    result = timeline.InsertFusionTitleIntoTimeline("Text+")
    _log(f"  Return value: {result}")
    _log(f"  Type: {type(result)}")
    _log(f"  Is True: {result is True}")
    _log(f"  Is None: {result is None}")
    _log(f"  Bool: {bool(result)}")
    if result and result is not True:
        try:
            _log(f"  .GetName(): {result.GetName()}")
        except Exception as e:
            _log(f"  .GetName() ERROR: {e}")
        try:
            _log(f"  .GetStart(): {result.GetStart()}")
            _log(f"  .GetEnd(): {result.GetEnd()}")
            _log(f"  .GetDuration(): {result.GetDuration()}")
        except Exception as e:
            _log(f"  .GetStart/End/Duration ERROR: {e}")
        try:
            ti = result.GetTrackTypeAndIndex()
            _log(f"  .GetTrackTypeAndIndex(): {ti}")
        except Exception as e:
            _log(f"  .GetTrackTypeAndIndex() ERROR: {e}")
        try:
            fc = result.GetFusionCompCount()
            _log(f"  .GetFusionCompCount(): {fc}")
        except Exception as e:
            _log(f"  .GetFusionCompCount() ERROR: {e}")
    return result


def _test_track_lock(timeline):
    """Test if SetTrackLock exists and if locking V1 redirects inserts."""
    _log("=== TEST 2: Track locking behavior ===")

    has_lock = hasattr(timeline, "SetTrackLock")
    _log(f"  HasAttr SetTrackLock: {has_lock}")
    has_get_lock = hasattr(timeline, "GetIsTrackLocked")
    _log(f"  HasAttr GetIsTrackLocked: {has_get_lock}")

    if not has_lock:
        _log("  SKIP: SetTrackLock not available")
        return

    # Ensure V2 exists
    while timeline.GetTrackCount("video") < 2:
        timeline.AddTrack("video")
    _log(f"  Track count after AddTrack: {timeline.GetTrackCount('video')}")

    # Lock V1
    try:
        lock_result = timeline.SetTrackLock("video", 1, True)
        _log(f"  SetTrackLock(video, 1, True) = {lock_result}")
    except Exception as e:
        _log(f"  SetTrackLock ERROR: {e}")
        return

    try:
        is_locked = timeline.GetIsTrackLocked("video", 1)
        _log(f"  GetIsTrackLocked(video, 1) = {is_locked}")
    except Exception as e:
        _log(f"  GetIsTrackLocked ERROR: {e}")

    # Insert with V1 locked
    _log("  Inserting Text+ with V1 locked...")
    result = timeline.InsertFusionTitleIntoTimeline("Text+")
    _log(f"  Insert result: {result} (type={type(result)})")

    if result and result is not True:
        try:
            ti = result.GetTrackTypeAndIndex()
            _log(f"  Inserted clip track: {ti}")
        except Exception as e:
            _log(f"  GetTrackTypeAndIndex ERROR: {e}")

    _dump_tracks(timeline, "After insert with V1 locked")

    # Unlock V1
    try:
        timeline.SetTrackLock("video", 1, False)
        _log(f"  V1 unlocked")
    except Exception as e:
        _log(f"  Unlock ERROR: {e}")


def _test_playhead_insert(timeline, media_pool):
    """Test if playhead position affects where the title lands."""
    _log("=== TEST 3: Playhead positioning ===")

    try:
        tc_before = timeline.GetCurrentTimecode()
        _log(f"  Current timecode: {tc_before}")
        start_tc = timeline.GetStartTimecode()
        _log(f"  Start timecode: {start_tc}")
        start_frame = timeline.GetStartFrame()
        _log(f"  Start frame: {start_frame}")
        fps = timeline.GetSetting("timelineFrameRate")
        _log(f"  FPS: {fps}")
    except Exception as e:
        _log(f"  Read timecode ERROR: {e}")

    # Move playhead to 2 seconds in
    try:
        target_tc = "01:00:02:00"
        timeline.SetCurrentTimecode(target_tc)
        time.sleep(0.3)
        actual_tc = timeline.GetCurrentTimecode()
        _log(f"  SetCurrentTimecode('{target_tc}') -> actual: '{actual_tc}'")
    except Exception as e:
        _log(f"  SetCurrentTimecode ERROR: {e}")

    _log("  Inserting Text+ at playhead (01:00:02:00)...")
    result = timeline.InsertFusionTitleIntoTimeline("Text+")
    _log(f"  Insert result: {result}")
    if result and result is not True:
        try:
            _log(f"  Clip start: {result.GetStart()}")
            _log(f"  Clip end: {result.GetEnd()}")
            _log(f"  Clip duration: {result.GetDuration()}")
            ti = result.GetTrackTypeAndIndex()
            _log(f"  Clip track: {ti}")
        except Exception as e:
            _log(f"  Read clip props ERROR: {e}")

    _dump_tracks(timeline, "After playhead insert")


def _test_import_fusion_comp(timeline):
    """Test ImportFusionComp behavior."""
    _log("=== TEST 4: ImportFusionComp ===")

    clips = timeline.GetItemListInTrack("video", 1) or []
    if not clips:
        _log("  SKIP: No clips on V1 to test with")
        return

    clip = clips[-1]
    _log(f"  Testing on clip: '{clip.GetName()}'")

    try:
        fc = clip.GetFusionCompCount()
        _log(f"  FusionCompCount: {fc}")
    except Exception as e:
        _log(f"  FusionCompCount ERROR: {e}")
        return

    if fc and fc >= 1:
        try:
            comp = clip.GetFusionCompByIndex(1)
            _log(f"  GetFusionCompByIndex(1): {comp}")
            if comp:
                tools = comp.GetToolList() or {}
                tool_list = list(tools.values()) if isinstance(tools, dict) else list(tools)
                _log(f"  Tool count: {len(tool_list)}")
                for t in tool_list:
                    try:
                        attrs = t.GetAttrs() or {}
                        reg_id = attrs.get("TOOLS_RegID", "unknown")
                        _log(f"    Tool: {reg_id}")
                        styled = t.GetInput("StyledText")
                        if styled is not None:
                            _log(f"      StyledText: {repr(styled)}")
                        font = t.GetInput("Font")
                        if font is not None:
                            _log(f"      Font: {font}")
                    except Exception as e:
                        _log(f"    Tool read ERROR: {e}")
        except Exception as e:
            _log(f"  GetFusionComp ERROR: {e}")


def _test_set_text(timeline):
    """Test if we can set text properties on an inserted Text+ clip."""
    _log("=== TEST 5: Set text via Fusion API ===")

    clips = timeline.GetItemListInTrack("video", 1) or []
    text_clips = [c for c in clips if c.GetName() == "Text+"]
    if not text_clips:
        _log("  SKIP: No Text+ clips on V1")
        return

    clip = text_clips[-1]
    _log(f"  Testing on last Text+ clip")

    try:
        comp = clip.GetFusionCompByIndex(1)
        if not comp:
            _log("  No Fusion comp found")
            return
        tools = comp.GetToolList(False, "TextPlus") or {}
        tool_list = list(tools.values()) if isinstance(tools, dict) else list(tools)
        if not tool_list:
            _log("  No TextPlus tool found, trying all tools...")
            all_tools = comp.GetToolList() or {}
            tool_list = list(all_tools.values()) if isinstance(all_tools, dict) else list(all_tools)

        if not tool_list:
            _log("  No tools found at all")
            return

        tool = tool_list[0]
        old_text = tool.GetInput("StyledText")
        _log(f"  Current StyledText: {repr(old_text)}")

        _log("  Setting StyledText to 'GITEO_TEST'...")
        tool.SetInput("StyledText", "GITEO_TEST")
        time.sleep(0.2)

        new_text = tool.GetInput("StyledText")
        _log(f"  After set, StyledText: {repr(new_text)}")
        _log(f"  SetInput worked: {new_text == 'GITEO_TEST'}")
    except Exception as e:
        _log(f"  Set text ERROR: {e}")
        traceback.print_exc()


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
    _log("TITLE INSERTION DEBUG")
    _log("=" * 60)

    # Create a test timeline so we don't touch the user's work
    test_name = f"giteo_debug_test_{int(time.time())}"
    _log(f"Creating test timeline: {test_name}")
    test_tl = media_pool.CreateEmptyTimeline(test_name)
    if not test_tl:
        _log("ERROR: Could not create test timeline")
        return

    project.SetCurrentTimeline(test_tl)
    time.sleep(0.5)

    try:
        _dump_tracks(test_tl, "Initial empty timeline")
        _test_return_value(test_tl)
        _dump_tracks(test_tl, "After TEST 1")
        _test_track_lock(test_tl)
        _test_playhead_insert(test_tl, media_pool)
        _test_import_fusion_comp(test_tl)
        _test_set_text(test_tl)
        _dump_tracks(test_tl, "Final state")
    except Exception as e:
        _log(f"UNEXPECTED ERROR: {e}")
        traceback.print_exc()

    _log("")
    _log("=" * 60)
    _log(f"Done. Delete '{test_name}' manually from Resolve.")
    _log("Copy this output and share for debugging.")
    _log("=" * 60)


try:
    main()
except Exception:
    print(f"[debug-insert] SCRIPT ERROR:\n{traceback.format_exc()}")
