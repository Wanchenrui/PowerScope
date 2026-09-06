"""Independent B2 T10 raw wire and consumer-quality counterexamples."""
from dataclasses import replace
import struct
import pytest
from PySide6.QtCore import QObject, Signal

from power_scope.core.contracts import Quality, SampleBlock, VariableDescriptor
from power_scope.core.debug_service import DebugService, SampleChannel
from power_scope.core.event_bus import EventBus
from power_scope.core.sample_pipeline import typed_view
from power_scope.core.sample_queue import SampleQueue, block_bytes
from power_scope.session.session_controller import SessionController


def crc(data):
    value = 0xffff
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xa001 if value & 1 else 0)
    return value.to_bytes(2, 'little')


def response(command, sequence, payload=b'', status=0):
    raw = bytes.fromhex('a55a01') + bytes([command]) + struct.pack('<HBH', sequence, status, len(payload)) + payload
    return raw + crc(raw)


def stream(sequence, tick, raw, list_id=0):
    header = bytes.fromhex('a55a0110') + struct.pack('<HIBB', sequence, tick, list_id, 1)
    return header + raw + crc(header + raw)


def channel(name='u', dtype='uint64_t', size=8):
    return SampleChannel(name, 0x20000000, size, dtype)


def setup(svc, channels=None, list_id=0):
    seq = svc.setup_sample_list(list_id, 25000, channels or [channel()])
    svc.feed(response(4, seq, bytes.fromhex('a8610000')))


def recorder(capture, sequence, first, raw, width=8):
    header = struct.pack('<IHIIHBBH', capture, sequence, first*width, first, 1, 0, 1, len(raw))
    return response(0x24, 0, header + raw)


def test_review_raw_session_stream_keeps_u64_float_and_units(qapp):
    assert crc(b'123456789') == bytes.fromhex('374b')
    session = SessionController()
    class Source(QObject):
        received = Signal(bytes)
    source = Source()
    session._transport = source
    session._state = 'connected'
    source.received.connect(session._on_ready_read)
    svc = DebugService(session=session, writer=lambda data: len(data))
    # The decoder is real; hardware connection remains a read-only transport seam.
    svc.register_sample_layout(0, [channel(), channel('v', 'double')], period_us=50000)
    raw = bytes.fromhex('fdffffffffffffff000000000000c0bf')
    wire = stream(41, 123456, raw)
    source.received.emit(wire[:7])
    source.received.emit(wire[7:])
    sample = EventBus.instance().samples.queues['plot'].drain()[0]
    assert sample.raw_data == raw
    assert int(typed_view(sample)['c0'][0]) == 18446744073709551613
    assert float(typed_view(sample)['c1'][0]) == -0.125
    assert sample.effective_period_us == 50000 and sample.device_tick == 123456
    assert sample.device_tick_us is None
    assert sample.host_received_ns > 0
    assert not typed_view(sample).flags.writeable


def test_review_stream_zero_sequence_loss_at_wrap_is_visible(qapp):
    svc = DebugService(writer=lambda data: len(data)); setup(svc)
    queue = EventBus.instance().samples.queues['plot']
    svc.feed(stream(65535, 1000, b'\0'*8)); queue.drain()
    # Firmware increments each list's uint16 counter including 0. Missing 0 is loss.
    svc.feed(stream(1, 2000, b'\0'*8))
    block = queue.drain()[0]
    assert 'sequence_gap' in block.quality_flags
    assert block.quality == Quality.GAP


def test_review_stream_sequences_are_per_list(qapp):
    svc = DebugService(writer=lambda data: len(data)); setup(svc); setup(svc, list_id=1)
    queue = EventBus.instance().samples.queues['plot']
    for seq, lid in [(100,0),(7,1),(101,0),(8,1)]:
        svc.feed(stream(seq, seq*100, b'\0'*8, lid))
    assert all('sequence_gap' not in block.quality_flags for block in queue.drain())


