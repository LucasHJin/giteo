"""Mock DaVinci Resolve API for testing.

Mimics the Resolve Python API so serializer/deserializer can be tested
without a running Resolve instance.
"""

import os


class MockMediaPoolItem:
    def __init__(self, filepath="", frames=0, codec="ProRes 422", resolution="1920x1080"):
        self._props = {
            "File Path": filepath,
            "Frames": str(frames),
            "Video Codec": codec,
            "Resolution": resolution,
        }

    def GetClipProperty(self, prop):
        return self._props.get(prop, "")


class MockFusionTool:
    """Mock a Fusion tool (e.g. TextPlus) with readable inputs."""

    def __init__(self, tool_id="TextPlus", inputs=None):
        self._tool_id = tool_id
        self._inputs = inputs or {}

    def GetInput(self, name):
        return self._inputs.get(name)

    def SetInput(self, name, value):
        self._inputs[name] = value

    def GetAttrs(self):
        return {"TOOLS_RegID": self._tool_id}


class MockFusionComp:
    """Mock a Fusion composition containing tools."""

    def __init__(self, tools=None):
        self._tools = tools or {}

    def GetToolList(self, selected=False, tool_type=None):
        if tool_type:
            return {k: v for k, v in self._tools.items()
                    if v.GetAttrs()["TOOLS_RegID"] == tool_type}
        return dict(self._tools)

    def FindToolByID(self, tool_id):
        for tool in self._tools.values():
            if tool.GetAttrs()["TOOLS_RegID"] == tool_id:
                return tool
        return None


class MockTimelineItem:
    """Mock a clip on the timeline.

    Mimics the color-related API surface of Resolve's TimelineItem:
    - GetProperty/SetProperty: clip-level properties (Contrast, Saturation, etc.)
    - SetCDL: write CDL values (SetCDL exists in real API, GetCDL does NOT)
    - SetLUT: write LUT path per node (SetLUT exists, GetLUT does NOT)
    - GetNumNodes/GetNodeLabel: undocumented but working in most Resolve versions
    - GetFusionCompCount/GetFusionCompByIndex: Fusion composition access
    - ExportFusionComp/ImportFusionComp: Fusion comp export/import
    """

    def __init__(
        self,
        name="Clip",
        start=0,
        end=100,
        left_offset=0,
        media_pool_item=None,
        properties=None,
        num_nodes=1,
        node_labels=None,
        fusion_comp=None,
    ):
        self._name = name
        self._start = start
        self._end = end
        self._left_offset = left_offset
        self._media_pool_item = media_pool_item
        self._properties = properties or {
            "Pan": 0.0,
            "Tilt": 0.0,
            "ZoomX": 1.0,
            "ZoomY": 1.0,
            "Opacity": 100.0,
            "Volume": 0.0,
            "Contrast": 1.0,
            "Saturation": 1.0,
            "Speed": 100.0,
            "RetimeProcess": 0,
            "MotionEstimation": 0,
        }
        self._num_nodes = num_nodes
        self._node_labels = node_labels or {}
        self._node_luts = {}
        self._cdl = {}
        self._fusion_comp = fusion_comp
        self._imported_comp_path = None

    def GetName(self):
        return self._name

    def GetStart(self):
        return self._start

    def GetEnd(self):
        return self._end

    def GetDuration(self):
        return self._end - self._start

    def GetLeftOffset(self):
        return self._left_offset

    def GetMediaPoolItem(self):
        return self._media_pool_item

    def GetProperty(self, prop):
        return self._properties.get(prop)

    def SetProperty(self, prop, value):
        self._properties[prop] = value

    def GetNumNodes(self):
        return self._num_nodes

    def GetNodeLabel(self, node_index):
        return self._node_labels.get(node_index, "")

    def SetCDL(self, cdl_map):
        self._cdl = cdl_map
        return True

    def SetLUT(self, node_index, lut_path):
        self._node_luts[node_index] = lut_path
        return True

    def GetFusionCompCount(self):
        return 1 if self._fusion_comp else 0

    def GetFusionCompByIndex(self, index):
        if index == 1 and self._fusion_comp:
            return self._fusion_comp
        return None

    def ExportFusionComp(self, filepath, comp_index):
        if self._fusion_comp and comp_index == 1:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "w") as f:
                inputs = {}
                tools = self._fusion_comp.GetToolList()
                for name, tool in tools.items():
                    inputs[name] = {k: v for k, v in tool._inputs.items()}
                f.write(repr(inputs))
            return True
        return False

    def ImportFusionComp(self, filepath):
        self._imported_comp_path = filepath
        return os.path.exists(filepath)


