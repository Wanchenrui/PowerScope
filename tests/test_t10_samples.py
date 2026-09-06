import struct
from dataclasses import replace
from types import SimpleNamespace

from power_scope.core.contracts import Quality, SampleBlock, VariableDescriptor
from power_scope.core.debug_service import SampleChannel, WaveDataBlock
from power_scope.core.event_bus import EventBus, VarUpdatedEvent
from power_scope.core.sample_pipeline import SamplePipeline, typed_view
from power_scope.core.sample_queue import SampleHub, SampleQueue, block_bytes


def channel():
    return SampleChannel('count', 0x20000000, 8, 'uint64_t')


def raw_block(list_id=0, value=2**64 - 3):
    return SampleBlock(1, (VariableDescriptor('count', 'count', dtype='uint64_t', byte_size=8),),
                       struct.pack('<Q', value), 1, list_id=list_id, quality=Quality.VALID)


def test_consumers_have_independent_byte_budgets_and_loss():
    hub = SampleHub()
    small = hub.subscribe('small', block_bytes(raw_block()) * 2)
    fast = hub.subscribe('fast', 10000)
    for _ in range(10):
        hub.publish(raw_block())
        assert len(fast.drain()) == 1
    assert small.stats.dropped_blocks == 8
    assert small.stats.queued_bytes <= small.budget_bytes
    dropped = small.drain()[0]
    assert dropped.consumer_dropped_samples == 8
    assert dropped.missing_samples is None
    assert fast.stats.dropped_blocks == 0


def test_loss_does_not_cross_streams_and_invalidation_preserves_other_loss():
    a, b = raw_block(0), raw_block(1)
    queue = SampleQueue(block_bytes(a))
    queue.push(a)
    queue.push(b)
    assert queue.drain()[0].missing_samples is None
    queue.push(a)
    queue.push(b)
    queue.invalidate(1)
    queue.push(a)
    assert queue.drain()[0].consumer_dropped_samples == 2


def test_oversize_visible_and_no_retained_payload():
    queue = SampleQueue(1)
    queue.push(raw_block())
    assert queue.stats.dropped_samples == 1
    assert queue.stats.queued_bytes == 0


def test_raw_precision_and_read_only_typed_views():
    block = raw_block()
    assert typed_view(block)['c0'][0] == 2**64 - 3
    assert not typed_view(block).flags.writeable
    block = replace(block, channels=(VariableDescriptor('v', 'v', dtype='double', byte_size=8),),
                    raw_data=struct.pack('<d', -0.123456789))
    assert typed_view(block)['c0'][0] == -0.123456789


def test_stream_metadata_wrap_gap_restart():
    pipe = SamplePipeline(SampleHub())
    pipe.configure_stream(0, [channel()], 25000, epoch=7, build_id=b'id', device_tick_us=1)
    def feed(seq, tick):
        return pipe.stream(b'\0' * 4 + struct.pack('<HI', seq, tick) + b'\0\1' + struct.pack('<Q', 2**64-1), 0, 1)
    first = feed(65535, 0xFFFFFF00)
    assert first.epoch == 7 and first.build_id == b'id'
    assert first.device_tick_us == 1 and first.effective_period_us == 25000
    assert first.host_received_ns > 0
    wrapped = feed(1, 500)
    assert {'sequence_wrap', 'counter_wrap'} <= wrapped.quality_flags
    assert feed(3, 1000).quality == Quality.GAP
    assert feed(3, 1000).quality == Quality.INVALID
    assert feed(4, 2).quality == Quality.INVALID
    pipe.invalidate()
    assert feed(5, 3000) is None
    pipe.configure_stream(0, [channel()], 50000, epoch=8)
    restarted = feed(1, 0)
    assert 'restart' in restarted.quality_flags and restarted.device_tick_us is None


def test_live_and_recorder_gaps_partial_overflow():
    hub = SampleHub()
    pipe = SamplePipeline(hub)
    pipe.configure_wave([channel()], 25, 9, total_points=20)
    def feed(seq, first):
        return pipe.wave(WaveDataBlock(9, seq, first*8, first, 1, 0, 1, struct.pack('<Q', 2**63)))
    assert 'partial_capture' in feed(1, 3).quality_flags
    assert feed(2, 6).missing_samples == 2
    assert feed(2, 6).quality == Quality.INVALID
    assert feed(1, 4).quality == Quality.INVALID
    status = SimpleNamespace(capture_id=9, overflow_count=3, state=5, captured_points=10, total_points=20)
    pipe.wave_status(status)
    pipe.wave_status(status)
    assert hub.queues['plot'].stats.device_overflows == 3
    pipe.configure_wave([channel()], 50, 10)
    assert feed(3, 7) is None
    decoded = {'channel_id': 0, 'raw_bytes': struct.pack('<Q', 2**64-1)}
    sample = pipe.wave(WaveDataBlock(10, 1, 0, 0xFFFFFFFF, 1, 1, 1, b''), decoded)
    assert sample.device_tick is None and sample.first_sample_id == 0xFFFFFFFF
    assert sample.raw_data == decoded['raw_bytes']
    sample = pipe.wave(WaveDataBlock(10, 2, 0, 0, 1, 1, 1, b''), decoded)
    assert 'counter_wrap' in sample.quality_flags


def test_compatibility_events_bounded_and_low_events_separate(qapp):
    bus = EventBus.instance()
    bus.data_budget_bytes = 2048
    seen = []
    bus.subscribe('control/status', seen.append)
    for i in range(100):
        bus.publish('var/updated', VarUpdatedEvent('v', i, float(i), 'V', 0))
    bus.publish('control/status', 'ack')
    assert bus.data_stats['queued_bytes'] <= 2048
    assert bus.data_stats['dropped_events'] > 0
    assert len(bus._pending) == 1
    bus._on_flush()
    assert seen == ['ack']
    bus.data_budget_bytes = 2 * 1024 * 1024