@pytest.mark.parametrize("quality",[Quality.INVALID,Quality.UNKNOWN,Quality.STALE])
def test_review_consumer_loss_preserves_invalid_quality(quality):
    desc = VariableDescriptor('u','u',dtype='uint64_t',byte_size=8)
    original = SampleBlock(1,(desc,),b'\0'*8,1,list_id=0,quality=Quality.VALID)
    queue = SampleQueue(block_bytes(original))
    queue.push(original)
    queue.push(replace(original,quality=quality,quality_flags=frozenset({'duplicate'})))
    block = queue.drain()[0]
    assert block.quality == quality
    assert {'duplicate','consumer_drop'} <= block.quality_flags
    assert queue.stats.dropped_samples == 1


def test_review_loss_never_transfers_to_other_list():
    desc = VariableDescriptor('u','u',dtype='uint64_t',byte_size=8)
    a = SampleBlock(1,(desc,),b'\0'*8,1,list_id=0,quality=Quality.VALID)
    queue = SampleQueue(block_bytes(a))
    queue.push(a);queue.push(replace(a,list_id=1))
    assert queue.drain()[0].missing_samples is None
    queue.push(a)
    assert queue.drain()[0].consumer_dropped_samples == 1
    assert queue.stats.peak_bytes <= queue.budget_bytes


def test_review_invalidation_during_first_data_handler_blocks_remaining_handlers(qapp):
    bus = EventBus.instance(); seen=[]
    bus.subscribe('wave/data',lambda _:bus.invalidate_data())
    bus.subscribe('wave/data',seen.append)
    bus.publish('wave/data',b'old');bus.publish('wave/data',b'old2')
    bus._on_flush()
    assert seen == []


def test_review_nack_restores_old_acked_layout_only(qapp):
    svc=DebugService(writer=lambda data:len(data));setup(svc)
    queue=EventBus.instance().samples.queues['plot']
    seq=svc.setup_sample_list(0,10000,[channel('f','float',4)])
    svc.feed(stream(1,100,b'\0'*8))
    assert queue.drain()==[]
    svc.feed(response(255,seq,status=5))
    svc.feed(stream(2,200,bytes.fromhex('ffffffffffffffff')))
    restored=queue.drain()[0]
    assert restored.channels[0].dtype=='uint64_t'
    assert restored.effective_period_us==25000


def test_review_stop_and_clear_reject_old_blocks(qapp):
    svc=DebugService(writer=lambda data:len(data));setup(svc)
    queue=EventBus.instance().samples.queues['plot']
    wire=stream(1,100,b'\0'*8)
    svc.feed(wire)
    svc.stop_stream(0)
    svc.feed(wire)
    assert queue.drain()==[]
    svc.clear_pending();svc.feed(wire)
    assert queue.drain()==[]


def test_review_status_overflow_is_delta_not_recount(qapp):
    svc=DebugService(writer=lambda data:len(data))
    seq=svc.configure_wave([channel()],points=8)
    svc.feed(response(0x20,seq,bytes.fromhex('0b000000190000000800000008000101')))
    for overflow in [3,3,5]:
        seq=svc.get_wave_status()
        status=struct.pack('<BBBBIIIHHIIB',2,1,0,1,11,0,8,8,25,0,overflow,0)
        svc.feed(response(0x22,seq,status))
    queue=EventBus.instance().samples.queues['plot']
    assert queue.stats.device_overflows==5
    assert sum(x.overflow_count or 0 for x in queue.drain())==5


def test_review_oversize_drop_is_not_assigned_to_earlier_queued_block():
    desc=VariableDescriptor('u','u',dtype='uint64_t',byte_size=8)
    earlier=SampleBlock(1,(desc,),b'\0'*8,1,list_id=0,sequence=10,quality=Quality.VALID)
    queue=SampleQueue(block_bytes(earlier))
    queue.push(earlier)
    queue.push(replace(earlier,sequence=11,raw_data=b'\0'*16,sample_count=2))
    emitted=queue.drain()[0]
    assert 'consumer_drop' not in emitted.quality_flags
    queue.push(replace(earlier,sequence=12))
    emitted=queue.drain()[0]
    assert 'consumer_drop' in emitted.quality_flags
    assert queue.stats.dropped_samples==2