class MockTimeline:
    """Mock a Resolve timeline."""

    def __init__(
        self,
        name="Test Timeline",
        video_tracks=None,
        audio_tracks=None,
        markers=None,
        settings=None,
    ):
        self._name = name
        self._video_tracks = video_tracks or {}  # {track_index: [MockTimelineItem]}
        self._audio_tracks = audio_tracks or {}
        self._markers = markers or {}
        self._settings = settings or {
            "timelineFrameRate": "24",
            "timelineResolutionWidth": "1920",
            "timelineResolutionHeight": "1080",
        }
        self._start_timecode = "01:00:00:00"

    def GetName(self):
        return self._name

    def GetTrackCount(self, track_type):
        if track_type == "video":
            return max(self._video_tracks.keys()) if self._video_tracks else 0
        elif track_type == "audio":
            return max(self._audio_tracks.keys()) if self._audio_tracks else 0
        return 0

    def GetItemListInTrack(self, track_type, index):
        if track_type == "video":
            return self._video_tracks.get(index, [])
        elif track_type == "audio":
            return self._audio_tracks.get(index, [])
        return []

    def GetMarkers(self):
        return dict(self._markers)

    def GetSetting(self, key):
        return self._settings.get(key)

    def SetSetting(self, key, value):
        self._settings[key] = value

    def GetStartTimecode(self):
        return self._start_timecode

    def SetStartTimecode(self, tc):
        self._start_timecode = tc

    def AddMarker(self, frame, color, name, note, duration):
        self._markers[frame] = {
            "color": color,
            "name": name,
            "note": note,
            "duration": duration,
        }

    def SetName(self, name):
        self._name = name
        return True

    def DeleteMarkerAtFrame(self, frame):
        self._markers.pop(frame, None)

    def GetStartFrame(self):
        return 0

    def SetCurrentTimecode(self, tc):
        self._current_timecode = tc

    def GetCurrentTimecode(self):
        return getattr(self, "_current_timecode", "01:00:00:00")

    def InsertFusionGeneratorIntoTimeline(self, generator_name):
        """Insert a Fusion generator clip. Returns a dict with the TimelineItem."""
        return self._insert_fusion_clip(generator_name)

    def InsertFusionTitleIntoTimeline(self, title_name):
        """Insert a Fusion title clip (Text+, etc.). Returns a dict with the TimelineItem."""
        return self._insert_fusion_clip(title_name)

    def InsertOFXGeneratorIntoTimeline(self, generator_name):
        """Insert an OFX generator clip."""
        return self._insert_fusion_clip(generator_name)

    def _insert_fusion_clip(self, name):
        item = MockTimelineItem(
            name=name,
            start=0,
            end=120,
            left_offset=0,
            media_pool_item=None,
        )
        if 1 not in self._video_tracks:
            self._video_tracks[1] = []
        self._video_tracks[1].append(item)
        return item

    def AddTrack(self, track_type):
        if track_type == "video":
            idx = max(self._video_tracks.keys(), default=0) + 1
            self._video_tracks[idx] = []
        elif track_type == "audio":
            idx = max(self._audio_tracks.keys(), default=0) + 1
            self._audio_tracks[idx] = []


class MockMediaPool:
    def __init__(self):
        self._root = MockFolder()
        self._timelines = []

    def GetRootFolder(self):
        return self._root

    def ImportMedia(self, paths):
        items = []
        for p in paths:
            items.append(MockMediaPoolItem(filepath=p))
        return items

    def AppendToTimeline(self, clip_infos):
        pass

    def CreateEmptyTimeline(self, name):
        tl = MockTimeline(name=name)
        self._timelines.append(tl)
        return tl

    def CreateTimelineFromClips(self, name, clip_infos):
        """Atomic timeline creation with clips — mirrors Resolve API."""
        tl = MockTimeline(name=name)
        items = []
        for info in clip_infos:
            pool_item = info.get("mediaPoolItem")
            start = info.get("startFrame", 0)
            end = info.get("endFrame", 100)
            clip_name = ""
            if pool_item:
                clip_name = os.path.basename(
                    pool_item.GetClipProperty("File Path") or "Clip"
                )
            item = MockTimelineItem(
                name=clip_name or "Clip",
                start=start,
                end=end,
                left_offset=start,
                media_pool_item=pool_item,
            )
            items.append(item)
        if items:
            tl._video_tracks[1] = items
        self._timelines.append(tl)
        return tl


