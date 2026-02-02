# Tech Context

## Core Technologies
- **Language**: C (C11 standard) for Core, Python 3.11 for Shell.
- **GUI**: PySide6 (Qt for Python).
- **Computer Vision**: Custom SIMD implementation (SSE4.2/NEON), avoiding heavy OpenCV dependency for core matching loops.
- **Video Streaming**: Scrcpy-server with H.264 decoding via PyAV (FFmpeg bindings).
- **Build System**: Make (Linux), Batch/MSVC (Windows).

## Dependencies
- `adb` & `scrcpy` (System level)
- `numpy` (Python)
- `av` (PyAV - H.264 video decoding)
- `posix_ipc` (Python)
- `PyYAML` (Python)
- `PyOpenGL` (Python)

## Constraints
- **Latency**: Total loop time must be <10ms. Video streaming achieves <50ms.
- **Memory**: Shared memory segment fixed at ~8MB (1920x1080x4 + Header).
- **Platform**: Primarily Linux x86_64/ARM64. Windows support via MSVC.
- **Video**: 30-60 FPS H.264 stream over socket (port 27183).
