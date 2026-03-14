"""Dataclasses for timeline entities."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Transform:
    pan: float = 0.0
    tilt: float = 0.0
    zoom_x: float = 1.0
    zoom_y: float = 1.0
    opacity: float = 100.0

    def to_dict(self) -> dict:
        return {
            "Pan": self.pan,
            "Tilt": self.tilt,
            "ZoomX": self.zoom_x,
            "ZoomY": self.zoom_y,
            "Opacity": self.opacity,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Transform":
        return cls(
            pan=d.get("Pan", 0.0),
            tilt=d.get("Tilt", 0.0),
            zoom_x=d.get("ZoomX", 1.0),
            zoom_y=d.get("ZoomY", 1.0),
            opacity=d.get("Opacity", 100.0),
        )


RETIME_PROCESS_NAMES = {
    0: "project_default",
    1: "nearest",
    2: "frame_blend",
    3: "optical_flow",
}

MOTION_EST_NAMES = {
    0: "project_default",
    1: "standard_faster",
    2: "standard_better",
    3: "enhanced_faster",
    4: "enhanced_better",
    5: "speed_warp",
}


@dataclass
class SpeedChange:
    """Retime/speed change state for a clip.

    Resolve exposes constant speed changes via GetProperty("Speed").
    Variable speed ramps (speed curves) are NOT accessible via the API.

    Attributes:
        speed_percent: Playback speed as percentage. 100.0 = normal,
            200.0 = 2x fast, 50.0 = half speed (slow-mo).
        retime_process: Interpolation method (0=project, 1=nearest,
            2=frame_blend, 3=optical_flow).
        motion_estimation: Motion estimation quality for optical flow
            (0=project, 1..5 = standard_faster through speed_warp).
    """
    speed_percent: float = 100.0
    retime_process: int = 0
    motion_estimation: int = 0

    @property
    def is_retimed(self) -> bool:
        return self.speed_percent != 100.0

    @property
    def multiplier(self) -> float:
        return self.speed_percent / 100.0

    def to_dict(self) -> dict:
        d: dict = {"speed_percent": round(self.speed_percent, 4)}
        if self.retime_process != 0:
            d["retime_process"] = self.retime_process
            d["retime_process_name"] = RETIME_PROCESS_NAMES.get(
                self.retime_process, "unknown"
            )
        if self.motion_estimation != 0:
            d["motion_estimation"] = self.motion_estimation
            d["motion_estimation_name"] = MOTION_EST_NAMES.get(
                self.motion_estimation, "unknown"
            )
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SpeedChange":
        return cls(
            speed_percent=d.get("speed_percent", 100.0),
            retime_process=d.get("retime_process", 0),
            motion_estimation=d.get("motion_estimation", 0),
        )


@dataclass
class VideoItem:
    id: str
    name: str
    media_ref: str
    record_start_frame: int
    record_end_frame: int
    source_start_frame: int
    source_end_frame: int
    track_index: int
    transform: Transform = field(default_factory=Transform)
    speed: SpeedChange = field(default_factory=SpeedChange)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "media_ref": self.media_ref,
            "record_start_frame": self.record_start_frame,
            "record_end_frame": self.record_end_frame,
            "source_start_frame": self.source_start_frame,
            "source_end_frame": self.source_end_frame,
            "track_index": self.track_index,
            "transform": self.transform.to_dict(),
        }
        if self.speed.is_retimed:
            d["speed"] = self.speed.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "VideoItem":
        return cls(
            id=d["id"],
            name=d["name"],
            media_ref=d["media_ref"],
            record_start_frame=d["record_start_frame"],
            record_end_frame=d["record_end_frame"],
            source_start_frame=d["source_start_frame"],
            source_end_frame=d["source_end_frame"],
            track_index=d["track_index"],
            transform=Transform.from_dict(d.get("transform", {})),
            speed=SpeedChange.from_dict(d["speed"]) if "speed" in d else SpeedChange(),
        )


@dataclass
class VideoTrack:
    index: int
    items: List[VideoItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VideoTrack":
        return cls(
            index=d["index"],
            items=[VideoItem.from_dict(i) for i in d.get("items", [])],
        )


@dataclass
class AudioItem:
    id: str
    media_ref: str
    start_frame: int
    end_frame: int
    volume: float = 0.0
    pan: float = 0.0
    speed: SpeedChange = field(default_factory=SpeedChange)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "media_ref": self.media_ref,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "volume": self.volume,
            "pan": self.pan,
        }
        if self.speed.is_retimed:
            d["speed"] = self.speed.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AudioItem":
        return cls(
            id=d["id"],
            media_ref=d["media_ref"],
            start_frame=d["start_frame"],
            end_frame=d["end_frame"],
            volume=d.get("volume", 0.0),
            pan=d.get("pan", 0.0),
            speed=SpeedChange.from_dict(d["speed"]) if "speed" in d else SpeedChange(),
        )


@dataclass
class AudioTrack:
    index: int
    items: List[AudioItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AudioTrack":
        return cls(
            index=d["index"],
            items=[AudioItem.from_dict(i) for i in d.get("items", [])],
        )


@dataclass
class ColorNodeGrade:
    """Color correction values for a single node in the color graph.

    Captures CDL (Color Decision List) values and primary color wheels
    that Resolve exposes via its scripting API.
    """
    index: int = 1
    label: str = ""
    lut: str = ""

    # CDL values (ASC-CDL standard: slope * input + offset) ^ power
    slope: Optional[List[float]] = None      # [R, G, B] multipliers (default 1,1,1)
    offset: Optional[List[float]] = None     # [R, G, B] offsets (default 0,0,0)
    power: Optional[List[float]] = None      # [R, G, B] gamma (default 1,1,1)
    saturation: Optional[float] = None       # Overall saturation (default 1.0)

    # Primary color wheels (Resolve's Lift/Gamma/Gain/Offset wheels)
    lift: Optional[Dict[str, float]] = None    # {"r": 0, "g": 0, "b": 0, "y": 0}
    gamma: Optional[Dict[str, float]] = None   # {"r": 0, "g": 0, "b": 0, "y": 0}
    gain: Optional[Dict[str, float]] = None    # {"r": 1, "g": 1, "b": 1, "y": 1}
    color_offset: Optional[Dict[str, float]] = None  # {"r": 0, "g": 0, "b": 0, "y": 0}

    # Contrast / Pivot / Hue / Saturation adjustments
    contrast: Optional[float] = None
    pivot: Optional[float] = None
    hue: Optional[float] = None
    color_boost: Optional[float] = None

    def to_dict(self) -> dict:
        d: dict = {"index": self.index, "label": self.label, "lut": self.lut}
        # Only include color values that were actually read (not None)
        for key in ["slope", "offset", "power", "saturation",
                     "lift", "gamma", "gain", "color_offset",
                     "contrast", "pivot", "hue", "color_boost"]:
            val = getattr(self, key)
            if val is not None:
                d[key] = val
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ColorNodeGrade":
        return cls(
            index=d.get("index", 1),
            label=d.get("label", ""),
            lut=d.get("lut", ""),
            slope=d.get("slope"),
            offset=d.get("offset"),
            power=d.get("power"),
            saturation=d.get("saturation"),
            lift=d.get("lift"),
            gamma=d.get("gamma"),
            gain=d.get("gain"),
            color_offset=d.get("color_offset"),
            contrast=d.get("contrast"),
            pivot=d.get("pivot"),
            hue=d.get("hue"),
            color_boost=d.get("color_boost"),
        )


@dataclass
class ColorGrade:
    """Color grade state for a single clip.

    Captures per-node color correction values (CDL, primary wheels,
    contrast/hue/saturation), structural info, and optionally a DRX
    still for full-fidelity binary backup.
    """
    num_nodes: int = 1
    nodes: List[ColorNodeGrade] = field(default_factory=list)
    version_name: str = ""
    drx_file: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "num_nodes": self.num_nodes,
            "nodes": [n.to_dict() for n in self.nodes],
            "version_name": self.version_name,
            "drx_file": self.drx_file,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ColorGrade":
        raw_nodes = d.get("nodes", [])
        nodes = []
        for n in raw_nodes:
            if isinstance(n, dict):
                nodes.append(ColorNodeGrade.from_dict(n))
            else:
                nodes.append(n)
        return cls(
            num_nodes=d.get("num_nodes", 1),
            nodes=nodes,
            version_name=d.get("version_name", ""),
            drx_file=d.get("drx_file"),
        )


@dataclass
class Marker:
    frame: int
    color: str = "Blue"
    name: str = ""
    note: str = ""
    duration: int = 1

    def to_dict(self) -> dict:
        return {
            "frame": self.frame,
            "color": self.color,
            "name": self.name,
            "note": self.note,
            "duration": self.duration,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Marker":
        return cls(
            frame=d["frame"],
            color=d.get("color", "Blue"),
            name=d.get("name", ""),
            note=d.get("note", ""),
            duration=d.get("duration", 1),
        )


@dataclass
class Asset:
    filename: str
    original_path: str
    duration_frames: int
    codec: str
    resolution: str

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "original_path": self.original_path,
            "duration_frames": self.duration_frames,
            "codec": self.codec,
            "resolution": self.resolution,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Asset":
        return cls(
            filename=d["filename"],
            original_path=d["original_path"],
            duration_frames=d["duration_frames"],
            codec=d["codec"],
            resolution=d["resolution"],
        )


@dataclass
class TimelineMetadata:
    project_name: str = ""
    timeline_name: str = ""
    frame_rate: float = 24.0
    width: int = 1920
    height: int = 1080
    start_timecode: str = "01:00:00:00"
    video_track_count: int = 1
    audio_track_count: int = 1

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "timeline_name": self.timeline_name,
            "frame_rate": self.frame_rate,
            "resolution": {"width": self.width, "height": self.height},
            "start_timecode": self.start_timecode,
            "track_count": {
                "video": self.video_track_count,
                "audio": self.audio_track_count,
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TimelineMetadata":
        res = d.get("resolution", {})
        tc = d.get("track_count", {})
        return cls(
            project_name=d.get("project_name", ""),
            timeline_name=d.get("timeline_name", ""),
            frame_rate=d.get("frame_rate", 24.0),
            width=res.get("width", 1920),
            height=res.get("height", 1080),
            start_timecode=d.get("start_timecode", "01:00:00:00"),
            video_track_count=tc.get("video", 1),
            audio_track_count=tc.get("audio", 1),
        )


@dataclass
class Timeline:
    """Complete timeline state, split into domain files."""
    metadata: TimelineMetadata = field(default_factory=TimelineMetadata)
    video_tracks: List[VideoTrack] = field(default_factory=list)
    audio_tracks: List[AudioTrack] = field(default_factory=list)
    color_grades: Dict[str, ColorGrade] = field(default_factory=dict)
    effects: dict = field(default_factory=dict)
    markers: List[Marker] = field(default_factory=list)
    assets: Dict[str, Asset] = field(default_factory=dict)
