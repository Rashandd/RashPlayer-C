"""
RashPlayer-C: Scanner Widget
Interactive tool for defining screen elements with detection overlay
"""

import numpy as np
from pathlib import Path
from typing import Optional, Tuple
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QComboBox, QGroupBox, QListWidget, QListWidgetItem,
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
        
        # Rendering state
        self._target_rect = QRect()
        self._scale_x = 1.0
        self._scale_y = 1.0
        
        # Overlay data
        self._regions: list = []
        self._targets: list = []
        self._current_state = "IDLE"
        
        self.setMouseTracking(True)
        self.setMinimumSize(200, 200)
    
    def _update_geometry(self):
        """Calculate display geometry to maintain aspect ratio"""
        if self._frame is None:
            self._target_rect = self.rect()
            return

        w_w = self.width()
        w_h = self.height()
        f_w = self._frame_width
        f_h = self._frame_height
        
        if f_w <= 0 or f_h <= 0:
            return

        w_ratio = w_w / w_h
        f_ratio = f_w / f_h
        
        if f_ratio > w_ratio:
            # Frame is wider than widget
            d_w = w_w
            d_h = int(w_w / f_ratio)
        else:
            # Frame is taller than widget
            d_h = w_h
            d_w = int(w_h * f_ratio)
            
        x = (w_w - d_w) // 2
        y = (w_h - d_h) // 2
        
        self._target_rect = QRect(x, y, d_w, d_h)
        self._scale_x = d_w / f_w
        self._scale_y = d_h / f_h

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_geometry()
    
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
        self._update_geometry()
        self.update()
    
    def set_overlay_data(self, regions: list, targets: list):
        """Set regions and targets to draw"""
        self._regions = regions
        self._targets = targets
        self.update()
    
    def _widget_to_frame(self, pos: QPoint) -> Tuple[int, int]:
        """Convert widget coordinates to frame coordinates"""
        if self._scale_x == 0 or self._scale_y == 0:
            return 0, 0
        fx = int((pos.x() - self._target_rect.x()) / self._scale_x)
        fy = int((pos.y() - self._target_rect.y()) / self._scale_y)
        return max(0, min(self._frame_width, fx)), max(0, min(self._frame_height, fy))
    
    def _frame_to_widget(self, x: int, y: int) -> Tuple[int, int]:
        """Convert frame coordinates to widget coordinates"""
        wx = int(x * self._scale_x + self._target_rect.x())
        wy = int(y * self._scale_y + self._target_rect.y())
        return wx, wy
    
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
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            
            # Draw frame
            if self._frame is not None:
                from PySide6.QtGui import QImage, QPixmap
                h, w = self._frame.shape[:2]
                fmt = QImage.Format_RGBA8888 if self._frame.shape[2] == 4 else QImage.Format_RGB888
                qimg = QImage(self._frame.data, w, h, self._frame.strides[0], fmt)
                pixmap = QPixmap.fromImage(qimg)
                painter.drawPixmap(self._target_rect, pixmap)
            else:
                painter.fillRect(self.rect(), QColor(30, 30, 30))
            
            # Draw regions (green boxes)
            for region in self._regions:
                wx, wy = self._frame_to_widget(region.x, region.y)
                ww = int(region.width * self._scale_x)
                wh = int(region.height * self._scale_y)
                
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
        main_layout = QHBoxLayout(self)
        
        # Left Panel (Controls)
        sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        
        # Game selector
        game_group = QGroupBox("Game Management")
        game_layout = QVBoxLayout(game_group)
        
        combo_layout = QHBoxLayout()
        self.game_combo = QComboBox()
        self.game_combo.setMinimumWidth(150)
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setFixedWidth(30)
        combo_layout.addWidget(self.game_combo)
        combo_layout.addWidget(self.refresh_btn)
        game_layout.addLayout(combo_layout)
        
        btn_layout = QHBoxLayout()
        self.load_btn = QPushButton("📂 Load")
        self.new_btn = QPushButton("✨ New")
        btn_layout.addWidget(self.load_btn)
        btn_layout.addWidget(self.new_btn)
        game_layout.addLayout(btn_layout)
        sidebar_layout.addWidget(game_group)
        
        # Mode buttons
        mode_group = QGroupBox("Tools")
        mode_layout = QVBoxLayout(mode_group)
        self.region_btn = QPushButton("📦 Define Region")
        self.region_btn.setCheckable(True)
        self.region_btn.setChecked(True)
        self.tap_btn = QPushButton("👆 Mark Tap Target")
        self.tap_btn.setCheckable(True)
        mode_layout.addWidget(self.region_btn)
        mode_layout.addWidget(self.tap_btn)
        sidebar_layout.addWidget(mode_group)
        
        # Elements list
        elements_group = QGroupBox("Elements")
        elements_layout = QVBoxLayout(elements_group)
        self.elements_list = QListWidget()
        elements_layout.addWidget(self.elements_list)
        
        elem_btn_layout = QHBoxLayout()
        self.delete_btn = QPushButton("🗑️ Delete")
        self.save_btn = QPushButton("💾 Save Config")
        elem_btn_layout.addWidget(self.delete_btn)
        elem_btn_layout.addWidget(self.save_btn)
        elements_layout.addLayout(elem_btn_layout)
        sidebar_layout.addWidget(elements_group)
        sidebar_layout.addStretch()
        
        # Add splitter
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(sidebar_widget)
        
        # Right side: Preview
        self.preview_container = QFrame()
        self.preview_container.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        preview_layout = QVBoxLayout(self.preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        
        self.preview = ScannerPreview()
        preview_layout.addWidget(self.preview)
        
        self.splitter.addWidget(self.preview_container)
        self.splitter.setStretchFactor(1, 4)
        
        main_layout.addWidget(self.splitter)
    
    def _connect_signals(self):
        self.load_btn.clicked.connect(self._load_game)
        self.new_btn.clicked.connect(self._new_game)
        self.refresh_btn.clicked.connect(self._refresh_games)
        self.region_btn.clicked.connect(lambda: self._set_mode("region"))
        self.tap_btn.clicked.connect(lambda: self._set_mode("tap"))
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
            item = QListWidgetItem(f"📦 {name} ({region.x},{region.y} {region.width}x{region.height})")
            item.setData(Qt.UserRole, {"type": "region", "name": name})
            self.elements_list.addItem(item)
        
        for name, target in self.game_config.targets.items():
            item = QListWidgetItem(f"👆 {name} ({target.x},{target.y})")
            item.setData(Qt.UserRole, {"type": "target", "name": name})
            self.elements_list.addItem(item)
        
        for asset in self.game_config.assets:
            item = QListWidgetItem(f"🖼️ {asset}")
            item.setData(Qt.UserRole, {"type": "asset", "name": asset})
            self.elements_list.addItem(item)
    
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
        
        data = item.data(Qt.UserRole)
        if not data:
            return
            
        name = data["name"]
        item_type = data["type"]
        
        if item_type == "region":
            if name in self.game_config.regions:
                del self.game_config.regions[name]
        elif item_type == "target":
            if name in self.game_config.targets:
                del self.game_config.targets[name]
        elif item_type == "asset":
            if name in self.game_config.assets:
                self.game_config.assets.remove(name)
        
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
