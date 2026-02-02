# Product Context

## Problem Statement
Existing mobile automation tools are either:
- **Too slow**: Pure Python/Java implementations suffer from interpretation overhead and memory copying.
- **Detectable**: Linear/robotic mouse movements are easily flagged by anti-cheat systems.
- **Hard to configure**: Requires hard-coding logic for each game.

## Solution
RashPlayer-C solves this by:
1.  **Offloading Compute**: Heavy vision tasks use SIMD-optimized C code.
2.  **Zero-Copy Architecture**: Uses `mmap` to share raw video frames between capture (Python) and processing (C), eliminating data serialization overhead.
3.  **Humanization**: Implements Bezier curve algorithms for swipes and Gaussian distribution for click timing/position.
4.  **Metadata-Driven**: Game logic is defined in external YAML files, allowing users to share and switch "profiles" without coding.
