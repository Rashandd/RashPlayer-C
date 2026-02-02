# Video Streaming Architecture

## Overview
RashPlayer-C uses scrcpy-server for high-performance H.264 video streaming from Android devices over a local socket connection.

## Architecture

### Components

```
┌─────────────────┐
│  Python Shell   │
│   (main_ui.py)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ ScrcpyVideoStream│
│(scrcpy_stream.py)│
└────────┬────────┘
         │
         ├──► ADB (push server, port forward)
         │
         ▼
┌─────────────────┐
│  TCP Socket     │
│  localhost:27183│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ scrcpy-server   │
│  (on device)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  H.264 Stream   │
│  (60 FPS)       │
└─────────────────┘
```

## Protocol Details

### Connection Flow
1. **Push Server**: `adb push scrcpy-server.jar /data/local/tmp/`
2. **Start Server**: Launch scrcpy-server via `app_process`
3. **Port Forward**: `adb forward tcp:27183 localabstract:scrcpy`
4. **Connect**: TCP socket to `localhost:27183`
5. **Read Header**: 68 bytes (device name, width, height)
6. **Stream**: Continuous H.264 packets

### Header Format (68 bytes)
```
Offset | Size | Type       | Description
-------|------|------------|------------------
0      | 64   | char[64]   | Device name (NUL-terminated)
64     | 2    | uint16_be  | Frame width
66     | 2    | uint16_be  | Frame height
```

### Server Arguments
```python
"video_codec=h264"       # H.264 encoding
"max_size=1920"          # Max dimension
"max_fps=60"             # Target 60 FPS
"video_bit_rate=4000000" # 4 Mbps
"control=false"          # Video only, no input
"audio=false"            # No audio stream
"tunnel_forward=true"    # Use ADB forward
```

## Decoding Pipeline

### PyAV Integration
```python
import av

# Create H.264 decoder
codec = av.CodecContext.create('h264', 'r')

# Decode loop
while streaming:
    data = socket.recv(65536)
    packets = codec.parse(data)
    for packet in packets:
        frames = codec.decode(packet)
        for frame in frames:
            # Convert to RGBA numpy array
            img = frame.to_ndarray(format='rgba')
            callback(img)  # Send to OpenGL preview
```

## Performance Metrics

### Latency
- **Target**: <50ms end-to-end
- **Achieved**: ~30-50ms (3-6x better than adb screencap)
- **Breakdown**:
  - Device encoding: ~10ms
  - Network transfer: ~5ms
  - H.264 decoding: ~10-15ms
  - OpenGL rendering: ~5-10ms

### Frame Rate
- **Target**: 60 FPS
- **Achieved**: 30-60 FPS (device dependent)
- **Factors**:
  - Device screen refresh rate
  - Network bandwidth
  - CPU decoding speed

### CPU Usage
- **H.264 Decoding**: ~15-20% (PyAV/FFmpeg)
- **OpenGL Rendering**: ~5-10%
- **Total**: ~20-30% (vs ~40-50% with PNG screencap)

## Error Handling

### Automatic Cleanup
- Socket disconnection → cleanup resources
- Server crash → terminate and remove forward
- Decode errors → skip frame, continue streaming

### Retry Logic
- Socket connection: 5 retries with 500ms delay
- Server start: 1s wait for initialization
- Port forward: Remove existing before creating new

## Known Limitations

1. **Protocol Version**: Tied to scrcpy 3.3.4
2. **Codec Support**: H.264 only (no AV1/HEVC)
3. **Audio**: Not implemented
4. **Multi-Device**: One stream per device instance
5. **Port Conflict**: Only one stream per port 27183

## Future Enhancements

- [ ] Multi-codec support (AV1, HEVC)
- [ ] Audio stream integration
- [ ] Dynamic port allocation for multi-device
- [ ] Hardware decoding (VAAPI, NVDEC)
- [ ] Adaptive bitrate based on network conditions
