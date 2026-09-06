"""Controlled command orchestration. Real control remains denied by G0.

Offline construction is explicit, requires a sessionless protocol service, and
never changes the real Debug/Session gates. No command is retried automatically.
"""
from dataclasses import dataclass, field
import time
from PySide6.QtCore import QObject, QTimer

from .contracts import (CommandIntent, CommandReceipt, CommandPhase, DeviceIdentity,
                        Observation, Quality)
from .parameter_codec import encode_parameter, decode_parameter


@dataclass
class OfflineCommandContext:
    epoch: int
    identity: DeviceIdentity
    permissions: frozenset[str]
    ready: bool = True
    is_connected: bool = True
    exclusive: bool = False


@dataclass
class CommandRecord:
    intent: CommandIntent
    encoded_value: bytes | None = None
    actual_raw_value: int | float | bool | None = None
    anchor_value: int | float | bool | None = None
    anchor_received_ns: int | None = None
    readback_value: int | float | bool | None = None
    receipts: list[CommandReceipt] = field(default_factory=list)
    done: bool = False
    attempted: bool = False
    parameter: object = None

    @property
    def receipt(self):
        return self.receipts[-1] if self.receipts else None


class CommandService(QObject):
    OPERATIONS = frozenset({"write_parameter", "start", "stop", "run_mode",
                            "clear_fault", "upgrade", "maintenance"})

    def __init__(self, session, debug, parameters, state_provider, *,
                 clock_ns=time.monotonic_ns, max_age_ns=500_000_000,
                 state_alias="running_state", parent=None):
        super().__init__(parent)
        if max_age_ns <= 0:
            raise ValueError("Freshness budget must be positive")
        self.session, self.debug = session, debug
        self.parameters = parameters
        self.state_provider = state_provider
        self.state_alias = state_alias
        self.clock_ns, self.max_age_ns = clock_ns, max_age_ns
        self.records = {}
        self._active = None
        self._uncertain = set()
        self._offline = False
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self.expire)
        if hasattr(session, "epoch_changed"):
            session.epoch_changed.connect(self._invalidated)

    @classmethod
    def for_offline_test(cls, debug, parameters, context, state_provider, **kwargs):
        if debug._session is not None or not isinstance(context, OfflineCommandContext):
            raise ValueError("Offline tests require a sessionless DebugService and explicit context")
        kwargs.setdefault("state_alias", "offline_running_state")
        service = cls(context, debug, parameters, state_provider, **kwargs)
        debug.require_write_count = True
        service._offline = True
        return service

    def _receipt(self, record, phase, evidence, response=None, done=False):
        response = response or {}
        record.receipts.append(CommandReceipt(record.intent.intent_id, record.intent.epoch,
            phase, evidence, wire_sequence=response.get("seq"), status=response.get("status"),
            observed_value=record.readback_value))
        if done:
            record.done = True
            if phase == CommandPhase.UNKNOWN and record.attempted:
                self._uncertain.add(self._risk_key(record.intent))
            if self._active is record:
                self._active = None
                self._timer.stop()

    @staticmethod
    def _risk_key(intent):
        return intent.target_alias if intent.operation == "write_parameter" else "device_control"

    def _invalidated(self, *args):
        if self._active is not None:
            r = self._active
            phase = CommandPhase.UNKNOWN if r.attempted else CommandPhase.REJECTED
            self._receipt(r, phase, "Session invalidated", done=True)

    def expire(self):
        r = self._active
        if r is not None and self.clock_ns() >= r.intent.deadline_ns:
            phase = CommandPhase.UNKNOWN if r.attempted else CommandPhase.REJECTED
            self._receipt(r, phase, "Command deadline expired", done=True)

    def _validate(self, r, identity):
        i, s = r.intent, self.session
        if i.epoch != s.epoch or not s.is_connected or not s.ready:
            raise ValueError("Session not ready or stale epoch")
        if s.identity != identity or not identity.artifacts_verified or not identity.family or not isinstance(identity.build_id, bytes) or len(identity.build_id) != 32 or not any(identity.build_id):
            raise ValueError("Device identity unverified or changed")
        if self.clock_ns() >= i.deadline_ns:
            raise ValueError("Command deadline expired")
        if getattr(s, "exclusive", False):
            raise ValueError("Exclusive mode active")
        state = self.state_provider()
        now = self.clock_ns()
        if not isinstance(state, Observation) or state.alias != self.state_alias or state.epoch != i.epoch or state.quality != Quality.VALID:
            raise ValueError("Running state unavailable")
        if state.host_received_ns is None or not 0 <= now - state.host_received_ns <= self.max_age_ns:
            raise ValueError("Running state stale")
        if i.required_state is None or {0: "stopped", 1: "running"}.get(state.raw_value) != i.required_state:
            raise ValueError("Required running state not satisfied")
        if not self._offline:
            raise ValueError("Real control remains disabled (G0)")
        if self.debug._session is not None:
            raise ValueError("Offline service cannot use a bound session")
        # These 0/1 values are explicit OFFLINE fixture semantics, not NS5039 FSM codes.
        if i.operation in ("start", "run_mode", "clear_fault") and i.required_state != "stopped":
            raise ValueError("Operation requires stopped state")
        if i.operation not in s.permissions:
            raise ValueError("Operation permission denied")
        if i.operation == "write_parameter":
            p = self.parameters.get(i.target_alias)
            if p is None or not p.readable or not p.writable:
                raise ValueError("Parameter permission denied")
            if i.required_state != "stopped" or i.required_state not in p.allowed_modes:
                raise ValueError("Parameter requires allowed stopped mode")
            if r.parameter is not None and p != r.parameter:
                raise ValueError("Parameter descriptor changed")
            encoded = encode_parameter(p, i.requested_value)
            if r.encoded_value is not None and encoded.data != r.encoded_value:
                raise ValueError("Parameter descriptor changed")
            if i.encoded_value is not None and i.encoded_value != encoded.data:
                raise ValueError("Caller encoding mismatch")
            return p, encoded
        return None, None

    def submit(self, intent: CommandIntent):
        # Returning the original record makes duplicate IDs idempotent, never a retry.
        if intent.intent_id in self.records:
            return self.records[intent.intent_id]
        r = CommandRecord(intent)
        self.records[intent.intent_id] = r
        identity = self.session.identity
        try:
            if intent.operation not in self.OPERATIONS:
                raise ValueError("Unknown controlled intent")
            if not intent.intent_id:
                raise ValueError("Missing intent ID")
            if self._active is not None or self.debug._pending or self._uncertain:
                raise ValueError("Command busy or previous outcome unknown")
            if intent.operation in ("upgrade", "maintenance"):
                raise ValueError("Exclusive operation requires verified device workflow (T13)")
            p, encoded = self._validate(r, identity)
            if intent.operation == "run_mode" and (type(intent.requested_value) is not int or intent.requested_value not in (0, 1)):
                raise ValueError("Unsupported running mode")
        except Exception as exc:
            self._receipt(r, CommandPhase.REJECTED, str(exc), done=True)
            return r
        self._active = r
        self._timer.start()
        if p is not None:
            r.parameter = p
            r.encoded_value, r.actual_raw_value = encoded.data, encoded.raw_value
            self._dispatch(r, lambda cb: self.debug.read_memory(p.address, p.byte_size, cb),
                           lambda resp: self._anchor(r, p, identity, resp))
        else:
            self._write(r, identity)
        return r

    def _dispatch(self, r, send, callback, writing=False):
        queued = []
        sending = True
        def receive(response):
            if sending:
                queued.append(response)
            elif not r.done:
                callback(response)
        if writing:
            r.attempted = True
        try:
            seq = send(receive)
        except Exception as exc:
            if not r.done:
                phase = CommandPhase.UNKNOWN if r.attempted else CommandPhase.REJECTED
                self._receipt(r, phase, f"Transport/request failure: {exc}", done=True)
            return
        sending = False
        if writing and not r.done:
            self._receipt(r, CommandPhase.SENT, "Full frame accepted by writer", {"seq": seq})
        for response in queued:
            if not r.done:
                callback(response)

    def _check_response(self, r, identity, response, *, after_write=False):
        if r.done:
            return False
        try:
            self._validate(r, identity)
            status = response.get("status")
            if status != 0:
                phase = CommandPhase.REJECTED
                if r.attempted and (after_write or status not in range(1, 8)):
                    phase = CommandPhase.UNKNOWN
                self._receipt(r, phase, "Request did not succeed", response, done=True)
                return False
        except Exception as exc:
            phase = CommandPhase.UNKNOWN if r.attempted else CommandPhase.REJECTED
            self._receipt(r, phase, str(exc), response, done=True)
            return False
        return True

    def _anchor(self, r, p, identity, response):
        if not self._check_response(r, identity, response):
            return
        try:
            r.anchor_value = decode_parameter(p, response.get("payload", b""))
        except ValueError as exc:
            self._receipt(r, CommandPhase.REJECTED, str(exc), done=True)
            return
        r.anchor_received_ns = self.clock_ns()
        self._write(r, identity)

    def _write(self, r, identity):
        try:
            p, _ = self._validate(r, identity)
            if p is not None and not 0 <= self.clock_ns() - r.anchor_received_ns <= self.max_age_ns:
                raise ValueError("Parameter anchor stale")
        except Exception as exc:
            self._receipt(r, CommandPhase.REJECTED, str(exc), done=True)
            return
        operation = r.intent.operation
        if p is not None:
            send = lambda cb: self.debug.write_memory(p.address, r.encoded_value, cb)
        elif operation in ("start", "stop"):
            send = lambda cb: self.debug.device_control(operation == "start", cb)
        elif operation == "run_mode":
            send = lambda cb: self.debug.set_run_mode(r.intent.requested_value, cb)
        else:
            send = self.debug.clear_fault
        self._dispatch(r, send, lambda resp: self._acked(r, p, identity, resp), writing=True)

    def _acked(self, r, p, identity, response):
        if not self._check_response(r, identity, response):
            return
        expected = b""
        if r.intent.operation in ("start", "stop"):
            expected = bytes([r.intent.operation == "start"])
        elif r.intent.operation == "run_mode":
            expected = bytes([r.intent.requested_value])
        if response.get("payload", b"") != expected:
            self._receipt(r, CommandPhase.UNKNOWN, "ACK echo differs from request", response, done=True)
            return
        self._receipt(r, CommandPhase.ACKED, "Device accepted command; effect remains unknown",
                      response, done=p is None)
        if p is not None:
            self._dispatch(r, lambda cb: self.debug.read_memory(p.address, p.byte_size, cb),
                           lambda resp: self._readback(r, p, identity, resp))

    def _readback(self, r, p, identity, response):
        if not self._check_response(r, identity, response, after_write=True):
            return
        try:
            r.readback_value = decode_parameter(p, response.get("payload", b""))
            if r.readback_value != r.actual_raw_value:
                raise ValueError("ACK received but typed readback differs")
        except ValueError as exc:
            self._receipt(r, CommandPhase.UNKNOWN, str(exc), response, done=True)
            return
        self._receipt(r, CommandPhase.VERIFIED, "Fresh typed parameter readback matches encoded value",
                      response, done=True)
