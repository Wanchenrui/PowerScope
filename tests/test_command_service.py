from dataclasses import replace
import struct
import pytest
from power_scope.core.contracts import *
from power_scope.core.command_service import CommandService, OfflineCommandContext
from power_scope.core.parameter_codec import encode_parameter
from power_scope.core.debug_service import DebugService
from power_scope.core.cffi_loader import DebugProtocol


@pytest.fixture
def rig(qapp):
    sent = []
    debug = DebugService(writer=lambda data: sent.append(data) or len(data))
    identity = DeviceIdentity('offline-fixture', b'x' * 32, 1, 'a' * 64, True)
    context = OfflineCommandContext(4, identity, CommandService.OPERATIONS)
    p = ParameterDescriptor('gain', 'gain', 0x20000000, 'float', 4,
        type_source=TypeSource.DWARF, readable=True, writable=True,
        write_range=(-100, 100), allowed_modes=frozenset({'stopped'}))
    now = [1_000_000_000]
    state = [Observation('offline_running_state', 4, 0, now[0], quality=Quality.VALID)]
    service = CommandService.for_offline_test(debug, {'gain': p}, context,
        lambda: state[0], clock_ns=lambda: now[0])
    def reply(payload=b'', status=0):
        frame = sent[-1]
        debug.feed(DebugProtocol.build_response(frame[3], struct.unpack_from('<H', frame, 4)[0], status, payload))
    return service, debug, context, sent, now, state, reply


def intent(operation='write_parameter', value=1.5, ident='one', target='gain'):
    return CommandIntent(ident, 4, target, operation, 2_000_000_000,
                         requested_value=value, required_state='stopped')


def test_exact_phases_and_audit(rig):
    s,d,c,sent,now,state,reply = rig
    r = s.submit(intent())
    assert r.receipts == [] and sent[-1][3] == 1
    reply(b'\x00\x00\x00\x3f')
    assert r.encoded_value == b'\x00\x00\xc0\x3f'
    assert r.anchor_value == 0.5
    assert r.receipt.phase == CommandPhase.SENT
    reply()
    assert r.receipt.phase == CommandPhase.ACKED
    reply(b'\x00\x00\xc0\x3f')
    assert [x.phase for x in r.receipts] == [CommandPhase.SENT, CommandPhase.ACKED, CommandPhase.VERIFIED]
    assert r.readback_value == 1.5 and r.receipt.effect == EffectState.UNKNOWN
    assert s.submit(intent()) is r and len(sent) == 3


@pytest.mark.parametrize('field,value', [('writable',False),('type_source',TypeSource.UNKNOWN),
    ('byte_size',8),('address',0x20000002),('scale',0),('write_range',None)])
def test_descriptor_rejections(rig,field,value):
    s,d,c,sent,*_ = rig
    s.parameters['gain'] = replace(s.parameters['gain'], **{field:value})
    assert s.submit(intent()).receipt.phase == CommandPhase.REJECTED
    assert not sent


@pytest.mark.parametrize('value',[float('nan'),float('inf'),101])
def test_numeric_rejections(rig,value):
    s,d,c,sent,*_ = rig
    assert s.submit(intent(value=value)).receipt.phase == CommandPhase.REJECTED
    assert not sent


def test_uint64_exact_and_overflow(rig):
    p = replace(rig[0].parameters['gain'], dtype='uint64_t', byte_size=8, write_range=(0,2**64-1))
    assert encode_parameter(p,2**64-1).data == b'\xff'*8
    with pytest.raises(ValueError): encode_parameter(p,2**64)
    p = replace(p,write_range=(-100,2**65))
    with pytest.raises(ValueError): encode_parameter(p,-1)


@pytest.mark.parametrize('change',['epoch','identity','state','age','deadline','address','exclusive','permission'])
def test_anchor_race_rechecks(rig,change):
    s,d,c,sent,now,state,reply = rig
    r=s.submit(intent())
    if change=='epoch': c.epoch+=1
    if change=='identity': c.identity=replace(c.identity,build_id=b'y'*32)
    if change=='state': state[0]=replace(state[0],raw_value=1)
    if change=='age': now[0]+=600_000_000
    if change=='deadline': now[0]=2_000_000_000
    if change=='address': s.parameters['gain']=replace(s.parameters['gain'],address=0x20000004)
    if change=='exclusive': c.exclusive=True
    if change=='permission': c.permissions=frozenset()
    reply(b'\x00'*4)
    assert r.receipt.phase == CommandPhase.REJECTED and len(sent)==1


