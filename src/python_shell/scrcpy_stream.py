"""
RashPlayer-C: Scrcpy Video Stream
H.264 video stream receiver for scrcpy-server via socket
"""

import socket
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Callable
import numpy as np
import av


class ScrcpyVideoStream:
    """H.264 video stream receiver from scrcpy-server"""
    
    def __init__(self, serial: str, server_jar: str = "scrcpy-server.jar"):
        self.serial = serial
        self.server_jar = Path(__file__).parent.parent.parent / server_jar
        self._socket: Optional[socket.socket] = None
        self._server_proc: Optional[subprocess.Popen] = None
        self._stream_thread: Optional[threading.Thread] = None
        self._running = False
        self._frame_callback: Optional[Callable] = None
        self._local_port = 27183
        self._device_name = ""
        self._width = 0
        self._height = 0
        
    def start(self, callback: Callable[[np.ndarray], None]) -> bool:
        """Start scrcpy-server and begin streaming"""
        if self._running:
            return False
            
        self._frame_callback = callback
        self._running = True
        
        # Start server and streaming in background thread
        self._stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._stream_thread.start()
        
        return True
    
    def stop(self):
        """Stop streaming and cleanup"""
        self._running = False
        
        if self._stream_thread:
            self._stream_thread.join(timeout=2)
            self._stream_thread = None
        
        self._cleanup()
    
    def _stream_loop(self):
        """Main streaming loop"""
        try:
            # 1. Push server to device
            if not self._push_server():
                print("Failed to push scrcpy-server")
                return
            
            # 2. Start scrcpy-server
            if not self._start_server():
                print("Failed to start scrcpy-server")
                return
            
            # 3. Setup port forwarding
            if not self._setup_forward():
                print("Failed to setup port forwarding")
                return
            
            # 4. Connect to socket
            if not self._connect_socket():
                print("Failed to connect to socket")
                return
            
            # 5. Read header
            if not self._read_header():
                print("Failed to read header")
                return
            
            print(f"Connected to {self._device_name} ({self._width}x{self._height})")
            
            # 6. Stream H.264 data
            self._stream_h264()
            
        except Exception as e:
            print(f"Stream error: {e}")
        finally:
            self._cleanup()
    
    def _push_server(self) -> bool:
        """Push scrcpy-server.jar to device"""
        try:
            result = subprocess.run(
                ["adb", "-s", self.serial, "push", str(self.server_jar), "/data/local/tmp/scrcpy-server.jar"],
                capture_output=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception as e:
            print(f"Push server error: {e}")
            return False
    
    def _start_server(self) -> bool:
        """Start scrcpy-server on device"""
        try:
            # scrcpy-server arguments for version 3.3.4
            cmd = [
                "adb", "-s", self.serial, "shell",
                "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
                "app_process", "/", "com.genymobile.scrcpy.Server",
                "3.3.4",  # Server version
                "log_level=info",
                "video_codec=h264",
                "max_size=1920",
                "max_fps=60",
                "video_bit_rate=4000000",
                "tunnel_forward=true",
                "control=false",  # No control, video only
                "audio=false",
                "cleanup=true"
            ]
            
            self._server_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Give server time to start
            time.sleep(1)
            
            return self._server_proc.poll() is None
            
        except Exception as e:
            print(f"Start server error: {e}")
            return False
    
    def _setup_forward(self) -> bool:
        """Setup ADB port forwarding"""
        try:
            # Remove existing forward
            subprocess.run(
                ["adb", "-s", self.serial, "forward", "--remove", f"tcp:{self._local_port}"],
                capture_output=True
            )
            
            # Setup new forward
            result = subprocess.run(
                ["adb", "-s", self.serial, "forward", f"tcp:{self._local_port}", "localabstract:scrcpy"],
                capture_output=True,
                timeout=5
            )
            
            return result.returncode == 0
            
        except Exception as e:
            print(f"Setup forward error: {e}")
            return False
    
    def _connect_socket(self) -> bool:
        """Connect to scrcpy socket"""
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(5)
            
            # Retry connection a few times
            for attempt in range(5):
                try:
                    self._socket.connect(('127.0.0.1', self._local_port))
                    self._socket.settimeout(None)  # Blocking mode
                    return True
                except (ConnectionRefusedError, socket.timeout):
                    if attempt < 4:
                        time.sleep(0.5)
                        continue
                    return False
            
            return False
            
        except Exception as e:
            print(f"Connect socket error: {e}")
            return False
    
    def _read_header(self) -> bool:
        """Read 68-byte header from scrcpy stream"""
        try:
            # Device name (64 bytes, NUL-terminated)
            device_name_bytes = self._socket.recv(64)
            self._device_name = device_name_bytes.decode('utf-8').rstrip('\x00')
            
            # Width (2 bytes, big-endian)
            width_bytes = self._socket.recv(2)
            self._width = struct.unpack('>H', width_bytes)[0]
            
            # Height (2 bytes, big-endian)
            height_bytes = self._socket.recv(2)
            self._height = struct.unpack('>H', height_bytes)[0]
            
            return self._width > 0 and self._height > 0
            
        except Exception as e:
            print(f"Read header error: {e}")
            return False
    
    def _stream_h264(self):
        """Stream and decode H.264 video"""
        codec = av.CodecContext.create('h264', 'r')
        frame_count = 0
        
        try:
            while self._running:
                # Read H.264 data from socket
                try:
                    data = self._socket.recv(65536)
                    if not data:
                        print("Socket closed")
                        break
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"Socket recv error: {e}")
                    break
                
                # Decode H.264 packets
                try:
                    packets = codec.parse(data)
                    for packet in packets:
                        frames = codec.decode(packet)
                        for frame in frames:
                            # Convert to numpy array (RGB)
                            img = frame.to_ndarray(format='rgba')
                            
                            if self._frame_callback:
                                self._frame_callback(img)
                            
                            frame_count += 1
                            if frame_count == 1:
                                print(f"First frame decoded: {img.shape}")
                                
                except Exception as e:
                    print(f"Decode error: {e}")
                    continue
                    
        except Exception as e:
            print(f"Stream H.264 error: {e}")
        finally:
            print(f"Stream ended. Total frames: {frame_count}")
    
    def _cleanup(self):
        """Cleanup resources"""
        # Close socket
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        
        # Stop server
        if self._server_proc:
            try:
                self._server_proc.terminate()
                self._server_proc.wait(timeout=2)
            except Exception:
                try:
                    self._server_proc.kill()
                except Exception:
                    pass
            self._server_proc = None
        
        # Remove port forward
        try:
            subprocess.run(
                ["adb", "-s", self.serial, "forward", "--remove", f"tcp:{self._local_port}"],
                capture_output=True,
                timeout=2
            )
        except Exception:
            pass
