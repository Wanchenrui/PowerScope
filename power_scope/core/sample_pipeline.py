"""Adapt validated Debug stream / Wave v2 payloads without changing wire format."""
import struct
import time
from dataclasses import replace

from .contracts import Quality, SampleBlock, VariableDescriptor


def typed_view(block):
    """Read-only structured NumPy view; unsupported dtypes remain opaque bytes."""
    import numpy as np
    types = {'int8_t': 'i1', 'uint8_t': 'u1', 'int16_t': '<i2',
             'uint16_t': '<u2', 'int32_t': '<i4', 'uint32_t': '<u4',
             'int64_t': '<i8', 'uint64_t': '<u8', 'float': '<f4',
             'double': '<f8', 'bool': '?'}
    fields = []
    for index, channel in enumerate(block.channels):
        dtype = types.get(channel.dtype, f'V{channel.byte_size}')
        if np.dtype(dtype).itemsize != channel.byte_size:
            dtype = f'V{channel.byte_size}'
        fields.append((f'c{index}', dtype))
    return np.frombuffer(block.raw_data, dtype=np.dtype(fields), count=block.sample_count)


def descriptors(channels):
    return tuple(VariableDescriptor(alias=c.name, symbol=c.name, address=c.address,
                 dtype=c.type_name, byte_size=c.size, unit=c.unit,
                 scale=c.scale, offset=c.offset, readable=True) for c in channels)