def test_invalidation_in_status_callback_discards_detached_data(qapp):
    bus = EventBus.instance()
    seen = []
    bus.subscribe('var/updated', seen.append)
    bus.subscribe('layout/changed', lambda _: bus.invalidate_data())
    bus.publish('var/updated', 'old')
    bus.publish('layout/changed', None)
    bus._on_flush()
    assert seen == []


def test_live_group_channels_share_sequence_but_not_sample_ids():
    pipe = SamplePipeline(SampleHub())
    pipe.configure_wave([channel(), replace(channel(), name='other')], 25, 8)
    for seq, cid, first in [(1, 0, 0), (1, 1, 0), (2, 0, 1), (2, 1, 1)]:
        sample = pipe.wave(WaveDataBlock(8, seq, 0, first, 1, 1, 1, b''),
                          {'channel_id': cid, 'raw_bytes': b'\0'*8})
        assert sample.quality == Quality.VALID
        assert 'sequence_gap' not in sample.quality_flags


def test_real_debug_stream_ack_decode_reconfigure_and_stop(qapp):
    from power_scope.core.debug_service import DebugService
    from power_scope.core.cffi_loader import DebugProtocol
    svc = DebugService(writer=lambda _: None)
    plot = EventBus.instance().samples.queues['plot']
    raw = struct.pack('<Q', 2**64-1)
    frame = DebugProtocol.build_stream_frame(seq=1, timestamp=400, list_id=0, sample_count=1, data=raw)
    seq = svc.setup_sample_list(0, 2000, [channel()])
    svc.feed(frame)
    assert plot.drain() == []
    svc.feed(DebugProtocol.build_response(DebugProtocol.CMD_SET_SAMPLE, seq, 0, struct.pack('<I', 3000)))
    svc.feed(frame[:8])
    svc.feed(frame[8:])
    block = plot.drain()[0]
    assert block.raw_data == raw and block.effective_period_us == 3000
    assert block.device_tick == 400 and block.device_tick_us is None
    svc.stop_stream(0)
    svc.feed(frame)
    assert plot.drain() == []


def test_real_debug_live_and_recorder_feed_preserve_bytes(qapp):
    from power_scope.core.debug_service import DebugService, WAVE_MODE_LIVE
    from power_scope.core.cffi_loader import DebugProtocol
    from power_scope.core.wave_codec import encode_channel
    svc = DebugService(writer=lambda _: None)
    hub = EventBus.instance().samples
    seq = svc.configure_wave([channel()], points=4, mode=WAVE_MODE_LIVE)
    svc.feed(DebugProtocol.build_response(svc.CMD_WAVE_CONFIG, seq, 0,
             struct.pack('<IIIHBB', 11, 25, 4, 8, 1, 1)))
    raw = struct.pack('<2Q', 2**64-1, 2**63+1)
    encoded = encode_channel(raw, 8, type_code=8)
    data = struct.pack('<BBBBH', 0, encoded.codec_id, encoded.parameter, 8, len(encoded.payload)) + encoded.payload
    payload = struct.pack('<IHIIHBBH', 11, 1, 0, 0, 2, 1, 1, len(data)) + data
    svc.feed(DebugProtocol.build_response(svc.CMD_WAVE_DATA, 0, 0, payload))
    live = hub.queues['plot'].drain()[0]
    assert live.raw_data == raw
    assert hub.queues['recorder'].drain()[0] == live
    seq = svc.configure_wave([channel()], points=4)
    svc.feed(DebugProtocol.build_response(svc.CMD_WAVE_CONFIG, seq, 0,
             struct.pack('<IIIHBB', 12, 25, 4, 8, 1, 1)))
    payload = struct.pack('<IHIIHBBH', 12, 1, 0, 0, 2, 0, 1, len(raw)) + raw
    svc.feed(DebugProtocol.build_response(svc.CMD_WAVE_DATA, 0, 0, payload))
    assert hub.queues['plot'].drain()[0].raw_data == raw


def test_session_dual_parser_wave_copies_stay_bounded(qapp):
    from PySide6.QtCore import QObject, Signal
    from power_scope.session.session_controller import SessionController
    from power_scope.core.debug_service import DebugService
    from power_scope.core.cffi_loader import DebugProtocol
    bus = EventBus.instance()
    session = SessionController()
    class TransportSource(QObject):
        ready_read = Signal(bytes)
    source = TransportSource()
    session._transport = source
    session._state = 'connected'
    source.ready_read.connect(session._on_ready_read)
    svc = DebugService(session=session, writer=lambda _: None)
    svc.samples.configure_wave([channel()], 25, 1)
    bus.data_budget_bytes = 8192
    for seq in range(1, 401):
        payload = struct.pack('<IHIIHBBH', 1, seq, (seq-1)*8, seq-1, 1, 0, 1, 8) + b'\0'*8
        source.ready_read.emit(DebugProtocol.build_response(svc.CMD_WAVE_DATA, 0, 0, payload))
    assert bus._pending == []
    assert bus.data_stats['queued_bytes'] <= 8192
    assert bus.data_stats['dropped_events'] > 0
    assert any(topic == 'frame/received' for topic, _, _ in bus._data_pending)
    bus.publish('debug/response', {'cmd': svc.CMD_WAVE_DATA, 'payload': b'x'*20000})
    bus.publish('debug/response', {'cmd': 0x0C, 'status': 0, 'payload': b'\0'})
    assert len(bus._pending) == 1  # Control evidence is never evicted by waveform traffic.
    bus.data_budget_bytes = 2*1024*1024
