"""
RashPlayer-C: Scanner Widget
Interactive tool for defining screen elements with detection overlay
"""

import numpy as np
from pathlib import Path
from typing import Optional, Tuple
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QLineEdit, QComboBox, QGroupBox, QListWidget,
    QSplitter, QFrame, QInputDialog, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QPoint, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QMouseEvent

from game_loader import GameLoader, GameConfig, TapTarget, Region


class ScannerPreview(QWidget):
    """Preview widget with interactive region selection"""
    
    element_selected = Signal(str, int, int, int, int)  # name, x, y, w, h
    tap_marked = Signal(str, int, int)  # name, x, y
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame: Optional[np.ndarray] = None
        self._frame_width = 1080
        self._frame_height = 2400
        
        # Selection state
        self._selecting = False
        self._selection_start: Optional[QPoint] = None
        self._selection_rect: Optional[QRect] = None
        self._mode = "region"  # "region" or "tap"
        
        # Overlay data
        self._regions: list = []
        self._targets: list = []
        self._current_state = "IDLE"
        
        self.setMinimumSize(360, 640)
        self.setMouseTracking(True)
    
    def set_mode(self, mode: str):
        """Set selection mode: 'region' or 'tap'"""
        self._mode = mode
    
    def set_state(self, state: str):
        """Set current FSM state for display"""
        self._current_state = state
    
    def update_frame(self, frame: np.ndarray):
        """Update preview frame"""
        self._frame = frame
        self._frame_height, self._frame_width = frame.shape[:2]
        self.update()
    
    def set_overlay_data(self, regions: list, targets: list):
        """Set regions and targets to draw"""
        self._regions = regions
        self._targets = targets
        self.update()
    
    def _widget_to_frame(self, pos: QPoint) -> Tuple[int, int]:
        """Convert widget coordinates to frame coordinates"""
        scale_x = self._frame_width / self.width()
        scale_y = self._frame_height / self.height()
        return int(pos.x() * scale_x), int(pos.y() * scale_y)
    
    def _frame_to_widget(self, x: int, y: int) -> Tuple[int, int]:
        """Convert frame coordinates to widget coordinates"""
        scale_x = self.width() / self._frame_width
        scale_y = self.height() / self._frame_height
        return int(x * scale_x), int(y * scale_y)
    
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._selecting = True
            self._selection_start = event.pos()
            self._selection_rect = QRect(event.pos(), event.pos())
    
    def mouseMoveEvent(self, event: QMouseEvent):
        if self._selecting and self._selection_start:
            self._selection_rect = QRect(self._selection_start, event.pos()).normalized()
            self.update()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._selecting:
            self._selecting = False
            
            if self._mode == "tap":
                # Mark tap target at click position
                fx, fy = self._widget_to_frame(event.pos())
                name, ok = QInputDialog.getText(self, "Tap Target", "Name for this tap target:")
                if ok and name:
                    self.tap_marked.emit(name, fx, fy)
            
            elif self._mode == "region" and self._selection_rect:
                # Get rectangle in frame coordinates
                x1, y1 = self._widget_to_frame(self._selection_rect.topLeft())
                x2, y2 = self._widget_to_frame(self._selection_rect.bottomRight())
                w, h = x2 - x1, y2 - y1
                
                if w > 10 and h > 10:  # Minimum size
                    name, ok = QInputDialog.getText(self, "Region", "Name for this region:")
                    if ok and name:
                        self.element_selected.emit(name, x1, y1, w, h)
            
            self._selection_rect = None
            self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw frame
        if self._frame is not None:
            from PySide6.QtGui import QImage, QPixmap
            h, w = self._frame.shape[:2]
            if self._frame.shape[2] == 4:
                fmt = QImage.Format_RGBA8888
            else:
                fmt = QImage.Format_RGB888
            qimg = QImage(self._frame.data, w, h, self._frame.strides[0], fmt)
            pixmap = QPixmap.fromImage(qimg)
            painter.drawPixmap(self.rect(), pixmap)
        else:
            painter.fillRect(self.rect(), QColor(30, 30, 30))
        
        # Draw regions (green boxes)
        for region in self._regions:
            wx, wy = self._frame_to_widget(region.x, region.y)
            ww = int(region.width * self.width() / self._frame_width)
            wh = int(region.height * self.height() / self._frame_height)
            
            painter.setPen(QPen(QColor(0, 255, 0, 200), 2))
            painter.setBrush(QBrush(QColor(0, 255, 0, 30)))
            painter.drawRect(wx, wy, ww, wh)
            
            # Label
            painter.setPen(QPen(QColor(0, 255, 0)))
            painter.setFont(QFont("Arial", 10))
            painter.drawText(wx + 5, wy + 15, region.name)
        
        # Draw tap targets (blue crosshairs)
        for target in self._targets:
            wx, wy = self._frame_to_widget(target.x, target.y)
            
            painter.setPen(QPen(QColor(0, 150, 255), 2))
            painter.drawLine(wx - 15, wy, wx + 15, wy)
            painter.drawLine(wx, wy - 15, wx, wy + 15)
            painter.drawEllipse(wx - 8, wy - 8, 16, 16)
            
            # Label
            painter.drawText(wx + 12, wy - 5, target.name)
        
        # Draw current selection
        if self._selection_rect and not self._selection_rect.isEmpty():
            if self._mode == "region":
                painter.setPen(QPen(QColor(255, 255, 0), 2, Qt.DashLine))
                painter.setBrush(QBrush(QColor(255, 255, 0, 40)))
            else:
                painter.setPen(QPen(QColor(0, 150, 255), 2, Qt.DashLine))
            painter.drawRect(self._selection_rect)
        
        # Draw state label
        painter.setPen(QPen(QColor(255, 255, 0)))
        painter.setFont(QFont("Arial", 14, QFont.Bold))
        painter.drawText(10, 25, f"State: {self._current_state}")
        
        # Draw mode indicator
        mode_color = QColor(0, 255, 0) if self._mode == "region" else QColor(0, 150, 255)
        painter.setPen(QPen(mode_color))
        painter.drawText(10, 45, f"Mode: {self._mode.upper()}")


