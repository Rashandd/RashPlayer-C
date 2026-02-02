"""
RashPlayer-C: YAML Parser
Loads game workflows from YAML files and primes the C-Brain
"""

import yaml
import ctypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
from enum import IntEnum


class TriggerType(IntEnum):
    TEMPLATE_MATCH = 0
    COLOR_MATCH = 1
    EDGE_DETECT = 2
    OCR_REGION = 3


class ActionType(IntEnum):
    NONE = 0
    TAP = 1
    SWIPE = 2
    LONG_PRESS = 3
    DRAG = 4
    WAIT = 5


@dataclass
class VisualTrigger:
    id: int
    name: str
    trigger_type: TriggerType
    region: tuple[int, int, int, int] = (0, 0, 0, 0)
    template_path: Optional[str] = None
    color_hsv: Optional[tuple[int, int, int]] = None
    threshold: float = 0.85
    edge_horizontal: bool = True


@dataclass
class DecisionRule:
    condition: str
    action: ActionType
    target: tuple[int, int] = (0, 0)
    priority: int = 0


@dataclass
class WorkflowConfig:
    name: str
    version: str = "1.0"
    polling_hz: int = 60
    triggers: list[VisualTrigger] = field(default_factory=list)
    rules: list[DecisionRule] = field(default_factory=list)
    assets_dir: Optional[Path] = None


class YAMLParser:
    """Parses YAML workflow files"""
    
    @staticmethod
    def load(filepath: str | Path) -> WorkflowConfig:
        """Load a workflow from a YAML file"""
        path = Path(filepath)
        
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        
        config = WorkflowConfig(
            name=data.get('name', path.stem),
            version=data.get('version', '1.0'),
            polling_hz=data.get('polling_hz', 60),
            assets_dir=path.parent / 'assets'
        )
        
        # Parse visual triggers
        trigger_id = 1
        for name, trigger_data in data.get('visual_triggers', {}).items():
            trigger = YAMLParser._parse_trigger(trigger_id, name, trigger_data)
            if trigger:
                config.triggers.append(trigger)
                trigger_id += 1
        
        # Parse decision rules
        priority = len(data.get('decision_logic', []))
        for rule_data in data.get('decision_logic', []):
            rule = YAMLParser._parse_rule(rule_data, priority)
            if rule:
                config.rules.append(rule)
                priority -= 1
        
        return config
    
    @staticmethod
    def _parse_trigger(trigger_id: int, name: str, data: dict) -> Optional[VisualTrigger]:
        """Parse a single trigger definition"""
        trigger_type_str = data.get('type', 'template_match')
        
        trigger_type_map = {
            'template_match': TriggerType.TEMPLATE_MATCH,
            'color_match': TriggerType.COLOR_MATCH,
            'color_edge': TriggerType.EDGE_DETECT,
            'edge_detect': TriggerType.EDGE_DETECT,
            'ocr': TriggerType.OCR_REGION
        }
        
        trigger_type = trigger_type_map.get(trigger_type_str, TriggerType.TEMPLATE_MATCH)
        
        region = (0, 0, 0, 0)
        if 'region' in data:
            r = data['region']
            region = (r.get('x', 0), r.get('y', 0),
                      r.get('width', 0), r.get('height', 0))
        
        return VisualTrigger(
            id=trigger_id,
            name=name,
            trigger_type=trigger_type,
            region=region,
            template_path=data.get('image'),
            color_hsv=tuple(data.get('color_hsv', [0, 0, 0])) if 'color_hsv' in data else None,
            threshold=data.get('threshold', 0.85),
            edge_horizontal=data.get('edge_direction', 'horizontal') == 'horizontal'
        )
    
    @staticmethod
    def _parse_rule(data: dict, priority: int) -> Optional[DecisionRule]:
        """Parse a single decision rule"""
        condition = data.get('condition', '')
        action_str = data.get('action', 'NONE').upper()
        
        action_map = {
            'NONE': ActionType.NONE,
            'TAP': ActionType.TAP,
            'SWIPE': ActionType.SWIPE,
            'LONG_PRESS': ActionType.LONG_PRESS,
            'DRAG': ActionType.DRAG,
            'WAIT': ActionType.WAIT
        }
        
        action = action_map.get(action_str, ActionType.NONE)
        
        target = (0, 0)
        if 'target' in data:
            t = data['target']
            target = (t.get('x', 0), t.get('y', 0))
        
        return DecisionRule(
            condition=condition,
            action=action,
            target=target,
            priority=priority
        )


# C-compatible structures for ctypes bridge
class CPoint2D(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int32),
        ("y", ctypes.c_int32)
    ]


class CRect2D(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int32),
        ("y", ctypes.c_int32),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32)
    ]


class CColorHSV(ctypes.Structure):
    _fields_ = [
        ("h", ctypes.c_uint8),
        ("s", ctypes.c_uint8),
        ("v", ctypes.c_uint8)
    ]


class CDecisionRule(ctypes.Structure):
    _fields_ = [
        ("condition", ctypes.c_char * 256),
        ("action", ctypes.c_int),
        ("action_target", CPoint2D),
        ("priority", ctypes.c_int32)
    ]


class BrainPrimer:
    """Primes the C-Brain with workflow configuration via ctypes"""
    
    def __init__(self, lib_path: str = "./build/librashplayer.so"):
        self.lib = ctypes.CDLL(lib_path)
        self._setup_functions()
    
    def _setup_functions(self):
        """Setup ctypes function signatures"""
        # brain_init
        self.lib.brain_init.restype = ctypes.c_int
        self.lib.brain_init.argtypes = []
        
        # brain_load_rules
        self.lib.brain_load_rules.restype = ctypes.c_int
        self.lib.brain_load_rules.argtypes = [
            ctypes.POINTER(CDecisionRule),
            ctypes.c_int
        ]
    
    def prime(self, config: WorkflowConfig) -> bool:
        """Load workflow configuration into C-Brain"""
        # Initialize brain
        if self.lib.brain_init() != 0:
            return False
        
        # Convert rules to C format
        if config.rules:
            c_rules = (CDecisionRule * len(config.rules))()
            
            for i, rule in enumerate(config.rules):
                c_rules[i].condition = rule.condition.encode('utf-8')[:255]
                c_rules[i].action = int(rule.action)
                c_rules[i].action_target.x = rule.target[0]
                c_rules[i].action_target.y = rule.target[1]
                c_rules[i].priority = rule.priority
            
            if self.lib.brain_load_rules(c_rules, len(config.rules)) != 0:
                return False
        
        return True
