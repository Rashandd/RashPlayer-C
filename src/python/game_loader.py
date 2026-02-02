"""
RashPlayer-C: Game Loader
Loads game configuration from directory structure
"""

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
class LogicRule:
    """Decision logic rule for gameplay"""
    condition: str
    action: str
    priority: int = 0
    target: str = ""


@dataclass
class GameState:
    """FSM state definition"""
    name: str
    detect: List[str] = field(default_factory=list)
    action: str = "NONE"
    target: str = ""  # Tap target name for TAP action
    next_state: str = ""
    timeout_ms: int = 0
    on_timeout: str = ""
    workflow: str = ""
    exit_on: List[str] = field(default_factory=list)
    logic: List[LogicRule] = field(default_factory=list)
    polling_hz: int = 60


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
    game_functions: Optional[object] = None  # Loaded game-specific functions module


class GameLoader:
    """Loads game configuration from directory"""
    
    def __init__(self, games_dir: str = None):
        if games_dir is None:
            # Default to project_root/games
            project_root = Path(__file__).parent.parent.parent
            games_dir = project_root / "games"
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
                    target=state_data.get("on_found", {}).get("target", ""),
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
            
            # Load workflow files for states that reference them
            for state_name, state in config.states.items():
                if state.workflow:
                    workflow_path = game_path / state.workflow
                    if workflow_path.exists():
                        try:
                            with open(workflow_path) as f:
                                workflow_data = yaml.safe_load(f)
                            
                            # Update state with workflow data
                            detect = workflow_data.get("detect", [])
                            if isinstance(detect, str):
                                detect = [detect]
                            state.detect = detect
                            state.polling_hz = workflow_data.get("polling_hz", 60)
                            
                            # Parse logic rules
                            for rule_data in workflow_data.get("logic", []):
                                rule = LogicRule(
                                    condition=rule_data.get("condition", "true"),
                                    action=rule_data.get("action", "WAIT"),
                                    priority=rule_data.get("priority", 0),
                                    target=rule_data.get("target", "")
                                )
                                state.logic.append(rule)
                            
                            # Sort logic by priority (highest first)
                            state.logic.sort(key=lambda r: r.priority, reverse=True)
                            
                            print(f"  Loaded workflow for {state_name}: {len(state.logic)} rules")
                        except Exception as e:
                            print(f"  Failed to load workflow {state.workflow}: {e}")
            
            # Load game-specific functions if available
            game_funcs_path = game_path / "game_functions.py"
            
            # Check src directory (new centralized structure)
            if not game_funcs_path.exists():
                project_root = Path(__file__).parent.parent.parent
                central_path = project_root / "src" / "game_functions" / game_name / "game_functions.py"
                if central_path.exists():
                    game_funcs_path = central_path
            
            # Legacy local support
            if not game_funcs_path.exists():
                game_funcs_path = game_path / "src" / "game_functions.py"
            
            if game_funcs_path.exists():
                try:
                    import importlib.util
                    spec = importlib.util.spec_from_file_location(
                        f"{game_name}_functions", 
                        game_funcs_path
                    )
                    game_funcs_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(game_funcs_module)
                    
                    # Create instance if factory function exists
                    if hasattr(game_funcs_module, 'create_game_functions'):
                        # Build config dict for game functions
                        funcs_config = {
                            'colors': {name: {'hsv_low': list(c.hsv_low), 'hsv_high': list(c.hsv_high)} 
                                      for name, c in config.colors.items()},
                            'regions': {name: {'x': r.x, 'y': r.y, 'width': r.width, 'height': r.height}
                                       for name, r in config.regions.items()}
                        }
                        config.game_functions = game_funcs_module.create_game_functions(funcs_config)
                    else:
                        config.game_functions = game_funcs_module
                    
                    print(f"  Loaded game functions from {game_funcs_path.name}")
                except Exception as e:
                    print(f"  Failed to load game functions: {e}")
            
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