class MockFolder:
    def __init__(self):
        self._clips = []

    def GetClipList(self):
        return self._clips


class MockProject:
    def __init__(self, name="Test Project", timeline=None):
        self._name = name
        self._timeline = timeline or MockTimeline()
        self._media_pool = MockMediaPool()

    def GetName(self):
        return self._name

    def GetCurrentTimeline(self):
        return self._timeline

    def SetCurrentTimeline(self, timeline):
        self._timeline = timeline
        return True

    def GetMediaPool(self):
        return self._media_pool


class MockProjectManager:
    def __init__(self, project=None):
        self._project = project or MockProject()

    def GetCurrentProject(self):
        return self._project


class MockResolve:
    def __init__(self, project=None):
        self._pm = MockProjectManager(project)

    def GetProjectManager(self):
        return self._pm


def create_text_clip(name="Text+", text="Hello World", font="Arial",
                     size=0.1, bold=False, italic=False,
                     color_r=1.0, color_g=1.0, color_b=1.0,
                     start=0, end=120, track_index=1):
    """Create a mock Text+ generator clip with Fusion composition."""
    text_tool = MockFusionTool(
        tool_id="TextPlus",
        inputs={
            "StyledText": text,
            "Font": font,
            "Size": size,
            "Bold": 1 if bold else 0,
            "Italic": 1 if italic else 0,
            "Red1": color_r,
            "Green1": color_g,
            "Blue1": color_b,
        },
    )
    fusion_comp = MockFusionComp(tools={"Template": text_tool})

    clip = MockTimelineItem(
        name=name,
        start=start,
        end=end,
        left_offset=0,
        media_pool_item=MockMediaPoolItem(filepath=""),
        properties={
            "Pan": 0.0, "Tilt": 0.0, "ZoomX": 1.0, "ZoomY": 1.0,
            "Opacity": 100.0, "Volume": 0.0,
            "Contrast": 1.0, "Saturation": 1.0,
            "Speed": 100.0, "RetimeProcess": 0, "MotionEstimation": 0,
        },
        fusion_comp=fusion_comp,
    )
    return clip


def create_test_timeline():
    """Create a mock timeline with sample clips for testing."""
    media1 = MockMediaPoolItem(
        filepath="/Volumes/Media/Interview_A_001.mov",
        frames=14400,
        codec="ProRes 422",
        resolution="1920x1080",
    )
    media2 = MockMediaPoolItem(
        filepath="/Volumes/Media/BRoll_001.mov",
        frames=7200,
        codec="ProRes 422",
        resolution="1920x1080",
    )

    clip1 = MockTimelineItem(
        name="Interview_A_001",
        start=0,
        end=720,
        left_offset=100,
        media_pool_item=media1,
    )
    clip2 = MockTimelineItem(
        name="BRoll_001",
        start=720,
        end=960,
        left_offset=0,
        media_pool_item=media2,
    )

    audio1 = MockTimelineItem(
        name="Interview_A_001_audio",
        start=0,
        end=720,
        left_offset=100,
        media_pool_item=media1,
        properties={"Volume": -3.0, "Pan": 0.0},
    )

    timeline = MockTimeline(
        name="Main Edit v3",
        video_tracks={1: [clip1, clip2]},
        audio_tracks={1: [audio1]},
        markers={
            240: {"color": "Blue", "name": "Fix jump cut", "note": "Transition feels abrupt", "duration": 1},
            720: {"color": "Green", "name": "B-roll start", "note": "", "duration": 1},
        },
    )

    project = MockProject(name="My Documentary", timeline=timeline)
    # Populate the media pool's root folder so _find_media_pool_item can
    # locate clips without requiring files on disk
    project.GetMediaPool().GetRootFolder()._clips = [media1, media2]
    return MockResolve(project), project, timeline
