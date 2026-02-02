"""
RashPlayer-C: FSM Engine
Finite State Machine for game workflow execution
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Tuple
from enum import Enum
import numpy as np
import cv2

from game_loader import GameConfig, GameState, Region, TapTarget


class ActionType(Enum):
    NONE = "none"
    TAP = "tap"
    SWIPE = "swipe"
    WAIT = "wait"


@dataclass
class DetectionResult:
    """Result of asset detection"""
    name: str
    found: bool
    confidence: float = 0.0
    location: Optional[Tuple[int, int]] = None  # center x, y
    region: Optional[Tuple[int, int, int, int]] = None  # x, y, w, h


@dataclass
class FSMAction:
    """Action to execute"""
    action_type: ActionType
    target_x: int = 0
    target_y: int = 0
    end_x: int = 0
    end_y: int = 0
    duration_ms: int = 100


@dataclass
class FSMState:
    """Current FSM state info for overlay"""
    state_name: str
    detections: List[DetectionResult] = field(default_factory=list)
    pending_action: Optional[FSMAction] = None
    decision_text: str = ""


class FSMEngine:
    """Finite State Machine engine for game automation"""
    
    def __init__(self, game_config: GameConfig):
        self.config = game_config
        self.current_state = game_config.initial_state
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # Callbacks
        self._action_callback: Optional[Callable[[FSMAction], None]] = None
        self._state_callback: Optional[Callable[[FSMState], None]] = None
        
        # Detection
        self._latest_frame: Optional[np.ndarray] = None
        self._templates: Dict[str, np.ndarray] = {}
        self._state_enter_time = time.time()
        
        # Load templates
        self._load_templates()
    
    def _load_templates(self):
        """Load asset templates for matching"""
        for asset_name in self.config.assets:
            asset_path = self.config.path / "assets" / asset_name
            if asset_path.exists():
                try:
                    template = cv2.imread(str(asset_path))
                    if template is not None:
                        name = asset_path.stem  # filename without extension
                        self._templates[name] = template
                        print(f"Loaded template: {name}")
                except Exception as e:
                    print(f"Failed to load template {asset_name}: {e}")
    
    def set_action_callback(self, callback: Callable[[FSMAction], None]):
        """Set callback for executing actions"""
        self._action_callback = callback
    
    def set_state_callback(self, callback: Callable[[FSMState], None]):
        """Set callback for state updates (overlay)"""
        self._state_callback = callback
    
    def update_frame(self, frame: np.ndarray):
        """Update current frame for detection"""
        self._latest_frame = frame
    
    def start(self):
        """Start FSM engine"""
        if self._running:
            return
        
        self._running = True
        self._state_enter_time = time.time()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print(f"FSM started in state: {self.current_state}")
    
    def stop(self):
        """Stop FSM engine"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        print("FSM stopped")
    
    def _run_loop(self):
        """Main FSM loop"""
        while self._running:
            try:
                self._process_state()
                time.sleep(0.016)  # ~60 Hz
            except Exception as e:
                print(f"FSM error: {e}")
                time.sleep(0.1)
    
    def _process_state(self):
        """Process current state"""
        if self.current_state not in self.config.states:
            print(f"Unknown state: {self.current_state}")
            return
        
        state = self.config.states[self.current_state]
        detections = []
        
        # Run detections
        for target in state.detect:
            result = self._detect(target)
            detections.append(result)
        
        # Check for found targets
        found_targets = [d for d in detections if d.found]
        
        # Build FSM state for overlay
        fsm_state = FSMState(
            state_name=self.current_state.upper(),
            detections=detections
        )
        
        # Decision logic
        if found_targets:
            target = found_targets[0]
            fsm_state.decision_text = f"Found: {target.name} → {state.action}"
            
            # Create action
            if state.action == "TAP":
                action = self._create_tap_action(target, state)
                fsm_state.pending_action = action
                
                # Execute action
                if self._action_callback:
                    self._action_callback(action)
                
                # Transition to next state
                if state.next_state:
                    self._transition(state.next_state)
        else:
            fsm_state.decision_text = f"Searching: {', '.join(state.detect)}"
            
            # Check timeout
            if state.timeout_ms > 0:
                elapsed = (time.time() - self._state_enter_time) * 1000
                if elapsed > state.timeout_ms:
                    fsm_state.decision_text = f"Timeout → {state.on_timeout}"
                    if state.on_timeout:
                        self._transition(state.on_timeout)
        
        # Notify overlay
        if self._state_callback:
            self._state_callback(fsm_state)
    
    def _detect(self, target_name: str) -> DetectionResult:
        """Detect a target in current frame"""
        if self._latest_frame is None:
            return DetectionResult(name=target_name, found=False)
        
        # Check if we have a template
        if target_name in self._templates:
            return self._template_match(target_name)
        
        # Check if we have a color definition
        if target_name in self.config.colors:
            return self._color_detect(target_name)
        
        # Check if it's a region-based detection
        if target_name in self.config.regions:
            # For now, just return the region center as found
            region = self.config.regions[target_name]
            return DetectionResult(
                name=target_name,
                found=True,
                confidence=1.0,
                location=(region.x + region.width // 2, region.y + region.height // 2),
                region=region.as_tuple()
            )
        
        return DetectionResult(name=target_name, found=False)
    
    def _template_match(self, name: str) -> DetectionResult:
        """Template matching detection"""
        template = self._templates[name]
        frame = self._latest_frame
        
        # Convert to BGR if needed
        if len(frame.shape) == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
        
        # Get search region if defined
        region = self.config.regions.get(f"{name}_search")
        if region:
            x, y, w, h = region.as_tuple()
            search_area = frame[y:y+h, x:x+w]
            offset = (x, y)
        else:
            search_area = frame
            offset = (0, 0)
        
        # Template match
        try:
            result = cv2.matchTemplate(search_area, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            
            threshold = 0.7  # Configurable
            if max_val > threshold:
                th, tw = template.shape[:2]
                cx = offset[0] + max_loc[0] + tw // 2
                cy = offset[1] + max_loc[1] + th // 2
                
                return DetectionResult(
                    name=name,
                    found=True,
                    confidence=max_val,
                    location=(cx, cy),
                    region=(offset[0] + max_loc[0], offset[1] + max_loc[1], tw, th)
                )
        except Exception as e:
            print(f"Template match error: {e}")
        
        return DetectionResult(name=name, found=False)
    
    def _color_detect(self, name: str) -> DetectionResult:
        """Color-based detection"""
        color_range = self.config.colors[name]
        frame = self._latest_frame
        
        # Convert to HSV
        if len(frame.shape) == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        
        # Create mask
        lower = np.array(color_range.hsv_low)
        upper = np.array(color_range.hsv_high)
        mask = cv2.inRange(hsv, lower, upper)
        
        # Find contours
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if contours:
            # Get largest contour
            largest = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest)
            
            if area > 100:  # Minimum area threshold
                x, y, w, h = cv2.boundingRect(largest)
                return DetectionResult(
                    name=name,
                    found=True,
                    confidence=min(area / 10000, 1.0),
                    location=(x + w // 2, y + h // 2),
                    region=(x, y, w, h)
                )
        
        return DetectionResult(name=name, found=False)
    
    def _create_tap_action(self, detection: DetectionResult, state: GameState) -> FSMAction:
        """Create tap action from detection"""
        # Use detection location or configured target
        if detection.location:
            x, y = detection.location
        elif state.next_state in self.config.targets:
            target = self.config.targets[state.next_state]
            x, y = target.x, target.y
        else:
            # Use center of detected region
            if detection.region:
                rx, ry, rw, rh = detection.region
                x, y = rx + rw // 2, ry + rh // 2
            else:
                x, y = self.config.screen_width // 2, self.config.screen_height // 2
        
        return FSMAction(
            action_type=ActionType.TAP,
            target_x=x,
            target_y=y
        )
    
    def _transition(self, new_state: str):
        """Transition to new state"""
        print(f"FSM: {self.current_state} → {new_state}")
        self.current_state = new_state
        self._state_enter_time = time.time()
    
    @property
    def is_running(self) -> bool:
        return self._running