def test_review_consumer_drop_does_not_invent_known_device_loss_count():
    desc=VariableDescriptor('u','u',dtype='uint64_t',byte_size=8)
    sample=SampleBlock(1,(desc,),b'\0'*8,1,list_id=0,quality=Quality.GAP,
                       quality_flags=frozenset({'sequence_gap'}),missing_samples=None)
    queue=SampleQueue(block_bytes(sample))
    queue.push(sample);queue.push(sample)
    emitted=queue.drain()[0]
    # Stream sequence gaps carry an unknown number of device samples. A known
    # consumer drop cannot turn that unknown total into precisely one sample.
    assert emitted.missing_samples is None
    assert 'consumer_drop' in emitted.quality_flags
    assert queue.stats.dropped_samples==1


def test_review_live_channels_share_a_block_sequence_and_keep_distinct_sample_tracking(qapp):
    svc=DebugService(writer=lambda data:len(data))
    seq=svc.configure_wave([channel('a'),channel('b')],points=8,mode=2)
    svc.feed(response(0x20,seq,bytes.fromhex('0b000000190000000800000010000102')))
    queue=EventBus.instance().samples.queues['plot'];legacy=[]
    EventBus.instance().subscribe('wave/live_block',legacy.append)
    for sequence,cid,first in [(1,0,0),(1,1,0),(2,0,1),(2,1,1)]:
        raw=bytes.fromhex('ffffffffffffffff')
        inner=bytes([cid,0,0,8,8,0])+raw  # RAW codec, 8-byte scalar
        header=struct.pack('<IHIIHBBH',11,sequence,0,first,1,1,1,len(inner))
        svc.feed(response(0x24,0,header+inner))
    blocks=queue.drain()
    assert len(blocks)==4
    assert all(block.quality==Quality.VALID for block in blocks)
    assert all('sequence_gap' not in block.quality_flags for block in blocks)
    EventBus.instance()._on_flush()
    assert len(legacy)==4


def test_review_recorder_sequence_wrap_does_not_skip_zero(qapp):
    svc=DebugService(writer=lambda data:len(data))
    seq=svc.configure_wave([channel()],points=8)
    svc.feed(response(0x20,seq,bytes.fromhex('0b000000190000000800000008000101')))
    queue=EventBus.instance().samples.queues['plot']
    svc.feed(recorder(11,65535,0,b'\0'*8));queue.drain()
    svc.feed(recorder(11,1,1,b'\0'*8))
    block=queue.drain()[0]
    assert 'sequence_gap' in block.quality_flags


def test_review_evicted_device_gap_remains_unknown_on_next_block():
    desc=VariableDescriptor('u','u',dtype='uint64_t',byte_size=8)
    gap=SampleBlock(1,(desc,),b'\0'*8,1,list_id=0,quality=Quality.GAP,
                    quality_flags=frozenset({'sequence_gap'}),missing_samples=None)
    queue=SampleQueue(block_bytes(gap))
    queue.push(gap)
    queue.push(replace(gap,quality=Quality.VALID,quality_flags=frozenset()))
    emitted=queue.drain()[0]
    assert emitted.missing_samples is None
    assert emitted.consumer_dropped_samples==1


def test_review_absent_missing_count_is_not_assumed_zero():
    desc=VariableDescriptor('u','u',dtype='uint64_t',byte_size=8)
    unknown=SampleBlock(1,(desc,),b'\0'*8,1,list_id=0,quality=Quality.UNKNOWN)
    queue=SampleQueue(block_bytes(unknown))
    queue.push(unknown);queue.push(unknown)
    emitted=queue.drain()[0]
    assert emitted.missing_samples is None
    assert emitted.consumer_dropped_samples==1
