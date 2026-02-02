"""
RashPlayer-C: Device Manager
Abstracts physical and virtual Android device connectivity via ADB/Scrcpy
"""

import subprocess
import threading
import time
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable, TYPE_CHECKING
import numpy as np

if TYPE_CHECKING:
    from scrcpy_stream import ScrcpyVideoStream


class DeviceType(Enum):
    PHYSICAL = "physical"
    EMULATOR = "emulator"
    REDROID = "redroid"


@dataclass
class DeviceInfo:
    serial: str
    name: str
    device_type: DeviceType
    resolution: tuple[int, int]
    connected: bool = False


class DeviceInterface(ABC):
    """Abstract base class for device connectivity"""
    
    @abstractmethod
    def connect(self) -> bool:
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        pass
    
    @abstractmethod
    def start_capture(self, callback: Callable[[np.ndarray], None]) -> bool:
        pass
    
    @abstractmethod
    def stop_capture(self) -> None:
        pass
    
    @abstractmethod
    def send_tap(self, x: int, y: int) -> bool:
        pass
    
    @abstractmethod
    def send_swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> bool:
        pass
    
    @abstractmethod
    def get_resolution(self) -> tuple[int, int]:
        pass


class PhysicalAndroid(DeviceInterface):
    """Physical Android device via USB/ADB + scrcpy"""
    
    def __init__(self, serial: str):
        self.serial = serial
        self._stream: Optional['ScrcpyVideoStream'] = None
        self._resolution = (1920, 1080)
        
    def connect(self) -> bool:
        try:
            result = subprocess.run(
                ["adb", "-s", self.serial, "get-state"],
                capture_output=True, text=True, timeout=5
            )
            if "device" in result.stdout:
                self._update_resolution()
                return True
        except Exception as e:
            print(f"Connection failed: {e}")
        return False
    
    def disconnect(self) -> None:
        self.stop_capture()
        
    def _update_resolution(self) -> None:
        try:
            result = subprocess.run(
                ["adb", "-s", self.serial, "shell", "wm", "size"],
                capture_output=True, text=True, timeout=5
            )
            if "Physical size:" in result.stdout:
                size_str = result.stdout.split(":")[-1].strip()
                w, h = map(int, size_str.split("x"))
                self._resolution = (w, h)
        except Exception:
            pass
    
    def start_capture(self, callback: Callable[[np.ndarray], None]) -> bool:
        if self._stream:
            return False
        
        from scrcpy_stream import ScrcpyVideoStream
        
        try:
            self._stream = ScrcpyVideoStream(self.serial)
            return self._stream.start(callback)
        except Exception as e:
            print(f"Failed to start scrcpy stream: {e}")
            self._stream = None
            return False
    

    
    def stop_capture(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream = None
    
    def send_tap(self, x: int, y: int) -> bool:
        try:
            subprocess.run(
                ["adb", "-s", self.serial, "shell", "input", "tap", str(x), str(y)],
                timeout=1
            )
            return True
        except Exception:
            return False
    
    def send_swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> bool:
        try:
            subprocess.run(
                ["adb", "-s", self.serial, "shell", "input", "swipe",
                 str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
                timeout=duration_ms/1000 + 2
            )
            return True
        except Exception:
            return False
    
    def get_resolution(self) -> tuple[int, int]:
        return self._resolution


class VirtualAndroid(DeviceInterface):
    """Virtual Android (Redroid/Emulator) via network ADB"""
    
    def __init__(self, host: str = "localhost", port: int = 5555):
        self.host = host
        self.port = port
        self.serial = f"{host}:{port}"
        self._resolution = (1920, 1080)
        self._running = False
        self._capture_thread: Optional[threading.Thread] = None
        self._frame_callback: Optional[Callable] = None
        
    def connect(self) -> bool:
        try:
            # Connect to network ADB
            subprocess.run(
                ["adb", "connect", self.serial],
                capture_output=True, timeout=10
            )
            result = subprocess.run(
                ["adb", "-s", self.serial, "get-state"],
                capture_output=True, text=True, timeout=5
            )
            return "device" in result.stdout
        except Exception:
            return False
    
    def disconnect(self) -> None:
        self.stop_capture()
        subprocess.run(["adb", "disconnect", self.serial], capture_output=True)
    
    def start_capture(self, callback: Callable[[np.ndarray], None]) -> bool:
        self._frame_callback = callback
        self._running = True
        self._capture_thread = threading.Thread(target=self._capture_loop)
        self._capture_thread.daemon = True
        self._capture_thread.start()
        return True
    
    def _capture_loop(self) -> None:
        """Capture frames using optimized adb screencap with minimal delay"""
        while self._running:
            try:
                # Use raw screencap format for speed
                result = subprocess.run(
                    ["adb", "-s", self.serial, "exec-out", "screencap"],
                    capture_output=True, 
                    timeout=0.1
                )
                
                if result.returncode == 0 and self._frame_callback and len(result.stdout) > 0:
                    try:
                        # Parse raw screencap format
                        if len(result.stdout) > 12:
                            width = struct.unpack('<I', result.stdout[0:4])[0]
                            height = struct.unpack('<I', result.stdout[4:8])[0]
                            raw_data = result.stdout[12:]
                            expected_size = width * height * 4
                            
                            if len(raw_data) >= expected_size:
                                frame = np.frombuffer(raw_data[:expected_size], dtype=np.uint8)
                                frame = frame.reshape((height, width, 4))
                                self._frame_callback(frame)
                    except Exception:
                        # Fallback to PNG
                        import io
                        from PIL import Image
                        result_png = subprocess.run(
                            ["adb", "-s", self.serial, "exec-out", "screencap", "-p"],
                            capture_output=True, timeout=0.1
                        )
                        if result_png.returncode == 0:
                            img = Image.open(io.BytesIO(result_png.stdout))
                            frame = np.array(img.convert("RGBA"))
                            self._frame_callback(frame)
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
            
            time.sleep(0.001)  # Minimal sleep for lowest latency
    
    def stop_capture(self) -> None:
        self._running = False
        if self._capture_thread:
            self._capture_thread.join(timeout=2)
    
    def send_tap(self, x: int, y: int) -> bool:
        try:
            subprocess.run(
                ["adb", "-s", self.serial, "shell", "input", "tap", str(x), str(y)],
                timeout=1
            )
            return True
        except Exception:
            return False
    
    def send_swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> bool:
        try:
            subprocess.run(
                ["adb", "-s", self.serial, "shell", "input", "swipe",
                 str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
                timeout=duration_ms/1000 + 2
            )
            return True
        except Exception:
            return False
    
    def get_resolution(self) -> tuple[int, int]:
        return self._resolution


class DeviceManager:
    """Manages device discovery and selection"""
    
    def __init__(self):
        self.devices: list[DeviceInfo] = []
        self.active_device: Optional[DeviceInterface] = None
        
    def scan_devices(self) -> list[DeviceInfo]:
        """Scan for available Android devices"""
        self.devices.clear()
        
        try:
            result = subprocess.run(
                ["adb", "devices", "-l"],
                capture_output=True, text=True, timeout=10
            )
            
            for line in result.stdout.strip().split("\n")[1:]:
                if not line.strip():
                    continue
                    
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    serial = parts[0]
                    name = serial
                    
                    # Extract model name
                    for part in parts[2:]:
                        if part.startswith("model:"):
                            name = part.split(":")[1]
                            break
                    
                    # Determine device type
                    if ":" in serial:
                        dtype = DeviceType.EMULATOR
                    elif "emulator" in serial.lower():
                        dtype = DeviceType.EMULATOR
                    else:
                        dtype = DeviceType.PHYSICAL
                    
                    self.devices.append(DeviceInfo(
                        serial=serial,
                        name=name,
                        device_type=dtype,
                        resolution=(1920, 1080),
                        connected=True
                    ))
                    
        except Exception as e:
            print(f"Device scan failed: {e}")
        
        return self.devices
    
    def connect_device(self, serial: str) -> Optional[DeviceInterface]:
        """Connect to a specific device"""
        device_info = next((d for d in self.devices if d.serial == serial), None)
        
        if not device_info:
            return None
        
        if device_info.device_type == DeviceType.PHYSICAL:
            device = PhysicalAndroid(serial)
        else:
            host, port = serial.split(":") if ":" in serial else (serial, 5555)
            device = VirtualAndroid(host, int(port))
        
        if device.connect():
            self.active_device = device
            return device
        
        return None
    
    def get_active_device(self) -> Optional[DeviceInterface]:
        return self.active_device
