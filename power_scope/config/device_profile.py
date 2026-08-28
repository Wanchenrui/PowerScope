"""设备配置系统: 通过 YAML 配置文件定义设备界面、变量映射、控制按钮"""
from dataclasses import dataclass, field
from typing import Optional
import yaml
import os


@dataclass
class ControlButton:
    """控制按钮定义"""
    id: str
    label: str
    icon: str = ""
    action: str = ""           # write_var / send_frame / run_script
    target_var: str = ""       # 写入的变量名
    value: any = None          # 写入值
    confirm: bool = False      # 是否需要确认
    color: str = "primary"     # primary/danger/warning/success
    visibility: str = ""       # 条件显示表达式


@dataclass
class StatusIndicator:
    """状态指示器"""
    id: str
    label: str
    var: str                   # 绑定的变量名
    type: str = "led"          # led/text/gauge
    on_value: any = 1          # LED 亮起的值
    color_on: str = "#00FF00"
    color_off: str = "#666666"


@dataclass
class VarBinding:
    """变量绑定"""
    name: str                  # 工具内显示名
    elf_symbol: str            # ELF 符号名
    display_name: str = ""     # 中文显示名
    unit: str = ""             # 单位
    scale: float = 1.0         # 缩放 (寄存器值 × scale = 物理量)
    offset: float = 0.0        # 偏移
    min_val: float = 0.0       # 量程下限
    max_val: float = 100.0     # 量程上限
    precision: int = 2         # 小数位数
    widget: str = "text"       # text/gauge/chart/led/progress
    color: str = "#7aa2f7"
    update_rate: int = 100     # 更新周期 ms


@dataclass
class DashboardWidget:
    """仪表盘组件定义"""
    id: str
    type: str                  # waveform/gauge/led_matrix/button_panel/status_panel/plot
    title: str
    x: int = 0                 # 网格位置
    y: int = 0
    w: int = 4                 # 网格宽度
    h: int = 3                 # 网格高度
    config: dict = field(default_factory=dict)  # 组件特定配置


@dataclass
class DeviceProfile:
    """设备配置文件 — 完整定义一个设备的界面和行为"""
    name: str
    device_type: str           # microinverter / storage / hybrid / custom
    version: str
    description: str = ""

    # 连接配置
    connection: dict = field(default_factory=dict)
    # ELF 文件路径
    elf_file: str = ""
    # Modbus 配置
    modbus: dict = field(default_factory=dict)

    # 变量映射
    variables: list = field(default_factory=list)  # list[VarBinding]

    # 控制按钮组
    control_buttons: list = field(default_factory=list)  # list[ControlButton]

    # 状态指示器
    status_indicators: list = field(default_factory=list)  # list[StatusIndicator]

    # 仪表盘布局
    dashboard: list = field(default_factory=list)  # list[DashboardWidget]

    # 调参页：环路参数映射与安全看门狗配置
    tuning: dict = field(default_factory=dict)

    # 主题
    theme: str = "dark"        # dark/light/solar

    @classmethod
    def from_yaml(cls, path: str) -> "DeviceProfile":
        """从 YAML 文件加载设备配置"""
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        profile = cls(
            name=data.get('name', 'Unknown'),
            device_type=data.get('device_type', 'custom'),
            version=data.get('version', '1.0.0'),
            description=data.get('description', ''),
            connection=data.get('connection', {}),
            elf_file=data.get('elf_file', ''),
            modbus=data.get('modbus', {}),
            tuning=data.get('tuning', {}),
            theme=data.get('theme', 'dark'),
        )

        for vd in data.get('variables', []):
            profile.variables.append(VarBinding(
                name=vd['name'], elf_symbol=vd.get('elf_symbol', vd['name']),
                display_name=vd.get('display_name', vd['name']),
                unit=vd.get('unit', ''), scale=vd.get('scale', 1.0),
                offset=vd.get('offset', 0.0), min_val=vd.get('min', 0.0),
                max_val=vd.get('max', 100.0), precision=vd.get('precision', 2),
                widget=vd.get('widget', 'text'), color=vd.get('color', '#7aa2f7'),
                update_rate=vd.get('update_rate', 100),
            ))

        for bd in data.get('control_buttons', []):
            profile.control_buttons.append(ControlButton(
                id=bd['id'], label=bd['label'], icon=bd.get('icon', ''),
                action=bd.get('action', 'write_var'), target_var=bd.get('target_var', ''),
                value=bd.get('value'), confirm=bd.get('confirm', False),
                color=bd.get('color', 'primary'), visibility=bd.get('visibility', ''),
            ))

        for sd in data.get('status_indicators', []):
            profile.status_indicators.append(StatusIndicator(
                id=sd['id'], label=sd['label'], var=sd['var'],
                type=sd.get('type', 'led'), on_value=sd.get('on_value', 1),
                color_on=sd.get('color_on', '#00FF00'), color_off=sd.get('color_off', '#666666'),
            ))

        for wd in data.get('dashboard', []):
            profile.dashboard.append(DashboardWidget(
                id=wd['id'], type=wd['type'], title=wd.get('title', ''),
                x=wd.get('x', 0), y=wd.get('y', 0), w=wd.get('w', 4), h=wd.get('h', 3),
                config=wd.get('config', {}),
            ))

        return profile

    def to_yaml(self, path: str):
        """保存为 YAML"""
        data = {
            'name': self.name, 'device_type': self.device_type,
            'version': self.version, 'description': self.description,
            'connection': self.connection, 'elf_file': self.elf_file,
            'modbus': self.modbus, 'tuning': self.tuning, 'theme': self.theme,
            'variables': [vars(v) for v in self.variables],
            'control_buttons': [vars(b) for b in self.control_buttons],
            'status_indicators': [vars(s) for s in self.status_indicators],
            'dashboard': [vars(w) for w in self.dashboard],
        }
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    def find_var(self, name: str) -> Optional[VarBinding]:
        for v in self.variables:
            if v.name == name:
                return v
        return None


# 内置设备配置文件目录
BUILTIN_PROFILES_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'profiles')


def list_profiles() -> list:
    """列出所有可用的设备配置文件"""
    profiles = []
    # 内置
    if os.path.isdir(BUILTIN_PROFILES_DIR):
        for f in os.listdir(BUILTIN_PROFILES_DIR):
            if f.endswith('.yaml') or f.endswith('.yml'):
                profiles.append(('builtin', os.path.join(BUILTIN_PROFILES_DIR, f)))
    # 用户自定义 (当前目录 profiles/)
    user_dir = os.path.join(os.getcwd(), 'profiles')
    if os.path.isdir(user_dir):
        for f in os.listdir(user_dir):
            if f.endswith('.yaml') or f.endswith('.yml'):
                path = os.path.join(user_dir, f)
                if path not in [p[1] for p in profiles]:
                    profiles.append(('user', path))
    return profiles


def load_profile(path: str) -> DeviceProfile:
    """加载设备配置文件"""
    return DeviceProfile.from_yaml(path)

