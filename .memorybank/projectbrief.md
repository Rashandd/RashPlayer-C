# Project Brief: RashPlayer-C

RashPlayer-C is a high-performance, modular mobile automation framework designed for low-latency game automation.

## Core Philosophy
- **Speed**: <10ms loop time via C-Core and Shared Memory.
- **Stealth**: Human-like gesture engine with Bezier curves and randomization to bypass anti-bot detection.
- **Modularity**: Separation of heavy vision/logic (C) from UI/Device management (Python).
- **Flexibility**: YAML-based workflow definitions for rapid game adaptation.

## Key Architecturs
1.  **C-Core**: Handles Vision (SIMD) and Logic (FSM).
2.  **Python Shell**: Handles UI (PySide6), Device Communication (ADB/Scrcpy), and Gestures.
3.  **Shared Memory Bridge**: Zero-copy IPC between Python and C.
