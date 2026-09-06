"""Version 1 consumer contracts; no transport, authorization or UI side effects.

None means unknown, never a permission grant. See protocol-contract-v1.md.
"""
from dataclasses import dataclass
from enum import Enum, IntEnum

SCHEMA_VERSION = 1
RX_PAYLOAD_BYTES = 192
TX_FRAME_BYTES = 192
RESPONSE_OVERHEAD_BYTES = 11
READ_MEMORY_BYTES = TX_FRAME_BYTES - RESPONSE_OVERHEAD_BYTES
BATCH_ITEMS = 16
SAMPLE_ITEMS = 16
SAMPLE_ROW_BYTES = 64


class TypeSource(str, Enum):
    UNKNOWN = "unknown"
    DWARF = "dwarf"
    DEVICE_PACK = "device_pack"


class Quality(str, Enum):
    UNKNOWN = "unknown"
    VALID = "valid"
    STALE = "stale"
    GAP = "gap"
    INVALID = "invalid"


class CommandPhase(str, Enum):
    UNKNOWN = "unknown"
    SENT = "sent"
    ACKED = "acked"
    VERIFIED = "verified"
    REJECTED = "rejected"


class EffectState(str, Enum):
    UNKNOWN = "unknown"
    INACTIVE = "inactive"
    CONFIRMED = "confirmed"


class DebugStatus(IntEnum):
    OK = 0
    CRC = 1
    COMMAND = 2
    ADDRESS = 3
    LENGTH = 4
    BUSY = 5
    PROTECTED = 6
    LIST_FULL = 7


@dataclass(frozen=True)
class DeviceIdentity:
    family: str | None = None
    build_id: bytes | None = None
    protocol_version: int | None = None
    manifest_sha256: str | None = None
    artifacts_verified: bool = False


@dataclass(frozen=True)
class Capabilities:
    supported_commands: frozenset[int] = frozenset()
    rx_payload_bytes: int | None = None
    tx_frame_bytes: int | None = None
    read_memory_bytes: int | None = None
    batch_items: int | None = None
    sample_lists: int | None = None
    sample_items: int | None = None
    sample_row_bytes: int | None = None
    min_sample_period_us: int | None = None
    wave_buffer_bytes: int | None = None
    device_tick_us: int | None = None


@dataclass(frozen=True)
class VariableDescriptor:
    alias: str
    symbol: str
    address: int | None = None
    dtype: str | None = None
    byte_size: int | None = None
    unit: str | None = None
    scale: float = 1.0
    offset: float = 0.0
    type_source: TypeSource = TypeSource.UNKNOWN
    readable: bool = False
    writable: bool = False


@dataclass(frozen=True)
class ParameterDescriptor(VariableDescriptor):
    write_range: tuple[float, float] | None = None
    allowed_modes: frozenset[str] = frozenset()
    control_period_us: int | None = None
    coefficient_definition: str | None = None
    effect_condition: str | None = None
    tuning_verified: bool = False


@dataclass(frozen=True)
class Observation:
    alias: str
    epoch: int
    raw_value: int | float | bool | None = None
    host_received_ns: int | None = None
    device_tick: int | None = None
    device_tick_us: int | None = None
    quality: Quality = Quality.UNKNOWN


@dataclass(frozen=True)
class SampleBlock:
    epoch: int
    channels: tuple[VariableDescriptor, ...]
    raw_data: bytes
    sample_count: int
    build_id: bytes | None = None
    list_id: int | None = None
    capture_id: int | None = None
    sequence: int | None = None
    device_tick: int | None = None
    device_tick_us: int | None = None
    host_received_ns: int | None = None
    effective_period_us: int | None = None
    missing_samples: int | None = None
    overflow_count: int | None = None
    quality: Quality = Quality.UNKNOWN


@dataclass(frozen=True)
class CommandIntent:
    intent_id: str
    epoch: int
    target_alias: str
    operation: str
    deadline_ns: int
    requested_value: int | float | bool | None = None
    encoded_value: bytes | None = None
    required_state: str | None = None


@dataclass(frozen=True)
class CommandReceipt:
    intent_id: str
    epoch: int
    phase: CommandPhase = CommandPhase.UNKNOWN
    evidence: str = ""
    wire_sequence: int | None = None
    status: int | None = None
    observed_value: int | float | bool | None = None
    effect: EffectState = EffectState.UNKNOWN
    effect_evidence: str = ""


def require_read_memory_length(length: int) -> None:
    """Conservative consumer boundary, including unpatched legacy firmware."""
    if type(length) is not int or not 1 <= length <= READ_MEMORY_BYTES:
        raise ValueError("ReadMemory length must be 1..181 bytes")
