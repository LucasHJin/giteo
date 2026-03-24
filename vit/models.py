"""Dataclasses for timeline entities."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


COMPOSITE_MODE_NAMES = {
    0: "normal", 1: "add", 2: "subtract", 3: "difference",
    4: "multiply", 5: "screen", 6: "overlay", 7: "hard_light",
    8: "soft_light", 9: "darken", 10: "lighten", 11: "color_dodge",
    12: "color_burn", 13: "exclusion", 14: "hue", 15: "saturate",
    16: "colorize", 17: "luma_mask", 18: "divide", 19: "linear_dodge",
    20: "linear_burn", 21: "linear_light", 22: "vivid_light",
    23: "pin_light", 24: "hard_mix", 25: "lighter_color",
    26: "darker_color", 27: "foreground", 28: "alpha",
    29: "inverted_alpha", 30: "lum", 31: "inverted_lum",
}

DYNAMIC_ZOOM_EASE_NAMES = {
    0: "linear",
    1: "ease_in",
    2: "ease_out",
    3: "ease_in_and_out",
}


@dataclass
class Transform:
    pan: float = 0.0
    tilt: float = 0.0
    zoom_x: float = 1.0
    zoom_y: float = 1.0
    opacity: float = 100.0
    rotation_angle: float = 0.0
    anchor_x: float = 0.0
    anchor_y: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    flip_x: bool = False
    flip_y: bool = False
    crop_left: float = 0.0
    crop_right: float = 0.0
    crop_top: float = 0.0
    crop_bottom: float = 0.0
    crop_softness: float = 0.0
    crop_retain: bool = False
    distortion: float = 0.0

    def to_dict(self) -> dict:
        d: dict = {
            "Pan": self.pan,
            "Tilt": self.tilt,
            "ZoomX": self.zoom_x,
            "ZoomY": self.zoom_y,
            "Opacity": self.opacity,
        }
        if self.rotation_angle != 0.0:
            d["RotationAngle"] = self.rotation_angle
        if self.anchor_x != 0.0:
            d["AnchorPointX"] = self.anchor_x
        if self.anchor_y != 0.0:
            d["AnchorPointY"] = self.anchor_y
        if self.pitch != 0.0:
            d["Pitch"] = self.pitch
        if self.yaw != 0.0:
            d["Yaw"] = self.yaw
        if self.flip_x:
            d["FlipX"] = True
        if self.flip_y:
            d["FlipY"] = True
        if self.crop_left != 0.0:
            d["CropLeft"] = self.crop_left
        if self.crop_right != 0.0:
            d["CropRight"] = self.crop_right
        if self.crop_top != 0.0:
            d["CropTop"] = self.crop_top
        if self.crop_bottom != 0.0:
            d["CropBottom"] = self.crop_bottom
        if self.crop_softness != 0.0:
            d["CropSoftness"] = self.crop_softness
        if self.crop_retain:
            d["CropRetain"] = True
        if self.distortion != 0.0:
            d["Distortion"] = self.distortion
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Transform":
        return cls(
            pan=d.get("Pan", 0.0),
            tilt=d.get("Tilt", 0.0),
            zoom_x=d.get("ZoomX", 1.0),
            zoom_y=d.get("ZoomY", 1.0),
            opacity=d.get("Opacity", 100.0),
            rotation_angle=d.get("RotationAngle", 0.0),
            anchor_x=d.get("AnchorPointX", 0.0),
            anchor_y=d.get("AnchorPointY", 0.0),
            pitch=d.get("Pitch", 0.0),
            yaw=d.get("Yaw", 0.0),
            flip_x=d.get("FlipX", False),
            flip_y=d.get("FlipY", False),
            crop_left=d.get("CropLeft", 0.0),
            crop_right=d.get("CropRight", 0.0),
            crop_top=d.get("CropTop", 0.0),
            crop_bottom=d.get("CropBottom", 0.0),
            crop_softness=d.get("CropSoftness", 0.0),
            crop_retain=d.get("CropRetain", False),
            distortion=d.get("Distortion", 0.0),
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
class TextProperties:
    """Text properties for generator/title clips (Text+, Text3D, etc.)."""
    styled_text: str = ""
    font: str = ""
    size: float = 0.0
    bold: bool = False
    italic: bool = False
    color: Optional[Dict[str, float]] = None

    def to_dict(self) -> dict:
        d: dict = {}
        if self.styled_text:
            d["styled_text"] = self.styled_text
        if self.font:
            d["font"] = self.font
        if self.size > 0:
            d["size"] = self.size
        if self.bold:
            d["bold"] = True
        if self.italic:
            d["italic"] = True
        if self.color:
            d["color"] = self.color
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TextProperties":
        return cls(
            styled_text=d.get("styled_text", ""),
            font=d.get("font", ""),
            size=d.get("size", 0.0),
            bold=d.get("bold", False),
            italic=d.get("italic", False),
            color=d.get("color"),
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
    composite_mode: int = 0
    dynamic_zoom_ease: int = 0
    clip_enabled: bool = True
    item_type: str = "media"
    generator_name: str = ""
    fusion_comp_file: str = ""
    text_properties: Optional[TextProperties] = None

    @property
    def is_generator(self) -> bool:
        return self.item_type in ("generator", "title")

    @property
    def is_title(self) -> bool:
        return self.item_type == "title"

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
        if self.composite_mode != 0:
            d["composite_mode"] = self.composite_mode
            d["composite_mode_name"] = COMPOSITE_MODE_NAMES.get(
                self.composite_mode, "unknown"
            )
        if self.dynamic_zoom_ease != 0:
            d["dynamic_zoom_ease"] = self.dynamic_zoom_ease
            d["dynamic_zoom_ease_name"] = DYNAMIC_ZOOM_EASE_NAMES.get(
                self.dynamic_zoom_ease, "unknown"
            )
        if not self.clip_enabled:
            d["clip_enabled"] = False
        if self.item_type != "media":
            d["item_type"] = self.item_type
        if self.generator_name:
            d["generator_name"] = self.generator_name
        if self.fusion_comp_file:
            d["fusion_comp_file"] = self.fusion_comp_file
        if self.text_properties:
            d["text_properties"] = self.text_properties.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "VideoItem":
        text_props = None
        if "text_properties" in d:
            tp = d["text_properties"]
            text_props = TextProperties.from_dict(tp) if isinstance(tp, dict) else tp
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
            composite_mode=d.get("composite_mode", 0),
            dynamic_zoom_ease=d.get("dynamic_zoom_ease", 0),
            clip_enabled=d.get("clip_enabled", True),
            item_type=d.get("item_type", "media"),
            generator_name=d.get("generator_name", ""),
            fusion_comp_file=d.get("fusion_comp_file", ""),
            text_properties=text_props,
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

    # Per-channel primary wheel values (R/G/B/M per wheel)
    lift_r: Optional[float] = None
    lift_g: Optional[float] = None
    lift_b: Optional[float] = None
    lift_m: Optional[float] = None
    gamma_r: Optional[float] = None
    gamma_g: Optional[float] = None
    gamma_b: Optional[float] = None
    gamma_m: Optional[float] = None
    gain_r: Optional[float] = None
    gain_g: Optional[float] = None
    gain_b: Optional[float] = None
    gain_m: Optional[float] = None
    offset_r: Optional[float] = None
    offset_g: Optional[float] = None
    offset_b: Optional[float] = None
    offset_m: Optional[float] = None

    # White balance
    temperature: Optional[float] = None
    tint: Optional[float] = None

    # Sharpness and noise reduction
    sharpness: Optional[float] = None
    noise_reduction_luma: Optional[float] = None
    noise_reduction_chroma: Optional[float] = None

    # Tool names in this node (e.g., ["Primary Offset"]) — for change detection
    tools: Optional[List[str]] = None

    def to_dict(self) -> dict:
        d: dict = {"index": self.index, "label": self.label, "lut": self.lut}
        # Only include color values that were actually read (not None)
        for key in ["slope", "offset", "power", "saturation",
                     "lift", "gamma", "gain", "color_offset",
                     "contrast", "pivot", "hue", "color_boost",
                     "lift_r", "lift_g", "lift_b", "lift_m",
                     "gamma_r", "gamma_g", "gamma_b", "gamma_m",
                     "gain_r", "gain_g", "gain_b", "gain_m",
                     "offset_r", "offset_g", "offset_b", "offset_m",
                     "temperature", "tint", "sharpness",
                     "noise_reduction_luma", "noise_reduction_chroma",
                     "tools"]:
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
            lift_r=d.get("lift_r"),
            lift_g=d.get("lift_g"),
            lift_b=d.get("lift_b"),
            lift_m=d.get("lift_m"),
            gamma_r=d.get("gamma_r"),
            gamma_g=d.get("gamma_g"),
            gamma_b=d.get("gamma_b"),
            gamma_m=d.get("gamma_m"),
            gain_r=d.get("gain_r"),
            gain_g=d.get("gain_g"),
            gain_b=d.get("gain_b"),
            gain_m=d.get("gain_m"),
            offset_r=d.get("offset_r"),
            offset_g=d.get("offset_g"),
            offset_b=d.get("offset_b"),
            offset_m=d.get("offset_m"),
            temperature=d.get("temperature"),
            tint=d.get("tint"),
            sharpness=d.get("sharpness"),
            noise_reduction_luma=d.get("noise_reduction_luma"),
            noise_reduction_chroma=d.get("noise_reduction_chroma"),
            tools=d.get("tools"),
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
    lut_file: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "num_nodes": self.num_nodes,
            "nodes": [n.to_dict() for n in self.nodes],
            "version_name": self.version_name,
            "drx_file": self.drx_file,
            "lut_file": self.lut_file,
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
            lut_file=d.get("lut_file"),
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
