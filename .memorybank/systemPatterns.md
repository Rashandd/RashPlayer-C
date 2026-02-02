# System Patterns

## Architecture
The system follows a **Split-Process Architecture**:

```mermaid
flowchart TD
    subgraph Python Shell
        UI[PySide6 UI]
        DM[Device Manager]
        GE[Gesture Executor]
        BridgePy[Shared Memory Bridge (Python)]
    end

    subgraph C-Core
        BridgeC[Shared Memory Bridge (C)]
        VE[Vision Engine (SIMD)]
        LB[Logic Brain (FSM)]
    end

    Device[Android Device] -->|ADB/Scrcpy| DM
    DM -->|Raw Frame| BridgePy
    BridgePy <-->|mmap| BridgeC
    BridgeC --> VE
    VE --> LB
    LB -->|Action Command| BridgeC
    BridgePy -->|Read Action| GE
    GE -->|Input Event| Device
```

## Design Patterns
1.  **Finite State Machine (FSM)**: The `Logic Brain` uses an FSM to manage game states (IDLE, DETECTING, EXECUTING).
2.  **Shared Memory IPC**: Custom protocol over `mmap` for high-frequency data exchange.
3.  **Plugin System**: YAML files define `VisualTriggers` and `DecisionRules`, which are parsed and loaded into the C-Core at runtime.
4.  **Strategy Pattern**: `DeviceInterface` allows switching between Physical and Virtual devices transparently.
