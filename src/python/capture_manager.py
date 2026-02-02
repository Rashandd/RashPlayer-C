"""
RashPlayer-C: Capture Manager
Single capture source shared between preview and processing
"""

import threading
import time
from typing import Optional, Callable, List
import numpy as np

from device_manager import DeviceInterface


class CaptureManager:
    """Manages a single capture source shared by multiple consumers"""
    
    def __init__(self, device: DeviceInterface):
        self.device = device
        self._running = False
        self._callbacks: List[Callable[[np.ndarray], None]] = []
        self._lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
    
    def add_callback(self, callback: Callable[[np.ndarray], None]) -> None:
        """Add a frame callback"""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)
    
    def remove_callback(self, callback: Callable[[np.ndarray], None]) -> None:
        """Remove a frame callback"""
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)
    
    def start(self) -> bool:
        """Start capture if not already running"""
        if self._running:
            return True
        
        self._running = True
        
        def on_frame(frame: np.ndarray):
            self._latest_frame = frame
            with self._lock:
                for callback in self._callbacks:
                    try:
                        callback(frame)
                    except Exception as e:
                        print(f"Callback error: {e}")
        
        return self.device.start_capture(on_frame)
    
    def stop(self) -> None:
        """Stop capture"""
        if self._running:
            self._running = False
            self.device.stop_capture()
    
    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Get the most recent frame"""
        return self._latest_frame
    
    @property
    def is_running(self) -> bool:
        return self._running