def test_mismatch_unknown_and_no_retry(rig):
    s,d,c,sent,now,state,reply=rig
    r=s.submit(intent()); reply(b'\x00'*4); reply(); reply(b'\x00'*4)
    assert r.receipt.phase == CommandPhase.UNKNOWN
    assert s.submit(intent(ident='two')).receipt.phase == CommandPhase.REJECTED
    assert len(sent)==3


def test_partial_completion_preserves_first(rig):
    s,d,c,sent,now,state,reply=rig
    a=s.submit(intent()); reply(b'\x00'*4); reply(); reply(b'\x00\x00\xc0\x3f')
    b=s.submit(intent(ident='two')); reply(b'\x00'*4)
    c.is_connected=False
    s._invalidated()
    assert a.receipt.phase == CommandPhase.VERIFIED
    assert b.receipt.phase == CommandPhase.UNKNOWN


def test_short_write_is_unknown(rig):
    s,d,c,sent,now,state,reply=rig
    r=s.submit(intent())
    d._writer=lambda data: len(data)-1
    reply(b'\x00'*4)
    assert r.receipt.phase == CommandPhase.UNKNOWN
    assert not any(x.phase==CommandPhase.SENT for x in r.receipts)


@pytest.mark.parametrize('op,payload,value',[('start',b'\x01',None),('stop',b'\x00',None),
    ('run_mode',b'\x01',1),('clear_fault',b'',None)])
def test_control_ack_only(rig,op,payload,value):
    s,d,c,sent,now,state,reply=rig
    r=s.submit(intent(op,value)); reply(payload)
    assert r.done and r.receipt.phase == CommandPhase.ACKED
    assert r.receipt.effect==EffectState.UNKNOWN


def test_control_timeout_sticky(rig):
    s,d,c,sent,now,state,reply=rig
    r=s.submit(intent('start',None))
    now[0]=3_000_000_000; s.expire()
    assert r.receipt.phase==CommandPhase.UNKNOWN
    c.epoch+=1
    assert s.submit(replace(intent('start',None,ident='two'),epoch=c.epoch)).receipt.phase==CommandPhase.REJECTED
    assert len(sent)==1


def test_real_constructor_never_authorizes(rig):
    s,d,c,sent,now,state,reply=rig
    real=CommandService(c,d,s.parameters,lambda:state[0],clock_ns=lambda:now[0])
    assert real.submit(intent()).receipt.phase==CommandPhase.REJECTED
    assert not sent


def test_nack_rejected_and_wrong_echo_unknown(rig):
    s,d,c,sent,now,state,reply=rig
    r=s.submit(intent('start',None)); reply(status=5)
    assert r.receipt.phase==CommandPhase.REJECTED
    r=s.submit(intent('start',None,ident='two')); reply(b'\x00')
    assert r.receipt.phase==CommandPhase.UNKNOWN


def test_provider_failure_is_receipt(rig):
    s,d,c,sent,*_=rig
    def fail(): raise RuntimeError('state source offline')
    s.state_provider=fail
    r=s.submit(intent())
    assert r.receipt.phase==CommandPhase.REJECTED and not sent
    assert 'state source offline' in r.receipt.evidence


def test_provider_failure_after_write_is_unknown(rig):
    s,d,c,sent,now,state,reply=rig
    r=s.submit(intent()); reply(b'\x00'*4)
    def fail(): raise RuntimeError('state source offline')
    s.state_provider=fail
    reply()
    assert r.receipt.phase==CommandPhase.UNKNOWN and len(sent)==2


def test_missing_write_count_cannot_claim_sent(rig):
    s,d,c,sent,now,state,reply=rig
    r=s.submit(intent())
    d._writer=lambda data: None
    reply(b'\x00'*4)
    assert r.receipt.phase==CommandPhase.UNKNOWN
    assert not any(x.phase==CommandPhase.SENT for x in r.receipts)


def test_scaled_signed_encoding(rig):
    p=replace(rig[0].parameters['gain'],dtype='int16_t',byte_size=2,scale=0.5,offset=1)
    assert encode_parameter(p,-2).data==b'\xfa\xff'
    with pytest.raises(ValueError): encode_parameter(p,1.1)


def test_readback_disconnect_and_deadline(rig):
    s,d,c,sent,now,state,reply=rig
    r=s.submit(intent()); reply(b'\x00'*4); reply()
    now[0]=3_000_000_000
    reply(b'\x00\x00\xc0\x3f')
    assert r.receipt.phase==CommandPhase.UNKNOWN
