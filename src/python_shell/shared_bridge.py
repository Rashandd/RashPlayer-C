"""
RashPlayer-C: Shared Memory Bridge
Python interface to shared memory for C-Core communication
"""

import ctypes
import struct
import mmap
import posix_ipc
import numpy as np
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional


# Constants matching shared_bridge.h
SHM_NAME = "/rashplayer_shm"
MAX_FRAME_WIDTH = 1920
MAX_FRAME_HEIGHT = 1080
FRAME_CHANNELS = 4
FRAME_BUFFER_SIZE = MAX_FRAME_WIDTH * MAX_FRAME_HEIGHT * FRAME_CHANNELS


class GameState(IntEnum):
    IDLE = 0
    DETECTING = 1
    ACTION_PENDING = 2
    EXECUTING = 3
    PAUSED = 4
    ERROR = 5


class ActionType(IntEnum):
    NONE = 0
    TAP = 1
    SWIPE = 2
    LONG_PRESS = 3
    DRAG = 4
    WAIT = 5


@dataclass
class VisionResult:
    trigger_id: int
    found: bool
    confidence: float
    location: tuple[int, int]
    bounding_box: tuple[int, int, int, int]
    timestamp_ns: int


@dataclass
class ActionCommand:
    action_type: ActionType
    start: tuple[int, int]
    end: tuple[int, int]
    duration_ms: int
    hold_ms: int
    randomize: float


