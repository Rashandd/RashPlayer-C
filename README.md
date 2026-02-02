# RashPlayer-C 🎮⚡

**RashPlayer-C** is a high-performance, modular mobile automation framework designed for low-latency game automation. It combines a distinct **C-Core** for sub-10ms vision and logic processing with a flexible **Python Shell** for device management and UI.



## 🚀 Key Features

*   **⚡ Blazing Fast**: Vision (SIMD) and Logic (FSM) run in C, achieving **<10ms loop times**.
*   **🥷 Stealth Mode**: Human-like gesture engine uses **Bezier curves** and **Gaussian randomization** to bypass anti-bot detection.
*   **🔌 Pluggable Workflows**: Define game logic in simple **YAML files**—no coding required for new games.
*   **🌉 Zero-Copy Bridge**: Uses `mmap` for direct memory access between Python capture and C processing.
*   **📱 Hybrid Support**: Works seamlessly with Physical Devices (USB) and Emulators.

## 🛠️ Architecture

The system uses a split-process architecture:

1.  **C-Core (`librashplayer.so`)**:
    *   **Vision Engine**: SIMD-optimized (SSE4.2/NEON) template matching and color search.
    *   **Logic Brain**: Finite State Machine (FSM) that processes game states at 100Hz.
2.  **Python**:
    *   **PySide6 UI**: Real-time OpenGL preview and controls.
    *   **Device Manager**: Abstracts ADB and Scrcpy interactions.
    *   **Gesture Executor**: Generates natural input events.
    *   **FSM Engine**: State machine for game automation workflows.

## 📦 Installation

### Prerequisites
*   Linux (x86_64 or ARM64)
*   Python 3.11+
*   GCC 11+
*   `adb` and `scrcpy` installed and in PATH

### 1. Build C-Core
```bash
cd build
make
```

### 2. Install Python Dependencies
```bash
pip install -r requirements.txt
```

## 🎮 Usage

1.  **Connect your device** via USB or start your emulator.
2.  **Launch the UI**:
    ```bash
    cd src/python
    python main_ui.py
    ```
3.  **Select your device** from the dropdown.
4.  **Load a Game** from `games/` folder (e.g., flappy_bird).
5.  Click **▶ Start** to run the FSM automation.

## 🧩 Creating Game Workflows

Games are defined in `games/` directory with FSM structure:

```
games/flappy_bird/
├── main.yaml          # State machine: menu → gameplay → result
├── states/
│   └── gameplay.yaml  # Active game logic
├── assets/            # Template images for detection
├── locations.yaml     # Tap targets and regions
└── colors.yaml        # HSV color definitions
```

Use the **Scanner tab** in the UI to interactively define screen elements.

## Memory Bank

For AI agents contributing to this project, please refer to the `.memorybank/` directory for detailed context, architecture patterns, and active tasks.

## 📄 License

MIT License - See [LICENSE](LICENSE) for details.
