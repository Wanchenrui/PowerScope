"""Independent command review: wire frames assembled without production codec."""
from dataclasses import replace
import struct
import pytest

from power_scope.core.command_service import CommandService, OfflineCommandContext
from power_scope.core.contracts import (CommandIntent, CommandPhase, DeviceIdentity,
    EffectState, Observation, ParameterDescriptor, Quality, TypeSource)
from power_scope.core.debug_service import DebugService
from power_scope.core.parameter_codec import encode_parameter


def crc_frame(body):
    crc = 0xFFFF
    for byte in body:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return body + crc.to_bytes(2, 'little')


def request(cmd, seq, address=0, payload=b''):
    return crc_frame(b'\xA5\x5A\x01' + bytes([cmd]) + struct.pack('<HIH', seq, address, len(payload)) + payload)


def response(cmd, seq, payload=b'', status=0):
    return crc_frame(b'\xA5\x5A\x01' + bytes([cmd]) + struct.pack('<HBH', seq, status, len(payload)) + payload)


@pytest.fixture
def command_rig(qapp):
    wire = []
    debug = DebugService(writer=lambda frame: wire.append(frame) or len(frame))
    context = OfflineCommandContext(2, DeviceIdentity('review', b'z'*32, 1, 'a'*64, True), CommandService.OPERATIONS)
    parameter = ParameterDescriptor('p', 'p', 0x20000010, 'uint64_t', 8,
        type_source=TypeSource.DEVICE_PACK, readable=True, writable=True,
        write_range=(0, 2**64-1), allowed_modes=frozenset({'stopped'}))
    now = [1000000000]
    state = lambda: Observation('offline_running_state', 2, 0, now[0], quality=Quality.VALID)
    service = CommandService.for_offline_test(debug, {'p': parameter}, context, state, clock_ns=lambda: now[0])
    return service, debug, context, wire, now


def intent(op='write_parameter', value=2**64-1, ident='review'):
    return CommandIntent(ident, 2, 'p', op, 2000000000, requested_value=value, required_state='stopped')


def test_review_full_parameter_frames_and_exact_uint64(command_rig):
    service, debug, context, wire, _ = command_rig
    record = service.submit(intent())
    assert wire == [request(1, 1, 0x20000010, b'\x08')]
    debug.feed(response(1, 1, b'\x00'*8))
    assert wire[1] == request(2, 2, 0x20000010, b'\xff'*8)
    debug.feed(response(2, 2))
    assert wire[2] == request(1, 3, 0x20000010, b'\x08')
    debug.feed(response(1, 3, b'\xff'*8))
    assert [r.phase for r in record.receipts] == [CommandPhase.SENT, CommandPhase.ACKED, CommandPhase.VERIFIED]
    assert record.readback_value == 2**64-1 and record.receipt.effect == EffectState.UNKNOWN


@pytest.mark.parametrize('op,cmd,payload,value', [('start',12,b'\x01',None), ('stop',12,b'\x00',None),
    ('run_mode',13,b'\x01',1), ('clear_fault',14,b'',None)])
def test_review_control_wire_and_ack_lengths(command_rig, op, cmd, payload, value):
    service, debug, _, wire, _ = command_rig
    record = service.submit(intent(op,value))
    assert wire == [request(cmd, 1, payload=payload)]
    wrong = b'' if payload else b'\0'
    debug.feed(response(cmd, 1, wrong))
    assert record.receipt.phase == CommandPhase.SENT
    debug.feed(response(cmd, 1, payload))
    assert record.receipt.phase == CommandPhase.ACKED and record.done
    assert record.receipt.effect == EffectState.UNKNOWN


@pytest.mark.parametrize('mutation', ['address','identity','epoch','permissions','state_exception'])
def test_review_anchor_revalidation_blocks_changes(command_rig, mutation):
    service, debug, context, wire, _ = command_rig
    record = service.submit(intent())
    if mutation == 'address':
        service.parameters['p'] = replace(service.parameters['p'], address=0x20000018)
    elif mutation == 'identity':
        context.identity = replace(context.identity, artifacts_verified=False)
    elif mutation == 'epoch':
        context.epoch += 1
    elif mutation == 'permissions':
        context.permissions = frozenset()
    else:
        def fail():
            raise RuntimeError('state source unavailable')
        service.state_provider = fail
    debug.feed(response(1,1,b'\0'*8))
    assert record.receipt.phase == CommandPhase.REJECTED
    assert len(wire) == 1


def test_review_short_write_sticky_unknown_and_no_retry(command_rig):
    service, debug, context, wire, now = command_rig
    debug._writer = lambda frame: wire.append(frame) or len(frame)-1
    record = service.submit(intent('start',None))
    assert record.receipt.phase == CommandPhase.UNKNOWN
    assert all(r.phase != CommandPhase.SENT for r in record.receipts)
    context.epoch = 3
    retry = service.submit(replace(intent('stop',None,'next'),epoch=3))
    assert retry.receipt.phase == CommandPhase.REJECTED and len(wire) == 1
    assert service.submit(intent('start',None)) is record


def test_review_scaled_uint64_never_rounds_integer(command_rig):
    parameter = replace(command_rig[0].parameters['p'], scale=2, write_range=(0,2**65))
    encoded = encode_parameter(parameter, (2**63+1)*2)
    assert encoded.raw_value == 2**63+1
    assert encoded.data == b'\x01\0\0\0\0\0\0\x80'


def test_review_late_readback_after_identity_revocation_is_unknown(command_rig):
    service, debug, context, wire, _ = command_rig
    record = service.submit(intent())
    debug.feed(response(1,1,b'\0'*8))
    debug.feed(response(2,2))
    context.identity = replace(context.identity, artifacts_verified=False)
    debug.feed(response(1,3,b'\xff'*8))
    assert record.receipt.phase == CommandPhase.UNKNOWN
    assert not any(r.phase == CommandPhase.VERIFIED for r in record.receipts)


def test_review_normal_constructor_never_authorizes_real_control(command_rig):
    service, debug, context, wire, now = command_rig
    real = CommandService(context, debug, service.parameters, service.state_provider, clock_ns=lambda: now[0], state_alias='offline_running_state')
    for op in CommandService.OPERATIONS:
        assert real.submit(intent(op,None,op)).receipt.phase == CommandPhase.REJECTED
    assert wire == []


@pytest.mark.parametrize('mutation', [{'type_source':TypeSource.UNKNOWN}, {'dtype':'pointer'},
    {'byte_size':4}, {'address':0x20000011}, {'scale':0}, {'write_range':None}])
def test_review_parameter_contract_rejects_without_wire(command_rig, mutation):
    service, _, _, wire, _ = command_rig
    service.parameters['p'] = replace(service.parameters['p'], **mutation)
    assert service.submit(intent()).receipt.phase == CommandPhase.REJECTED
    assert wire == []


def test_review_deadline_after_send_and_late_ack_stays_unknown(command_rig):
    service, debug, _, wire, now = command_rig
    record = service.submit(intent('start',None))
    now[0] = 2000000000
    service.expire()
    debug.feed(response(12,1,b'\x01'))
    assert record.done and record.receipt.phase == CommandPhase.UNKNOWN
    assert len(wire) == 1


def test_review_state_provider_exception_at_ack_cannot_verify(command_rig):
    service, debug, _, wire, _ = command_rig
    record = service.submit(intent('start',None))
    def fail():
        raise RuntimeError('state source failed at ACK')
    service.state_provider = fail
    debug.feed(response(12,1,b'\x01'))
    assert record.done and record.receipt.phase == CommandPhase.UNKNOWN
    assert len(wire) == 1
