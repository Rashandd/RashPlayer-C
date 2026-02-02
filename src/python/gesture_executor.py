"""
RashPlayer-C: Gesture Executor
Human-like gesture generation with Bezier curves and randomization
"""

import random
import time
import math
from dataclasses import dataclass
from typing import Optional
from device_manager import DeviceInterface


@dataclass
class GestureConfig:
    """Configuration for gesture randomization"""
    click_offset_min: int = 3
    click_offset_max: int = 7
    timing_jitter_min_ms: int = 15
    timing_jitter_max_ms: int = 50
    swipe_bezier_variance: float = 0.15
    tap_duration_min_ms: int = 40
    tap_duration_max_ms: int = 80


class BezierCurve:
    """Cubic Bezier curve for smooth gesture paths"""
    
    def __init__(self, p0: tuple[int, int], p1: tuple[int, int],
                 p2: tuple[int, int], p3: tuple[int, int]):
        self.p0 = p0  # Start point
        self.p1 = p1  # Control point 1
        self.p2 = p2  # Control point 2
        self.p3 = p3  # End point
    
    def point_at(self, t: float) -> tuple[int, int]:
        """Get point on curve at parameter t (0-1)"""
        t = max(0.0, min(1.0, t))
        mt = 1 - t
        mt2 = mt * mt
        mt3 = mt2 * mt
        t2 = t * t
        t3 = t2 * t
        
        x = mt3 * self.p0[0] + 3 * mt2 * t * self.p1[0] + \
            3 * mt * t2 * self.p2[0] + t3 * self.p3[0]
        y = mt3 * self.p0[1] + 3 * mt2 * t * self.p1[1] + \
            3 * mt * t2 * self.p2[1] + t3 * self.p3[1]
        
        return (int(x), int(y))
    
    def generate_points(self, num_points: int = 20) -> list[tuple[int, int]]:
        """Generate points along the curve"""
        return [self.point_at(i / (num_points - 1)) for i in range(num_points)]
    
    @classmethod
    def from_endpoints(cls, start: tuple[int, int], end: tuple[int, int],
                       variance: float = 0.15) -> "BezierCurve":
        """Create a natural-looking curve between two points"""
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dist = math.sqrt(dx*dx + dy*dy)
        
        # Generate control points with randomized perpendicular offset
        perp_x = -dy / dist if dist > 0 else 0
        perp_y = dx / dist if dist > 0 else 0
        
        offset1 = random.gauss(0, dist * variance)
        offset2 = random.gauss(0, dist * variance)
        
        p1 = (
            int(start[0] + dx * 0.33 + perp_x * offset1),
            int(start[1] + dy * 0.33 + perp_y * offset1)
        )
        p2 = (
            int(start[0] + dx * 0.66 + perp_x * offset2),
            int(start[1] + dy * 0.66 + perp_y * offset2)
        )
        
        return cls(start, p1, p2, end)


class GestureExecutor:
    """Executes human-like gestures on a device"""
    
    def __init__(self, device: DeviceInterface, config: Optional[GestureConfig] = None):
        self.device = device
        self.config = config or GestureConfig()
        self._last_action_time = 0.0
    
    def _add_jitter(self) -> None:
        """Add random timing delay between actions"""
        jitter_ms = random.randint(
            self.config.timing_jitter_min_ms,
            self.config.timing_jitter_max_ms
        )
        elapsed = (time.time() - self._last_action_time) * 1000
        if elapsed < jitter_ms:
            time.sleep((jitter_ms - elapsed) / 1000)
        self._last_action_time = time.time()
    
    def _randomize_point(self, x: int, y: int) -> tuple[int, int]:
        """Add Gaussian offset to a point"""
        offset_range = random.randint(
            self.config.click_offset_min,
            self.config.click_offset_max
        )
        offset_x = int(random.gauss(0, offset_range))
        offset_y = int(random.gauss(0, offset_range))
        return (x + offset_x, y + offset_y)
    
    def tap(self, x: int, y: int, randomize: bool = True) -> bool:
        """Execute a tap with optional randomization"""
        self._add_jitter()
        
        if randomize:
            x, y = self._randomize_point(x, y)
        
        return self.device.send_tap(x, y)
    
    def long_press(self, x: int, y: int, duration_ms: int = 500,
                   randomize: bool = True) -> bool:
        """Execute a long press"""
        self._add_jitter()
        
        if randomize:
            x, y = self._randomize_point(x, y)
            duration_ms += random.randint(-50, 50)
        
        # Long press is a swipe with same start/end
        return self.device.send_swipe(x, y, x, y, duration_ms)
    
    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 300, randomize: bool = True) -> bool:
        """Execute a swipe using Bezier interpolation"""
        self._add_jitter()
        
        if randomize:
            x1, y1 = self._randomize_point(x1, y1)
            x2, y2 = self._randomize_point(x2, y2)
            duration_ms += random.randint(-30, 30)
        
        # For ADB, we use simple swipe - Bezier is for visualization
        return self.device.send_swipe(x1, y1, x2, y2, duration_ms)
    
    def swipe_bezier(self, x1: int, y1: int, x2: int, y2: int,
                     duration_ms: int = 300, steps: int = 10) -> bool:
        """Execute a swipe following a Bezier curve path"""
        self._add_jitter()
        
        curve = BezierCurve.from_endpoints(
            (x1, y1), (x2, y2),
            self.config.swipe_bezier_variance
        )
        
        points = curve.generate_points(steps)
        step_delay = duration_ms / (steps - 1) / 1000
        
        # Execute as series of small swipes
        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]
            step_duration = int(step_delay * 1000)
            self.device.send_swipe(p1[0], p1[1], p2[0], p2[1], step_duration)
            time.sleep(step_delay * 0.5)
        
        return True
    
    def drag(self, x1: int, y1: int, x2: int, y2: int,
             duration_ms: int = 500) -> bool:
        """Execute a drag (slower swipe with hold)"""
        return self.swipe_bezier(x1, y1, x2, y2, duration_ms, steps=15)
    
    def double_tap(self, x: int, y: int) -> bool:
        """Execute a double tap"""
        self.tap(x, y)
        time.sleep(random.uniform(0.05, 0.1))
        return self.tap(x, y)
    
    def get_bezier_preview(self, x1: int, y1: int, x2: int, y2: int,
                           num_points: int = 50) -> list[tuple[int, int]]:
        """Get Bezier curve points for UI preview"""
        curve = BezierCurve.from_endpoints(
            (x1, y1), (x2, y2),
            self.config.swipe_bezier_variance
        )
        return curve.generate_points(num_points)