class SamplePipeline:
    def __init__(self, hub):
        self.hub = hub
        self._streams = {}
        self._wave = None
        self._generation = 0
        self._state = {}
        self._sequences = {}
        self._overflow = 0
        self._restart = False
        self._ticks = {}

    def invalidate(self, reason='restart', list_id=None):
        self._generation += 1
        self.hub.invalidate(list_id)
        if reason == "restart":
            self._restart = True
        if list_id is None:
            self._streams.clear()
            self._wave = None
            self._state.clear()
            self._sequences.clear()
            self._ticks.clear()
        else:
            self._streams.pop(list_id, None)
            self._state.pop(('stream', list_id), None)
            self._sequences.pop(('stream', list_id), None)
            self._ticks.pop(list_id, None)

    def invalidate_wave(self, reason='stop'):
        # Wave blocks have no list ID. Preserve independently active slow streams.
        self._generation += 1
        self._wave = None
        for queue in self.hub.queues.values():
            queue.invalidate_wave()
        self._state = {k: v for k, v in self._state.items() if k[0] == 'stream'}
        self._sequences = {k: v for k, v in self._sequences.items() if k[0] == 'stream'}
        if reason == "restart":
            self._restart = True

    def configure_stream(self, list_id, channels, period_us, epoch=0,
                         build_id=None, device_tick_us=None):
        self.invalidate('layout_changed', list_id)
        self._streams[list_id] = dict(channels=descriptors(channels), epoch=epoch,
            build_id=build_id, effective_period_us=period_us,
            device_tick_us=device_tick_us, layout_generation=self._generation)

    def configure_wave(self, channels, period_us, capture_id, epoch=0,
                       build_id=None, total_points=None):
        self.invalidate_wave('layout_changed')
        self._wave = dict(channels=descriptors(channels), epoch=epoch,
            build_id=build_id, effective_period_us=period_us,
            capture_id=capture_id, layout_generation=self._generation)
        self._total_points = total_points
        self._overflow = 0
        self._recorder_received = 0
        self._capture_gap = False

    def _publish(self, block, key, first=None, modulus=2**32):
        flags = set(block.quality_flags)
        missing = None
        expected = self._state.get(key)
        sequence_key = key
        previous = self._sequences.get(sequence_key)
        invalid = "out_of_order_or_restart" in flags
        if previous is None:
            flags.add("layout_start")
            if self._restart:
                flags.add("restart")
        if previous is not None:
            prev_seq = previous
            delta = (block.sequence - prev_seq) & 0xFFFF
            if delta == 0:
                flags.add('duplicate')
                invalid = True
            elif delta >= 0x8000:
                flags.add('out_of_order_or_restart')
                invalid = True
            elif delta > 1 and not (key[0] == 'live' and prev_seq == 0xFFFF and block.sequence == 1):
                flags.add('sequence_gap')
            if block.sequence < prev_seq and not invalid:
                flags.add('sequence_wrap')
        if first is not None and expected is not None:
            gap = (first - expected) % modulus
            if gap >= modulus // 2:
                flags.add('out_of_order_or_restart')
                invalid = True
            else:
                missing = gap
                if gap:
                    flags.add('sample_gap')
                if first < expected:
                    flags.add('counter_wrap')
        if not invalid:
            expected = None if first is None else first + block.sample_count
            self._state[key] = expected
            self._sequences[sequence_key] = block.sequence
        if invalid:
            quality = Quality.INVALID
        elif flags & {'sequence_gap', 'sample_gap', 'partial_capture', 'device_overflow'}:
            quality = Quality.GAP
        elif flags & {'restart', 'out_of_order_or_restart'}:
            quality = Quality.UNKNOWN
        else:
            quality = Quality.VALID
        block = replace(block, quality=quality, quality_flags=frozenset(flags),
                        missing_samples=missing)
        self.hub.publish(block)
        return block

    def stream(self, frame, list_id, sample_count):
        config = self._streams.get(list_id)
        if config is None:
            return None
        row = sum(c.byte_size for c in config['channels'])
        raw = bytes(frame[12:12 + row * sample_count])
        if len(raw) != row * sample_count or sample_count <= 0:
            return None
        sequence, tick = struct.unpack_from('<HI', frame, 4)
        flags = set()
        previous_tick = self._ticks.get(list_id)
        if previous_tick is not None and tick < previous_tick:
            if (tick - previous_tick) & 0xFFFFFFFF < 0x80000000:
                flags.add('counter_wrap')
            else:
                flags.add('out_of_order_or_restart')
        self._ticks[list_id] = tick
        block = SampleBlock(**config, raw_data=raw, sample_count=sample_count,
            list_id=list_id, sequence=sequence, device_tick=tick, quality_flags=frozenset(flags),
            host_received_ns=time.monotonic_ns())
        # Stream ticks are timestamps, not sample IDs; never infer loss count.
        return self._publish(block, ('stream', list_id))

    def wave(self, block, decoded=None):
        if self._wave is None or block.capture_id != self._wave['capture_id']:
            return None
        config = dict(self._wave)
        flags = set()
        if block.encoding == 1:
            if decoded is None:
                return None
            channel_id = decoded['channel_id']
            config['channels'] = (config['channels'][channel_id],)
            raw = bytes(decoded['raw_bytes'])
            key = ('live', channel_id)
        elif block.encoding == 0:
            raw = bytes(block.data)
            key = ('recorder', block.capture_id)
            if block.offset != block.first_sample_id * sum(c.byte_size for c in config['channels']):
                flags.add('partial_capture')
        else:
            return None
        row = sum(c.byte_size for c in config['channels'])
        if len(raw) != row * block.sample_count:
            return None
        if key not in self._state and block.first_sample_id and block.encoding == 0:
            flags.add('partial_capture')
        sample = SampleBlock(**config, raw_data=raw, sample_count=block.sample_count,
            sequence=block.block_seq, first_sample_id=block.first_sample_id, quality_flags=frozenset(flags),
            host_received_ns=time.monotonic_ns())
        # first_sample_id is an ordinal, not a hardware tick.
        result = self._publish(sample, key, block.first_sample_id)
        if block.encoding == 0 and result.quality != Quality.INVALID:
            self._recorder_received += block.sample_count
            self._capture_gap |= result.quality == Quality.GAP
        return result

    def wave_status(self, status):
        if self._wave is None or status.capture_id != self._wave['capture_id']:
            return
        delta = max(0, status.overflow_count - self._overflow)
        self._overflow = status.overflow_count
        flags = set()
        if delta:
            flags.add('device_overflow')
        if status.state in (3, 5) and status.captured_points < status.total_points:
            flags.add('partial_capture')
        if status.state == 5 and (self._recorder_received < status.captured_points or self._capture_gap):
            flags.add('partial_capture')
        if flags:
            self.hub.publish(SampleBlock(**self._wave, raw_data=b'', sample_count=0,
                host_received_ns=time.monotonic_ns(), overflow_count=delta,
                quality=Quality.GAP, quality_flags=frozenset(flags)))
