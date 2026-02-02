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

from game_loader import GameConfig, GameState


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
        
        # Build FSM state for overlay
        fsm_state = FSMState(
            state_name=self.current_state.upper(),
            detections=detections
        )
        
        # Check if this state has workflow logic
        if state.logic:
            # Extract variables from detections
            variables = self._extract_variables(detections)
            
            # Evaluate logic rules (sorted by priority)
            for rule in state.logic:
                if self._eval_condition(rule.condition, variables):
                    fsm_state.decision_text = f"{rule.condition} → {rule.action}"
                    
                    if rule.action == "TAP":
                        # Create tap action
                        target_name = rule.target if rule.target else "tap_zone"
                        action = self._create_tap_action_from_target(target_name)
                        fsm_state.pending_action = action
                        
                        # Execute action
                        if self._action_callback:
                            self._action_callback(action)
                    elif rule.action == "WAIT":
                        fsm_state.decision_text = f"Waiting: {rule.condition}"
                        # No action, just wait for next loop iteration
                    
                    # Use first matching rule (highest priority)
                    break
            else: # No rule matched, check for timeout if no logic rule handled it
                if state.timeout_ms > 0:
                    elapsed = (time.time() - self._state_enter_time) * 1000
                    if elapsed > state.timeout_ms:
                        fsm_state.decision_text = f"Timeout → {state.on_timeout}"
                        if state.on_timeout:
                            self._transition(state.on_timeout)
        else:
            # Original simple state logic
            found_targets = [d for d in detections if d.found]
            
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
    
    def _extract_variables(self, detections: List[DetectionResult]) -> Dict[str, float]:
        """Extract variables from detection results for logic evaluation"""
        
        # If game has custom functions with extract_variables, use that
        if self.config.game_functions and hasattr(self.config.game_functions, 'extract_variables'):
            if self._latest_frame is not None:
                try:
                    return self.config.game_functions.extract_variables(self._latest_frame)
                except Exception as e:
                    print(f"Game function extract_variables error: {e}")
        
        # Default extraction from detections
        variables = {}
        
        pipe_top_y = None
        pipe_bottom_y = None
        
        for det in detections:
            if not det.found:
                continue
            
            # Extract bird position
            if det.name == "bird" and det.location:
                variables["bird_y"] = det.location[1]
                variables["bird_x"] = det.location[0]
            
            # Extract pipe positions
            elif det.name == "pipe_top" and det.region:
                x, y, w, h = det.region
                pipe_top_y = y + h  # Bottom edge of top pipe
                variables["pipe_top_y"] = pipe_top_y
            
            elif det.name == "pipe_bottom" and det.region:
                x, y, w, h = det.region
                pipe_bottom_y = y  # Top edge of bottom pipe
                variables["pipe_bottom_y"] = pipe_bottom_y
        
        # Calculate gap center if both pipes detected
        if pipe_top_y is not None and pipe_bottom_y is not None:
            variables["gap_center_y"] = (pipe_top_y + pipe_bottom_y) / 2
            variables["gap_height"] = pipe_bottom_y - pipe_top_y
        
        return variables
    
    def _eval_condition(self, condition: str, variables: Dict[str, float]) -> bool:
        """Evaluate a condition string with variables"""
        # Handle special case
        if condition.strip() == "true":
            return True
        
        try:
            # Replace variables in condition
            expr = condition
            for var_name, var_value in variables.items():
                expr = expr.replace(var_name, str(var_value))
            
            # Evaluate the expression safely
            # Only allow basic math and comparisons
            allowed_names = {"__builtins__": {}}
            result = eval(expr, allowed_names)
            return bool(result)
        except Exception as e:
            print(f"Condition eval error: {condition} -> {e}")
            return False
    
    def _create_tap_action_from_target(self, target_name: str) -> FSMAction:
        """Create tap action from a named target in config"""
        if target_name in self.config.targets:
            target = self.config.targets[target_name]
            return FSMAction(
                action_type=ActionType.TAP,
                target_x=target.x,
                target_y=target.y
            )
        else:
            print(f"Warning: Tap target '{target_name}' not found in config. Tapping center.")
            return FSMAction(
                action_type=ActionType.TAP,
                target_x=self.config.screen_width // 2,
                target_y=self.config.screen_height // 2
            )
    
    def _detect(self, target_name: str) -> DetectionResult:
        """Detect a target in current frame"""
        if self._latest_frame is None:
            print(f"  [DETECT] {target_name}: No frame available")
            return DetectionResult(name=target_name, found=False)
        
        # Check if we have a template
        if target_name in self._templates:
            print(f"  [DETECT] {target_name}: Using template matching")
            return self._template_match(target_name)
        
        # Check if we have a color definition
        if target_name in self.config.colors:
            print(f"  [DETECT] {target_name}: Using color detection")
            return self._color_detect(target_name)
        
        # Check if it's a region-based detection
        if target_name in self.config.regions:
            # For now, just return the region center as found
            region = self.config.regions[target_name]
            print(f"  [DETECT] {target_name}: Region-based (always found)")
            return DetectionResult(
                name=target_name,
                found=True,
                confidence=1.0,
                location=(region.x + region.width // 2, region.y + region.height // 2),
                region=region.as_tuple()
            )
        
        print(f"  [DETECT] {target_name}: No detection method found (not in templates, colors, or regions)")
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
            print(f"    Searching in region: {name}_search ({x}, {y}, {w}, {h})")
        else:
            search_area = frame
            offset = (0, 0)
            print("    Searching in full frame")
        
        # Template match
        try:
            result = cv2.matchTemplate(search_area, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            
            threshold = 0.7  # Configurable
            print(f"    Template match score: {max_val:.3f} (threshold: {threshold})")
            
            if max_val > threshold:
                th, tw = template.shape[:2]
                cx = offset[0] + max_loc[0] + tw // 2
                cy = offset[1] + max_loc[1] + th // 2
                
                print(f"    ✓ FOUND at ({cx}, {cy})")
                return DetectionResult(
                    name=name,
                    found=True,
                    confidence=max_val,
                    location=(cx, cy),
                    region=(offset[0] + max_loc[0], offset[1] + max_loc[1], tw, th)
                )
            else:
                print("    ✗ NOT FOUND (score too low)")
        except Exception as e:
            print(f"    ✗ Template match error: {e}")
        
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
        # Priority: state.target > detection.location > region center > screen center
        if state.target and state.target in self.config.targets:
            # Use explicitly configured target
            target = self.config.targets[state.target]
            x, y = target.x, target.y
            print(f"    Using target: {state.target} ({x}, {y})")
        elif detection.location:
            x, y = detection.location
            print(f"    Using detection location: ({x}, {y})")
        elif detection.region:
            # Use center of detected region
            rx, ry, rw, rh = detection.region
            x, y = rx + rw // 2, ry + rh // 2
            print(f"    Using region center: ({x}, {y})")
        else:
            x, y = self.config.screen_width // 2, self.config.screen_height // 2
            print(f"    Using screen center: ({x}, {y})")
        
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