class ScannerWidget(QWidget):
    """Scanner panel for defining game elements"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.game_loader = GameLoader()
        self.game_config: Optional[GameConfig] = None
        
        self._setup_ui()
        self._connect_signals()
        self._refresh_games()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Game selector
        game_group = QGroupBox("Game")
        game_layout = QHBoxLayout(game_group)
        self.game_combo = QComboBox()
        self.load_btn = QPushButton("Load")
        self.new_btn = QPushButton("New")
        game_layout.addWidget(self.game_combo)
        game_layout.addWidget(self.load_btn)
        game_layout.addWidget(self.new_btn)
        layout.addWidget(game_group)
        
        # Scanner preview
        self.preview = ScannerPreview()
        layout.addWidget(self.preview, 1)
        
        # Mode buttons
        mode_group = QGroupBox("Selection Mode")
        mode_layout = QHBoxLayout(mode_group)
        self.region_btn = QPushButton("📦 Region")
        self.region_btn.setCheckable(True)
        self.region_btn.setChecked(True)
        self.tap_btn = QPushButton("👆 Tap Target")
        self.tap_btn.setCheckable(True)
        self.capture_btn = QPushButton("📷 Capture Asset")
        mode_layout.addWidget(self.region_btn)
        mode_layout.addWidget(self.tap_btn)
        mode_layout.addWidget(self.capture_btn)
        layout.addWidget(mode_group)
        
        # Elements list
        elements_group = QGroupBox("Defined Elements")
        elements_layout = QVBoxLayout(elements_group)
        self.elements_list = QListWidget()
        elements_layout.addWidget(self.elements_list)
        
        btn_layout = QHBoxLayout()
        self.delete_btn = QPushButton("Delete")
        self.save_btn = QPushButton("💾 Save")
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.save_btn)
        elements_layout.addLayout(btn_layout)
        layout.addWidget(elements_group)
    
    def _connect_signals(self):
        self.load_btn.clicked.connect(self._load_game)
        self.new_btn.clicked.connect(self._new_game)
        self.region_btn.clicked.connect(lambda: self._set_mode("region"))
        self.tap_btn.clicked.connect(lambda: self._set_mode("tap"))
        self.capture_btn.clicked.connect(self._capture_asset)
        self.delete_btn.clicked.connect(self._delete_element)
        self.save_btn.clicked.connect(self._save_game)
        
        self.preview.element_selected.connect(self._on_region_selected)
        self.preview.tap_marked.connect(self._on_tap_marked)
    
    def _refresh_games(self):
        self.game_combo.clear()
        for game in self.game_loader.list_games():
            self.game_combo.addItem(game, game)
    
    def _load_game(self):
        game_name = self.game_combo.currentData()
        if game_name:
            self.game_config = self.game_loader.load(game_name)
            self._update_elements_list()
            self._update_overlay()
    
    def _new_game(self):
        name, ok = QInputDialog.getText(self, "New Game", "Game name:")
        if ok and name:
            import os
            game_path = Path("games") / name
            game_path.mkdir(parents=True, exist_ok=True)
            (game_path / "states").mkdir(exist_ok=True)
            (game_path / "assets").mkdir(exist_ok=True)
            
            # Create basic main.yaml
            with open(game_path / "main.yaml", "w") as f:
                f.write(f'name: "{name}"\nversion: "1.0"\ninitial_state: menu\nstates:\n  menu:\n    detect: play_button\n')
            
            self._refresh_games()
            self.game_combo.setCurrentText(name)
            self._load_game()
    
    def _set_mode(self, mode: str):
        self.preview.set_mode(mode)
        self.region_btn.setChecked(mode == "region")
        self.tap_btn.setChecked(mode == "tap")
    
    def _capture_asset(self):
        """Capture current frame as an asset"""
        if not self.game_config:
            return
        
        frame = self.preview._frame
        if frame is None:
            return
        
        name, ok = QInputDialog.getText(self, "Asset Name", "Name for this asset:")
        if ok and name:
            if self.game_loader.save_asset(self.game_config, name, frame):
                self._update_elements_list()
    
    def _on_region_selected(self, name: str, x: int, y: int, w: int, h: int):
        """Handle new region selection"""
        if not self.game_config:
            return
        
        self.game_config.regions[name] = Region(
            name=name, x=x, y=y, width=w, height=h
        )
        self._update_elements_list()
        self._update_overlay()
    
    def _on_tap_marked(self, name: str, x: int, y: int):
        """Handle new tap target"""
        if not self.game_config:
            return
        
        self.game_config.targets[name] = TapTarget(name=name, x=x, y=y)
        self._update_elements_list()
        self._update_overlay()
    
    def _update_elements_list(self):
        """Update elements list widget"""
        self.elements_list.clear()
        
        if not self.game_config:
            return
        
        for name, region in self.game_config.regions.items():
            self.elements_list.addItem(f"📦 {name} ({region.x},{region.y} {region.width}x{region.height})")
        
        for name, target in self.game_config.targets.items():
            self.elements_list.addItem(f"👆 {name} ({target.x},{target.y})")
        
        for asset in self.game_config.assets:
            self.elements_list.addItem(f"🖼️ {asset}")
    
    def _update_overlay(self):
        """Update preview overlay"""
        if not self.game_config:
            return
        
        self.preview.set_overlay_data(
            list(self.game_config.regions.values()),
            list(self.game_config.targets.values())
        )
    
    def _delete_element(self):
        """Delete selected element"""
        item = self.elements_list.currentItem()
        if not item or not self.game_config:
            return
        
        text = item.text()
        name = text.split(" ")[1].split("(")[0].strip()
        
        if text.startswith("📦"):
            if name in self.game_config.regions:
                del self.game_config.regions[name]
        elif text.startswith("👆"):
            if name in self.game_config.targets:
                del self.game_config.targets[name]
        
        self._update_elements_list()
        self._update_overlay()
    
    def _save_game(self):
        """Save game configuration"""
        if not self.game_config:
            return
        
        if self.game_loader.save_locations(self.game_config):
            QMessageBox.information(self, "Saved", "Game configuration saved!")
    
    def update_frame(self, frame: np.ndarray):
        """Update preview with new frame"""
        self.preview.update_frame(frame)