class SharedMemoryBridge:
    """Python interface to C-Core shared memory"""
    
    # Header structure layout (must match SharedMemoryHeader in C)
    HEADER_FORMAT = """
        I   magic
        I   version
        Q   frame_number
        q   frame_timestamp_ns
        I   frame_ready
        I   result_ready
        I   current_state
        I   _padding1
        i   frame_width
        i   frame_height
        i   frame_stride
        i   _padding2
        q   vision_latency_ns
        q   brain_latency_ns
        q   total_latency_ns
        q   _padding3
        I   num_results
        I   _padding4
    """
    
    HEADER_SIZE = 4096  # Aligned header size
    VISION_RESULT_SIZE = 48  # Per result
    ACTION_COMMAND_SIZE = 32
    
    def __init__(self):
        self._shm: Optional[posix_ipc.SharedMemory] = None
        self._mmap: Optional[mmap.mmap] = None
        self._frame_offset = self.HEADER_SIZE
        
    def create(self, width: int = MAX_FRAME_WIDTH, height: int = MAX_FRAME_HEIGHT) -> bool:
        """Create shared memory segment"""
        try:
            total_size = self.HEADER_SIZE + width * height * FRAME_CHANNELS
            
            # Remove existing if present
            try:
                posix_ipc.unlink_shared_memory(SHM_NAME)
            except posix_ipc.ExistentialError:
                pass
            
            self._shm = posix_ipc.SharedMemory(
                SHM_NAME,
                posix_ipc.O_CREAT | posix_ipc.O_RDWR,
                size=total_size
            )
            
            self._mmap = mmap.mmap(
                self._shm.fd,
                total_size,
                mmap.MAP_SHARED,
                mmap.PROT_READ | mmap.PROT_WRITE
            )
            
            # Initialize header
            self._write_header(width, height)
            return True
            
        except Exception as e:
            print(f"Failed to create shared memory: {e}")
            return False
    
    def attach(self) -> bool:
        """Attach to existing shared memory"""
        try:
            self._shm = posix_ipc.SharedMemory(SHM_NAME)
            
            self._mmap = mmap.mmap(
                self._shm.fd,
                0,  # Map entire segment
                mmap.MAP_SHARED,
                mmap.PROT_READ | mmap.PROT_WRITE
            )
            
            return self._verify_magic()
            
        except Exception as e:
            print(f"Failed to attach shared memory: {e}")
            return False
    
    def detach(self) -> None:
        """Detach from shared memory"""
        if self._mmap:
            self._mmap.close()
            self._mmap = None
        if self._shm:
            self._shm.close_fd()
            self._shm = None
    
    def destroy(self) -> None:
        """Destroy shared memory segment"""
        self.detach()
        try:
            posix_ipc.unlink_shared_memory(SHM_NAME)
        except posix_ipc.ExistentialError:
            pass
    
    def _write_header(self, width: int, height: int) -> None:
        """Initialize header with default values"""
        if not self._mmap:
            return
            
        self._mmap.seek(0)
        
        # Write header fields
        header = struct.pack(
            "<IIQqIIIIiiiiqqqqII",
            0x52415348,  # magic = "RASH"
            1,           # version
            0,           # frame_number
            0,           # frame_timestamp_ns
            0,           # frame_ready
            0,           # result_ready
            GameState.IDLE,  # current_state
            0,           # _padding1
            width,       # frame_width
            height,      # frame_height
            width * 4,   # frame_stride
            0,           # _padding2
            0,           # vision_latency_ns
            0,           # brain_latency_ns
            0,           # total_latency_ns
            0,           # _padding3
            0,           # num_results
            0            # _padding4
        )
        
        self._mmap.write(header)
    
    def _verify_magic(self) -> bool:
        """Verify shared memory magic number"""
        if not self._mmap:
            return False
        self._mmap.seek(0)
        magic = struct.unpack("<I", self._mmap.read(4))[0]
        return magic == 0x52415348
    
    def write_frame(self, frame: np.ndarray) -> bool:
        """Write a frame to shared memory"""
        if not self._mmap:
            return False
        
        # Ensure RGBA format
        if frame.ndim == 3 and frame.shape[2] == 3:
            frame = np.dstack([frame, np.full(frame.shape[:2], 255, dtype=np.uint8)])
        
        # Resize if needed
        h, w = frame.shape[:2]
        if h != MAX_FRAME_HEIGHT or w != MAX_FRAME_WIDTH:
            from PIL import Image
            img = Image.fromarray(frame)
            img = img.resize((MAX_FRAME_WIDTH, MAX_FRAME_HEIGHT))
            frame = np.array(img)
        
        # Write frame data
        self._mmap.seek(self._frame_offset)
        self._mmap.write(frame.tobytes())
        
        # Update frame counter and set ready flag
        self._mmap.seek(8)  # frame_number offset
        frame_num = struct.unpack("<Q", self._mmap.read(8))[0]
        self._mmap.seek(8)
        self._mmap.write(struct.pack("<Q", frame_num + 1))
        
        # Set frame_ready = 1
        self._mmap.seek(24)
        self._mmap.write(struct.pack("<I", 1))
        
        return True
    
    def read_results(self) -> tuple[bool, list[VisionResult], Optional[ActionCommand]]:
        """Read vision results and pending action from C-Core"""
        if not self._mmap:
            return False, [], None
        
        # Check if result is ready
        self._mmap.seek(28)  # result_ready offset
        result_ready = struct.unpack("<I", self._mmap.read(4))[0]
        
        if not result_ready:
            return False, [], None
        
        # Read number of results
        self._mmap.seek(80)  # num_results offset
        num_results = struct.unpack("<I", self._mmap.read(4))[0]
        
        results = []
        result_offset = 88  # After header fields
        
        for i in range(min(num_results, 16)):
            self._mmap.seek(result_offset + i * self.VISION_RESULT_SIZE)
            data = self._mmap.read(self.VISION_RESULT_SIZE)
            
            trigger_id, found, confidence, loc_x, loc_y, bb_x, bb_y, bb_w, bb_h, ts = \
                struct.unpack("<I?fiiiiiiQ", data[:44])
            
            results.append(VisionResult(
                trigger_id=trigger_id,
                found=found,
                confidence=confidence,
                location=(loc_x, loc_y),
                bounding_box=(bb_x, bb_y, bb_w, bb_h),
                timestamp_ns=ts
            ))
        
        # Read pending action
        action_offset = 88 + 16 * self.VISION_RESULT_SIZE
        self._mmap.seek(action_offset)
        action_data = self._mmap.read(self.ACTION_COMMAND_SIZE)
        
        action_type, sx, sy, ex, ey, dur, hold, rand = \
            struct.unpack("<Iiiiiiif", action_data)
        
        action = None
        if action_type != ActionType.NONE:
            action = ActionCommand(
                action_type=ActionType(action_type),
                start=(sx, sy),
                end=(ex, ey),
                duration_ms=dur,
                hold_ms=hold,
                randomize=rand
            )
        
        # Clear result_ready flag
        self._mmap.seek(28)
        self._mmap.write(struct.pack("<I", 0))
        
        return True, results, action
    
    def get_latency(self) -> tuple[int, int, int]:
        """Get latency metrics in microseconds"""
        if not self._mmap:
            return 0, 0, 0
        
        self._mmap.seek(48)
        vision_ns, brain_ns, total_ns = struct.unpack("<qqq", self._mmap.read(24))
        
        return vision_ns // 1000, brain_ns // 1000, total_ns // 1000
    
    def get_state(self) -> GameState:
        """Get current game state"""
        if not self._mmap:
            return GameState.ERROR
        
        self._mmap.seek(32)
        state = struct.unpack("<I", self._mmap.read(4))[0]
        return GameState(state)
