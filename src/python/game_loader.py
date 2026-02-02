"""
RashPlayer-C: Game Loader
Loads game configuration from directory structure
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import yaml


@dataclass
class TapTarget:
    """Tap target location"""
    name: str
    x: int
    y: int
    description: str = ""


@dataclass
class Region:
    """Screen region for detection"""
    name: str
    x: int
    y: int
    width: int
    height: int
    description: str = ""
    
    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


@dataclass
class ColorRange:
    """HSV color range"""
    name: str
    hsv_low: Tuple[int, int, int]
    hsv_high: Tuple[int, int, int]
    description: str = ""


@dataclass
class GameState:
    """FSM state definition"""
    name: str
    detect: List[str] = field(default_factory=list)
    action: str = "NONE"
    next_state: str = ""
    timeout_ms: int = 0
    on_timeout: str = ""
    workflow: str = ""
    exit_on: List[str] = field(default_factory=list)


@dataclass
class GameConfig:
    """Complete game configuration"""
    name: str
    version: str
    path: Path
    initial_state: str
    polling_hz: int
    screen_width: int
    screen_height: int
    states: Dict[str, GameState] = field(default_factory=dict)
    targets: Dict[str, TapTarget] = field(default_factory=dict)
    regions: Dict[str, Region] = field(default_factory=dict)
    colors: Dict[str, ColorRange] = field(default_factory=dict)
    assets: List[str] = field(default_factory=list)


class GameLoader:
    """Loads game configuration from directory"""
    
    def __init__(self, games_dir: str = "games"):
        self.games_dir = Path(games_dir)
    
    def list_games(self) -> List[str]:
        """List available games"""
        if not self.games_dir.exists():
            return []
        return [d.name for d in self.games_dir.iterdir() if d.is_dir()]
    
    def load(self, game_name: str) -> Optional[GameConfig]:
        """Load game configuration"""
        game_path = self.games_dir / game_name
        
        if not game_path.exists():
            print(f"Game not found: {game_name}")
            return None
        
        main_yaml = game_path / "main.yaml"
        if not main_yaml.exists():
            print(f"main.yaml not found in {game_name}")
            return None
        
        try:
            # Load main config
            with open(main_yaml) as f:
                main = yaml.safe_load(f)
            
            config = GameConfig(
                name=main.get("name", game_name),
                version=main.get("version", "1.0"),
                path=game_path,
                initial_state=main.get("initial_state", "menu"),
                polling_hz=main.get("polling_hz", 60),
                screen_width=main.get("screen", {}).get("width", 1080),
                screen_height=main.get("screen", {}).get("height", 2400)
            )
            
            # Load states
            for state_name, state_data in main.get("states", {}).items():
                detect = state_data.get("detect", [])
                if isinstance(detect, str):
                    detect = [detect]
                
                config.states[state_name] = GameState(
                    name=state_name,
                    detect=detect,
                    action=state_data.get("on_found", {}).get("action", "NONE"),
                    next_state=state_data.get("on_found", {}).get("next_state", ""),
                    timeout_ms=state_data.get("timeout_ms", 0),
                    on_timeout=state_data.get("on_timeout", ""),
                    workflow=state_data.get("workflow", ""),
                    exit_on=state_data.get("exit_on", [])
                )
            
            # Load locations
            locations_yaml = game_path / "locations.yaml"
            if locations_yaml.exists():
                with open(locations_yaml) as f:
                    locations = yaml.safe_load(f)
                
                for name, data in locations.get("targets", {}).items():
                    config.targets[name] = TapTarget(
                        name=name,
                        x=data.get("x", 0),
                        y=data.get("y", 0),
                        description=data.get("description", "")
                    )
                
                for name, data in locations.get("regions", {}).items():
                    config.regions[name] = Region(
                        name=name,
                        x=data.get("x", 0),
                        y=data.get("y", 0),
                        width=data.get("width", 100),
                        height=data.get("height", 100),
                        description=data.get("description", "")
                    )
            
            # Load colors
            colors_yaml = game_path / "colors.yaml"
            if colors_yaml.exists():
                with open(colors_yaml) as f:
                    colors = yaml.safe_load(f)
                
                for name, data in colors.get("colors", {}).items():
                    config.colors[name] = ColorRange(
                        name=name,
                        hsv_low=tuple(data.get("hsv_low", [0, 0, 0])),
                        hsv_high=tuple(data.get("hsv_high", [180, 255, 255])),
                        description=data.get("description", "")
                    )
            
            # List assets
            assets_dir = game_path / "assets"
            if assets_dir.exists():
                config.assets = [f.name for f in assets_dir.iterdir() if f.is_file()]
            
            print(f"Loaded game: {config.name} v{config.version}")
            print(f"  States: {list(config.states.keys())}")
            print(f"  Targets: {list(config.targets.keys())}")
            print(f"  Regions: {list(config.regions.keys())}")
            print(f"  Colors: {list(config.colors.keys())}")
            print(f"  Assets: {config.assets}")
            
            return config
            
        except Exception as e:
            print(f"Error loading game: {e}")
            return None
    
    def save_locations(self, config: GameConfig) -> bool:
        """Save locations.yaml"""
        try:
            data = {
                "targets": {},
                "regions": {}
            }
            
            for name, target in config.targets.items():
                data["targets"][name] = {
                    "x": target.x,
                    "y": target.y,
                    "description": target.description
                }
            
            for name, region in config.regions.items():
                data["regions"][name] = {
                    "x": region.x,
                    "y": region.y,
                    "width": region.width,
                    "height": region.height,
                    "description": region.description
                }
            
            with open(config.path / "locations.yaml", "w") as f:
                yaml.dump(data, f, default_flow_style=False)
            
            return True
        except Exception as e:
            print(f"Error saving locations: {e}")
            return False
    
    def save_asset(self, config: GameConfig, name: str, image_data) -> bool:
        """Save asset image"""
        try:
            from PIL import Image
            import numpy as np
            
            assets_dir = config.path / "assets"
            assets_dir.mkdir(exist_ok=True)
            
            if isinstance(image_data, np.ndarray):
                img = Image.fromarray(image_data)
            else:
                img = image_data
            
            path = assets_dir / f"{name}.png"
            img.save(path)
            
            if name not in config.assets:
                config.assets.append(f"{name}.png")
            
            return True
        except Exception as e:
            print(f"Error saving asset: {e}")
            return False
