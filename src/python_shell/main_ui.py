"""
RashPlayer-C: Main UI
PySide6 desktop application with OpenGL device preview
"""

import sys
import time
import numpy as np
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QLabel, QGroupBox, QFileDialog,
    QStatusBar, QFrame, QSlider, QSpinBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL.GL import (
    glClearColor, glEnable, glGenTextures, glBindTexture, glTexParameteri,
    glClear, glTexImage2D, glBegin, glTexCoord2f, glVertex2f, glEnd,
    GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR, GL_TEXTURE_MAG_FILTER,
    GL_COLOR_BUFFER_BIT, GL_RGBA, GL_UNSIGNED_BYTE, GL_QUADS
)

from device_manager import DeviceManager, DeviceInterface
from gesture_executor import GestureExecutor
from shared_bridge import SharedMemoryBridge, GameState
from yaml_parser import YAMLParser, WorkflowConfig


class DevicePreviewWidget(QOpenGLWidget):
    """OpenGL widget for real-time device preview"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._texture_id = 0
        self._frame: np.ndarray | None = None
        self._frame_width = 1920
        self._frame_height = 1080
        self.setMinimumSize(480, 270)
    
    def initializeGL(self):
        glClearColor(0.1, 0.1, 0.1, 1.0)
        glEnable(GL_TEXTURE_2D)
        self._texture_id = glGenTextures(1)
        
        glBindTexture(GL_TEXTURE_2D, self._texture_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    
    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT)
        
        if self._frame is not None:
            glBindTexture(GL_TEXTURE_2D, self._texture_id)
            glTexImage2D(
                GL_TEXTURE_2D, 0, GL_RGBA,
                self._frame_width, self._frame_height, 0,
                GL_RGBA, GL_UNSIGNED_BYTE, self._frame
            )
            
            # Calculate aspect ratio preserving coordinates
            widget_width = self.width()
            widget_height = self.height()
            widget_aspect = widget_width / widget_height if widget_height > 0 else 1.0
            frame_aspect = self._frame_width / self._frame_height if self._frame_height > 0 else 1.0
            
            # Calculate viewport coordinates to maintain aspect ratio
            if frame_aspect > widget_aspect:
                # Frame is wider - fit to width, add letterboxing top/bottom
                scale_x = 1.0
                scale_y = widget_aspect / frame_aspect
            else:
                # Frame is taller - fit to height, add pillarboxing left/right
                scale_x = frame_aspect / widget_aspect
                scale_y = 1.0
            
            # Draw quad with proper aspect ratio
            glBegin(GL_QUADS)
            glTexCoord2f(0, 1)
            glVertex2f(-scale_x, -scale_y)
            glTexCoord2f(1, 1)
            glVertex2f(scale_x, -scale_y)
            glTexCoord2f(1, 0)
            glVertex2f(scale_x, scale_y)
            glTexCoord2f(0, 0)
            glVertex2f(-scale_x, scale_y)
            glEnd()
    
    def update_frame(self, frame: np.ndarray):
        self._frame = frame
        self._frame_height, self._frame_width = frame.shape[:2]
        self.update()


class PreviewThread(QThread):
    """Background thread for device preview only (no processing)"""
    
    frame_captured = Signal(np.ndarray)
    
    def __init__(self, device: DeviceInterface):
        super().__init__()
        self.device = device
        self.running = False
    
    def run(self):
        self.running = True
        
        def on_frame(frame: np.ndarray):
            self.frame_captured.emit(frame)
        
        self.device.start_capture(on_frame)
        
        while self.running:
            time.sleep(0.016)  # Just keep thread alive
        
        self.device.stop_capture()
    
    def stop(self):
        self.running = False
        self.wait()


class ProcessingThread(QThread):
    """Background thread for C-Core processing loop"""
    
    results_ready = Signal(list, object, tuple)
    frame_captured = Signal(np.ndarray)
    
    def __init__(self, bridge: SharedMemoryBridge, device: DeviceInterface):
        super().__init__()
        self.bridge = bridge
        self.device = device
        self.running = False
        self.polling_hz = 60
    
    def run(self):
        self.running = True
        interval = 1.0 / self.polling_hz
        
        def on_frame(frame: np.ndarray):
            self.bridge.write_frame(frame)
            self.frame_captured.emit(frame)
        
        self.device.start_capture(on_frame)
        
        while self.running:
            loop_start = time.time()
            
            ready, results, action = self.bridge.read_results()
            if ready:
                latency = self.bridge.get_latency()
                self.results_ready.emit(results, action, latency)
            
            elapsed = time.time() - loop_start
            if elapsed < interval:
                time.sleep(interval - elapsed)
        
        self.device.stop_capture()
    
    def stop(self):
        self.running = False
        self.wait()


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RashPlayer-C - Mobile Automation")
        self.setMinimumSize(1200, 800)
        
        self.device_manager = DeviceManager()
        self.bridge = SharedMemoryBridge()
        self.gesture_executor: GestureExecutor | None = None
        self.workflow: WorkflowConfig | None = None
        self.preview_thread: PreviewThread | None = None
        self.processing_thread: ProcessingThread | None = None
        
        self._setup_ui()
        self._connect_signals()
        
        # Initial device scan
        QTimer.singleShot(100, self._scan_devices)
    
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        
        # Left panel - Controls
        left_panel = QVBoxLayout()
        left_panel.setSpacing(10)
        
        # Device group
        device_group = QGroupBox("Device")
        device_layout = QVBoxLayout(device_group)
        
        self.device_combo = QComboBox()
        self.device_combo.setPlaceholderText("Select device...")
        device_layout.addWidget(self.device_combo)
        
        device_buttons = QHBoxLayout()
        self.scan_btn = QPushButton("Scan")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setEnabled(False)
        device_buttons.addWidget(self.scan_btn)
        device_buttons.addWidget(self.connect_btn)
        device_layout.addLayout(device_buttons)
        
        left_panel.addWidget(device_group)
        
        # Workflow group
        workflow_group = QGroupBox("Workflow")
        workflow_layout = QVBoxLayout(workflow_group)
        
        self.workflow_label = QLabel("No workflow loaded")
        workflow_layout.addWidget(self.workflow_label)
        
        self.load_workflow_btn = QPushButton("Load YAML...")
        workflow_layout.addWidget(self.load_workflow_btn)
        
        hz_layout = QHBoxLayout()
        hz_layout.addWidget(QLabel("Polling Hz:"))
        self.hz_spin = QSpinBox()
        self.hz_spin.setRange(10, 200)
        self.hz_spin.setValue(60)
        hz_layout.addWidget(self.hz_spin)
        workflow_layout.addLayout(hz_layout)
        
        left_panel.addWidget(workflow_group)
        
        # Control group
        control_group = QGroupBox("Control")
        control_layout = QVBoxLayout(control_group)
        
        self.start_btn = QPushButton("▶ Start")
        self.start_btn.setEnabled(False)
        self.start_btn.setStyleSheet("font-size: 16px; padding: 10px;")
        control_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.setEnabled(False)
        control_layout.addWidget(self.stop_btn)
        
        left_panel.addWidget(control_group)
        
        # Stats group
        stats_group = QGroupBox("Performance")
        stats_layout = QVBoxLayout(stats_group)
        
        self.vision_latency_label = QLabel("Vision: --")
        self.brain_latency_label = QLabel("Brain: --")
        self.total_latency_label = QLabel("Total: --")
        self.state_label = QLabel("State: IDLE")
        
        stats_layout.addWidget(self.vision_latency_label)
        stats_layout.addWidget(self.brain_latency_label)
        stats_layout.addWidget(self.total_latency_label)
        stats_layout.addWidget(self.state_label)
        
        left_panel.addWidget(stats_group)
        left_panel.addStretch()
        
        layout.addLayout(left_panel, 1)
        
        # Right panel - Preview
        preview_group = QGroupBox("Device Preview")
        preview_layout = QVBoxLayout(preview_group)
        
        self.preview_widget = DevicePreviewWidget()
        preview_layout.addWidget(self.preview_widget)
        
        layout.addWidget(preview_group, 3)
        
        # Status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready")
    
    def _connect_signals(self):
        self.scan_btn.clicked.connect(self._scan_devices)
        self.connect_btn.clicked.connect(self._connect_device)
        self.load_workflow_btn.clicked.connect(self._load_workflow)
        self.start_btn.clicked.connect(self._start_processing)
        self.stop_btn.clicked.connect(self._stop_processing)
        self.device_combo.currentIndexChanged.connect(self._on_device_selected)
    
    def _scan_devices(self):
        self.statusBar.showMessage("Scanning devices...")
        devices = self.device_manager.scan_devices()
        
        self.device_combo.clear()
        for device in devices:
            self.device_combo.addItem(
                f"{device.name} ({device.serial})",
                device.serial
            )
        
        self.statusBar.showMessage(f"Found {len(devices)} device(s)")
    
    def _on_device_selected(self, index):
        self.connect_btn.setEnabled(index >= 0)
    
    def _connect_device(self):
        serial = self.device_combo.currentData()
        if not serial:
            return
        
        # Stop any existing preview
        if self.preview_thread:
            self.preview_thread.stop()
            self.preview_thread = None
        
        self.statusBar.showMessage(f"Connecting to {serial}...")
        device = self.device_manager.connect_device(serial)
        
        if device:
            self.gesture_executor = GestureExecutor(device)
            self.start_btn.setEnabled(True)
            self.statusBar.showMessage(f"Connected to {serial}")
            
            # Create shared memory
            if not self.bridge.create():
                self.statusBar.showMessage("Failed to create shared memory!")
            
            # Start preview thread immediately
            self.preview_thread = PreviewThread(device)
            self.preview_thread.frame_captured.connect(self.preview_widget.update_frame)
            self.preview_thread.start()
            self.statusBar.showMessage(f"Connected to {serial} - Live preview active")
        else:
            self.statusBar.showMessage(f"Failed to connect to {serial}")
    
    def _load_workflow(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Load Workflow", 
            str(Path(__file__).parent.parent / "metadata"),
            "YAML Files (*.yaml *.yml)"
        )
        
        if filepath:
            try:
                self.workflow = YAMLParser.load(filepath)
                self.workflow_label.setText(f"{self.workflow.name} v{self.workflow.version}")
                self.hz_spin.setValue(self.workflow.polling_hz)
                self.statusBar.showMessage(f"Loaded workflow: {self.workflow.name}")
            except Exception as e:
                self.statusBar.showMessage(f"Failed to load workflow: {e}")
    
    def _start_processing(self):
        device = self.device_manager.get_active_device()
        if not device:
            return
        
        # Stop preview thread (processing thread will handle frames)
        if self.preview_thread:
            self.preview_thread.stop()
            self.preview_thread = None
        
        self.processing_thread = ProcessingThread(self.bridge, device)
        self.processing_thread.polling_hz = self.hz_spin.value()
        self.processing_thread.results_ready.connect(self._on_results)
        self.processing_thread.frame_captured.connect(self.preview_widget.update_frame)
        self.processing_thread.start()
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.statusBar.showMessage("Processing started")
    
    def _stop_processing(self):
        device = self.device_manager.get_active_device()
        
        if self.processing_thread:
            self.processing_thread.stop()
            self.processing_thread = None
        
        # Restart preview thread
        if device and not self.preview_thread:
            self.preview_thread = PreviewThread(device)
            self.preview_thread.frame_captured.connect(self.preview_widget.update_frame)
            self.preview_thread.start()
        
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.statusBar.showMessage("Processing stopped - Preview active")
    
    def _on_results(self, results, action, latency):
        vision_us, brain_us, total_us = latency
        
        self.vision_latency_label.setText(f"Vision: {vision_us}µs")
        self.brain_latency_label.setText(f"Brain: {brain_us}µs")
        self.total_latency_label.setText(f"Total: {total_us}µs")
        
        state = self.bridge.get_state()
        self.state_label.setText(f"State: {state.name}")
        
        # Execute action if pending
        if action and self.gesture_executor:
            if action.action_type.TAP:
                self.gesture_executor.tap(action.start[0], action.start[1])
    
    def closeEvent(self, event):
        self._stop_processing()
        if self.preview_thread:
            self.preview_thread.stop()
            self.preview_thread = None
        self.bridge.destroy()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Dark theme
    palette = app.palette()
    from PySide6.QtGui import QColor
    palette.setColor(palette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(palette.ColorRole.WindowText, Qt.white)
    palette.setColor(palette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(palette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(palette.ColorRole.ToolTipBase, Qt.white)
    palette.setColor(palette.ColorRole.ToolTipText, Qt.white)
    palette.setColor(palette.ColorRole.Text, Qt.white)
    palette.setColor(palette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(palette.ColorRole.ButtonText, Qt.white)
    palette.setColor(palette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(palette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(palette.ColorRole.HighlightedText, Qt.black)
    app.setPalette(palette)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
