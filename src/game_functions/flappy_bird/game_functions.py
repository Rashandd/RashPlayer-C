"""
Flappy Bird - High-performance C bindings
Python wrapper for C game functions using ctypes
"""

import ctypes
import numpy as np
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass


# ========== C Structure Definitions ==========

class BirdDetection(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("center_x", ctypes.c_int),
        ("center_y", ctypes.c_int),
    ]


class PipeDetection(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("center_x", ctypes.c_int),
        ("center_y", ctypes.c_int),
        ("is_top", ctypes.c_bool),
    ]


class GapInfo(ctypes.Structure):
    _fields_ = [
        ("gap_x", ctypes.c_int),
        ("gap_y", ctypes.c_int),
        ("pipe_x", ctypes.c_int),
    ]


class GameVariables(ctypes.Structure):
    _fields_ = [
        ("bird_x", ctypes.c_float),
        ("bird_y", ctypes.c_float),
        ("bird_found", ctypes.c_bool),
        ("pipe_count", ctypes.c_int),
        ("gap_center_x", ctypes.c_float),
        ("gap_center_y", ctypes.c_float),
        ("gap_found", ctypes.c_bool),
    ]


# ========== Library Loader ==========

def _load_library():
    """Load the compiled C library"""
    lib_path = Path(__file__).parent / "libgame_functions.so"
    
    if not lib_path.exists():
        # Try Windows DLL
        lib_path = Path(__file__).parent / "game_functions.dll"
    
    if not lib_path.exists():
        raise RuntimeError(
            f"Game functions library not found. "
            f"Please compile: cd {Path(__file__).parent} && make"
        )
    
    lib = ctypes.CDLL(str(lib_path))
    
    # Define function signatures
    
    # detect_bird_color
    lib.detect_bird_color.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),  # frame_data
        ctypes.c_int,  # width
        ctypes.c_int,  # height
        ctypes.c_int,  # channels
        ctypes.POINTER(ctypes.c_int),  # search_region
        ctypes.c_uint8 * 3,  # hsv_low
        ctypes.c_uint8 * 3,  # hsv_high
        ctypes.POINTER(BirdDetection),  # out_bird
    ]
    lib.detect_bird_color.restype = ctypes.c_bool
    
    # detect_pipes_color
    lib.detect_pipes_color.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_uint8 * 3,
        ctypes.c_uint8 * 3,
        ctypes.POINTER(PipeDetection),
        ctypes.c_int,
    ]
    lib.detect_pipes_color.restype = ctypes.c_int
    
    # find_leftmost_gap
    lib.find_leftmost_gap.argtypes = [
        ctypes.POINTER(PipeDetection),
        ctypes.c_int,
        ctypes.POINTER(GapInfo),
    ]
    lib.find_leftmost_gap.restype = ctypes.c_bool
    
    # should_tap
    lib.should_tap.argtypes = [
        ctypes.POINTER(BirdDetection),
        ctypes.POINTER(GapInfo),
        ctypes.c_int,
    ]
    lib.should_tap.restype = ctypes.c_bool
    
    # extract_game_variables
    lib.extract_game_variables.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.POINTER(GameVariables),
    ]
    lib.extract_game_variables.restype = None
    
    return lib


# Global library instance (lazy loaded)
_lib = None


def _get_lib():
    global _lib
    if _lib is None:
        _lib = _load_library()
    return _lib


# ========== Python Interface ==========

@dataclass
class FlappyBirdConfig:
    """Configuration for game functions"""
    bird_hsv_low: tuple = (20, 150, 150)
    bird_hsv_high: tuple = (40, 255, 255)
    pipe_hsv_low: tuple = (35, 100, 100)
    pipe_hsv_high: tuple = (85, 255, 255)
    bird_search_region: Optional[tuple] = None  # (x, y, w, h)
    pipe_search_region: Optional[tuple] = None


