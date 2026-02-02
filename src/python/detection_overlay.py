"""
RashPlayer-C: Detection Overlay
Renders detection boxes, state labels, and decision info on preview
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from enum import Enum


class DetectionStatus(Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    SEARCHING = "searching"


@dataclass
class DetectionResult:
    """Single detection result for overlay"""
    name: str
    status: DetectionStatus
    region: Tuple[int, int, int, int]  # x, y, width, height
    confidence: float = 0.0
    match_location: Optional[Tuple[int, int]] = None  # x, y of match center


@dataclass  
class TapTarget:
    """Tap target for overlay"""
    x: int
    y: int
    label: str = ""


@dataclass
class OverlayState:
    """Current overlay state to render"""
    fsm_state: str = "IDLE"
    decision_text: str = ""
    detections: List[DetectionResult] = field(default_factory=list)
    tap_target: Optional[TapTarget] = None
    fps: float = 0.0
    latency_ms: float = 0.0


class DetectionOverlay:
    """Manages detection overlay rendering data"""
    
    def __init__(self):
        self._state = OverlayState()
    
    def set_fsm_state(self, state: str) -> None:
        """Update current FSM state"""
        self._state.fsm_state = state.upper()
    
    def set_decision(self, text: str) -> None:
        """Update decision text"""
        self._state.decision_text = text
    
    def clear_detections(self) -> None:
        """Clear all detections"""
        self._state.detections.clear()
    
    def add_detection(self, 
                      name: str, 
                      found: bool, 
                      region: Tuple[int, int, int, int],
                      confidence: float = 0.0,
                      location: Optional[Tuple[int, int]] = None) -> None:
        """Add a detection result"""
        status = DetectionStatus.FOUND if found else DetectionStatus.NOT_FOUND
        self._state.detections.append(DetectionResult(
            name=name,
            status=status,
            region=region,
            confidence=confidence,
            match_location=location
        ))
    
    def set_tap_target(self, x: int, y: int, label: str = "TAP") -> None:
        """Set current tap target"""
        self._state.tap_target = TapTarget(x=x, y=y, label=label)
    
    def clear_tap_target(self) -> None:
        """Clear tap target"""
        self._state.tap_target = None
    
    def set_metrics(self, fps: float, latency_ms: float) -> None:
        """Update performance metrics"""
        self._state.fps = fps
        self._state.latency_ms = latency_ms
    
    def get_state(self) -> OverlayState:
        """Get current overlay state for rendering"""
        return self._state
    
    def get_opengl_commands(self, widget_width: int, widget_height: int, 
                            frame_width: int, frame_height: int) -> List[dict]:
        """Generate OpenGL rendering commands for overlay"""
        commands = []
        
        # Scale factors
        scale_x = widget_width / frame_width if frame_width > 0 else 1.0
        scale_y = widget_height / frame_height if frame_height > 0 else 1.0
        
        # Detection boxes
        for det in self._state.detections:
            x, y, w, h = det.region
            color = (0.0, 1.0, 0.0, 0.8) if det.status == DetectionStatus.FOUND else (1.0, 0.0, 0.0, 0.5)
            
            commands.append({
                'type': 'rect',
                'x': int(x * scale_x),
                'y': int(y * scale_y),
                'w': int(w * scale_x),
                'h': int(h * scale_y),
                'color': color,
                'label': f"{det.name} ({det.confidence:.0%})" if det.confidence > 0 else det.name
            })
        
        # Tap target crosshair
        if self._state.tap_target:
            tx = int(self._state.tap_target.x * scale_x)
            ty = int(self._state.tap_target.y * scale_y)
            commands.append({
                'type': 'crosshair',
                'x': tx,
                'y': ty,
                'size': 30,
                'color': (0.0, 0.5, 1.0, 1.0),
                'label': self._state.tap_target.label
            })
        
        # State label (top-left)
        commands.append({
            'type': 'text',
            'x': 10,
            'y': 30,
            'text': f"State: {self._state.fsm_state}",
            'color': (1.0, 1.0, 0.0, 1.0)
        })
        
        # Decision text (top-left, below state)
        if self._state.decision_text:
            commands.append({
                'type': 'text',
                'x': 10,
                'y': 60,
                'text': self._state.decision_text,
                'color': (0.0, 1.0, 0.5, 1.0)
            })
        
        # FPS and latency (top-right)
        commands.append({
            'type': 'text',
            'x': widget_width - 120,
            'y': 30,
            'text': f"FPS: {self._state.fps:.1f}",
            'color': (1.0, 1.0, 1.0, 1.0)
        })
        
        commands.append({
            'type': 'text',
            'x': widget_width - 120,
            'y': 60,
            'text': f"Latency: {self._state.latency_ms:.0f}ms",
            'color': (1.0, 1.0, 1.0, 1.0)
        })
        
        return commands
