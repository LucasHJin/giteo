"""Giteo: Debug Clips — inspect all clips on the current timeline.

Run from Workspace > Scripts to see what Resolve reports for each clip.
Prints to Resolve's console (Workspace > Console).
"""
import os
import sys
import traceback

try:
    _real = os.path.realpath(__file__)
except NameError:
    _real = None
if _real:
    _root = os.path.dirname(os.path.dirname(_real))
    if os.path.isdir(os.path.join(_root, "giteo")) and _root not in sys.path:
        sys.path.insert(0, _root)


def main():
    try:
        _resolve = resolve  # noqa: F821
    except NameError:
        print("[giteo-debug] Must run from Resolve Scripts menu.")
        return

    project = _resolve.GetProjectManager().GetCurrentProject()
    if not project:
        print("[giteo-debug] No project open.")
        return

    timeline = project.GetCurrentTimeline()
    if not timeline:
        print("[giteo-debug] No timeline active.")
        return

    print(f"\n{'='*60}")
    print(f"[giteo-debug] Timeline: {timeline.GetName()}")
    print(f"{'='*60}")

    video_count = timeline.GetTrackCount("video") or 0
    for track_idx in range(1, video_count + 1):
        clips = timeline.GetItemListInTrack("video", track_idx)
        if not clips:
            print(f"\n  V{track_idx}: (empty)")
            continue

        print(f"\n  V{track_idx}: {len(clips)} clip(s)")
        for i, clip in enumerate(clips):
            print(f"\n  --- Clip {i} ---")
            print(f"  Name:        {clip.GetName()}")
            print(f"  Start:       {clip.GetStart()}")
            print(f"  End:         {clip.GetEnd()}")
            print(f"  Duration:    {clip.GetDuration()}")
            print(f"  LeftOffset:  {clip.GetLeftOffset()}")

            mpi = clip.GetMediaPoolItem()
            if mpi:
                fp = mpi.GetClipProperty("File Path") or "(empty)"
                clip_type = mpi.GetClipProperty("Type") or "(unknown)"
                print(f"  File Path:   {fp}")
                print(f"  Type:        {clip_type}")
            else:
                print(f"  MediaPoolItem: None")

            # Fusion comp info
            try:
                comp_count = clip.GetFusionCompCount()
                print(f"  FusionCompCount: {comp_count}")
                if comp_count and comp_count > 0:
                    for ci in range(1, comp_count + 1):
                        comp = clip.GetFusionCompByIndex(ci)
                        if comp:
                            tools = comp.GetToolList() or {}
                            print(f"    Comp {ci}: {len(tools)} tool(s)")
                            for tname, tool in (tools.items() if isinstance(tools, dict) else enumerate(tools)):
                                try:
                                    attrs = tool.GetAttrs() or {}
                                    reg_id = attrs.get("TOOLS_RegID", "?")
                                    print(f"      Tool '{tname}': {reg_id}")

                                    if reg_id in ("TextPlus", "Text3D", "StyledText"):
                                        for inp_name in ("StyledText", "Font", "Size", "Bold", "Italic"):
                                            try:
                                                val = tool.GetInput(inp_name)
                                                print(f"        {inp_name}: {val!r}")
                                            except Exception:
                                                pass
                                except Exception as e:
                                    print(f"      Tool '{tname}': error reading attrs: {e}")
                        else:
                            print(f"    Comp {ci}: None")
            except AttributeError:
                print(f"  FusionCompCount: N/A (no API)")
            except Exception as e:
                print(f"  FusionCompCount: error: {e}")

            # Key properties
            for prop in ("Speed", "CompositeMode", "Opacity"):
                try:
                    val = clip.GetProperty(prop)
                    print(f"  {prop}: {val}")
                except Exception:
                    pass

    print(f"\n{'='*60}")
    print("[giteo-debug] Done. Copy this output and share for debugging.")
    print(f"{'='*60}\n")


try:
    main()
except Exception:
    print(f"[giteo-debug] ERROR:\n{traceback.format_exc()}")