class FlappyBirdFunctions:
    """High-performance game functions using C backend"""
    
    def __init__(self, config: dict = None):
        self.lib = _get_lib()
        self.config = FlappyBirdConfig()
        
        if config:
            self._load_config(config)
    
    def _load_config(self, config: dict):
        """Load configuration from dict"""
        if 'colors' in config:
            colors = config['colors']
            if 'bird_yellow' in colors:
                self.config.bird_hsv_low = tuple(colors['bird_yellow'].get('hsv_low', [20, 150, 150]))
                self.config.bird_hsv_high = tuple(colors['bird_yellow'].get('hsv_high', [40, 255, 255]))
            if 'pipe_green' in colors:
                self.config.pipe_hsv_low = tuple(colors['pipe_green'].get('hsv_low', [35, 100, 100]))
                self.config.pipe_hsv_high = tuple(colors['pipe_green'].get('hsv_high', [85, 255, 255]))
        
        if 'regions' in config:
            regions = config['regions']
            if 'bird_search' in regions:
                r = regions['bird_search']
                self.config.bird_search_region = (r['x'], r['y'], r['width'], r['height'])
            if 'pipe_search' in regions:
                r = regions['pipe_search']
                self.config.pipe_search_region = (r['x'], r['y'], r['width'], r['height'])
    
    def _prepare_frame(self, frame: np.ndarray):
        """Prepare frame for C functions"""
        if not frame.flags['C_CONTIGUOUS']:
            frame = np.ascontiguousarray(frame)
        return frame
    
    def _make_hsv_array(self, values: tuple):
        """Create C array for HSV values"""
        arr = (ctypes.c_uint8 * 3)()
        arr[0], arr[1], arr[2] = values
        return arr
    
    def _make_region_array(self, region: Optional[tuple]):
        """Create C array for region, or None"""
        if region is None:
            return None
        arr = (ctypes.c_int * 4)()
        arr[0], arr[1], arr[2], arr[3] = region
        return arr
    
    def detect_bird(self, frame: np.ndarray) -> Optional[dict]:
        """Detect bird using C function"""
        frame = self._prepare_frame(frame)
        h, w = frame.shape[:2]
        channels = frame.shape[2] if len(frame.shape) > 2 else 1
        
        bird = BirdDetection()
        hsv_low = self._make_hsv_array(self.config.bird_hsv_low)
        hsv_high = self._make_hsv_array(self.config.bird_hsv_high)
        region = self._make_region_array(self.config.bird_search_region)
        
        found = self.lib.detect_bird_color(
            frame.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            w, h, channels,
            region,
            hsv_low, hsv_high,
            ctypes.byref(bird)
        )
        
        if found:
            return {
                'x': bird.x,
                'y': bird.y,
                'width': bird.width,
                'height': bird.height,
                'center_x': bird.center_x,
                'center_y': bird.center_y,
            }
        return None
    
    def detect_pipes(self, frame: np.ndarray, max_pipes: int = 10) -> list:
        """Detect pipes using C function"""
        frame = self._prepare_frame(frame)
        h, w = frame.shape[:2]
        channels = frame.shape[2] if len(frame.shape) > 2 else 1
        
        pipes = (PipeDetection * max_pipes)()
        hsv_low = self._make_hsv_array(self.config.pipe_hsv_low)
        hsv_high = self._make_hsv_array(self.config.pipe_hsv_high)
        region = self._make_region_array(self.config.pipe_search_region)
        
        count = self.lib.detect_pipes_color(
            frame.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            w, h, channels,
            region,
            hsv_low, hsv_high,
            pipes,
            max_pipes
        )
        
        result = []
        for i in range(count):
            result.append({
                'x': pipes[i].x,
                'y': pipes[i].y,
                'width': pipes[i].width,
                'height': pipes[i].height,
                'center_x': pipes[i].center_x,
                'center_y': pipes[i].center_y,
                'is_top': pipes[i].is_top,
            })
        return result
    
    def find_leftmost_gap(self, pipes: list) -> Optional[dict]:
        """Find leftmost pipe gap using C function"""
        if len(pipes) < 2:
            return None
        
        c_pipes = (PipeDetection * len(pipes))()
        for i, p in enumerate(pipes):
            c_pipes[i].x = p['x']
            c_pipes[i].y = p['y']
            c_pipes[i].width = p['width']
            c_pipes[i].height = p['height']
            c_pipes[i].center_x = p['center_x']
            c_pipes[i].center_y = p['center_y']
            c_pipes[i].is_top = p['is_top']
        
        gap = GapInfo()
        found = self.lib.find_leftmost_gap(c_pipes, len(pipes), ctypes.byref(gap))
        
        if found:
            return {
                'gap_x': gap.gap_x,
                'gap_y': gap.gap_y,
                'pipe_x': gap.pipe_x,
            }
        return None
    
    def should_tap(self, bird: dict, gap: dict, threshold: int = 30) -> bool:
        """Decide if should tap using C function"""
        c_bird = BirdDetection()
        c_bird.center_x = bird['center_x']
        c_bird.center_y = bird['center_y']
        
        c_gap = GapInfo()
        c_gap.gap_x = gap['gap_x']
        c_gap.gap_y = gap['gap_y']
        
        return self.lib.should_tap(ctypes.byref(c_bird), ctypes.byref(c_gap), threshold)
    
    def extract_variables(self, frame: np.ndarray) -> Dict[str, float]:
        """Extract all game variables using C function - fastest method"""
        frame = self._prepare_frame(frame)
        h, w = frame.shape[:2]
        channels = frame.shape[2] if len(frame.shape) > 2 else 1
        
        vars = GameVariables()
        
        self.lib.extract_game_variables(
            frame.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            w, h, channels,
            None,  # config (using defaults in C)
            ctypes.byref(vars)
        )
        
        result = {
            'bird_found': 1.0 if vars.bird_found else 0.0,
            'pipe_count': float(vars.pipe_count),
            'gap_found': 1.0 if vars.gap_found else 0.0,
        }
        
        if vars.bird_found:
            result['bird_x'] = vars.bird_x
            result['bird_y'] = vars.bird_y
        
        if vars.gap_found:
            result['gap_center_x'] = vars.gap_center_x
            result['gap_center_y'] = vars.gap_center_y
        
        return result


# Factory function for game loader
def create_game_functions(config: dict = None) -> FlappyBirdFunctions:
    """Create game functions instance"""
    return FlappyBirdFunctions(config)
