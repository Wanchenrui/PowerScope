"""Small device catalog and fail-closed build artifact verifier.

Static ACL is evidence only. Runtime writes remain closed until T06 supplies
state and fresh readback policy; this module never authorizes control.
"""
from dataclasses import dataclass
import hashlib
import json
import zipfile
from pathlib import Path
from elftools.common.exceptions import ELFError

from ..core.contracts import DeviceIdentity, ParameterDescriptor, TypeSource
from ..debug.elf_parser import TYPE_FORMATS, resolve_symbol_path, type_size

PACKS = {"ns5039-v1": ("NS800RT5039", "1"), "ess-observation-v1": (None, "1")}
# Exact source paths, not inferred symbol suffix permissions.
PARAMETERS = [
    ("inv_curr_freq_kp", "g_invCurrLoopCfg.freqCfg.kp", None, "PI calls commented", 100),
    ("inv_curr_freq_ki", "g_invCurrLoopCfg.freqCfg.kiTc", None, "PI calls commented", 100),
    ("inv_curr_pri_kp", "g_invCurrLoopCfg.priDutyCfg.kp", (-10, 10), "PI calls commented", 100),
    ("inv_curr_pri_ki", "g_invCurrLoopCfg.priDutyCfg.kiTc", (-1, 1), "PI calls commented", 100),
    ("inv_curr_phase_kp", "g_invCurrLoopCfg.phsCfg.kp", (-10, 10), "PI calls commented", 100),
    ("inv_curr_phase_ki", "g_invCurrLoopCfg.phsCfg.kiTc", (-1, 1), "PI calls commented", 100),
    ("inv_volt_kp", "g_invVoltLoopCfg.voltCfg.kp", (-100, 100), "PI when state != STATE_DISABLE; not bench verified", 100),
    ("inv_volt_ki", "g_invVoltLoopCfg.voltCfg.kiTc", (-1, 1), "PI when state != STATE_DISABLE; not bench verified", 100),
    ("current_limit_kp", "g_iLmtLoopCfg.iLmtCfg.kp", None, "unconfirmed", None),
    ("current_limit_ki", "g_iLmtLoopCfg.iLmtCfg.kiTc", None, "unconfirmed", None),
    ("urms_kp", "g_uRmsLoopCfg.urmsCfg.kp", (-10, 10), "PI when loop != LOOP_DISABLE; not bench verified", 300),
    ("urms_ki", "g_uRmsLoopCfg.urmsCfg.kiTc", (-1, 1), "PI when loop != LOOP_DISABLE; not bench verified", 300),
    ("active_power_kp", "g_aplCfg.cfg.kp", None, "APL_Process slice6; parameter effect unconfirmed", None),
    ("active_power_ki", "g_aplCfg.cfg.kiTc", None, "APL_Process slice6; parameter effect unconfirmed", None),
    ("reactive_power_kp", "g_rplCfg.cfg.kp", None, "conditional RPL_Process slice2; parameter effect unconfirmed", None),
    ("reactive_power_ki", "g_rplCfg.cfg.kiTc", None, "conditional RPL_Process slice2; parameter effect unconfirmed", None),
    ("spll_kp", "g_spllCfg.kp", None, "SPLL_Process; parameter effect unconfirmed", None),
    ("spll_ki", "g_spllCfg.kiTc", None, "SPLL_Process; parameter effect unconfirmed", None),
]


def trusted_type(symbol):
    if symbol is None or not getattr(symbol, "dwarf_verified", False):
        return None
    if type_size(symbol.type_name) != symbol.size:
        return None
    fmt = TYPE_FORMATS.get(symbol.type_name, "")[-1:]
    return {"f": "<f4", "d": "<f8", "b": "|i1", "B": "|u1", "h": "<i2",
            "H": "<u2", "i": "<i4", "I": "<u4", "q": "<i8", "Q": "<u8"}.get(fmt)


class DeviceCatalog:
    def __init__(self, profile, symbols, identity=None):
        self.pack_id = profile.device_pack
        self.parameters = {}
        self.diagnostics = []
        self._subscriptions = set()
        self._display = {}
        identity = identity or DeviceIdentity()
        bindings = {v.name: v for v in profile.variables}
        for binding in profile.variables:
            symbol = resolve_symbol_path(symbols, binding.elf_symbol)
            if trusted_type(symbol):
                self._subscriptions.add(binding.name)
            elif binding.elf_symbol:
                self.diagnostics.append(f"{binding.name}: unresolved or untrusted DWARF: {binding.elf_symbol}; subscription disabled")
        if self.pack_id != "ns5039-v1" or profile.device_type != "microinverter":
            return
        matched = identity.family == "NS800RT5039" and identity.artifacts_verified and bool(identity.build_id)
        for alias, path, write_range, effect, period in PARAMETERS:
            binding = bindings.get(alias)
            symbol = resolve_symbol_path(symbols, path) if binding and binding.elf_symbol == path else None
            dtype = trusted_type(symbol)
            # These catalog fields require the independently documented float/4 ABI.
            resolved = dtype == "<f4" and symbol.size == 4
            self.parameters[alias] = ParameterDescriptor(
                alias=alias, symbol=path, address=symbol.address if resolved else None,
                dtype=dtype if resolved else None, byte_size=4 if resolved else None,
                type_source=TypeSource.DWARF if resolved else TypeSource.UNKNOWN,
                readable=bool(resolved and matched), writable=False,
                write_range=write_range, control_period_us=period,
                coefficient_definition="kiTc initialization = Ki / ctrlFreq; library implementation unverified" if alias.endswith('_ki') else None,
                effect_condition=effect,
            )
            self._display[alias] = [binding.min_val, binding.max_val] if binding else None

    def subscription_allowed(self, alias):
        """Local typed observation candidate, not proof of device readability."""
        return alias in self._subscriptions

    def invalidate(self):
        self.parameters.clear()
        self._subscriptions.clear()
        self._display.clear()
        self.diagnostics = ["catalog invalidated; reload ELF/profile and verify identity"]

    def report(self):
        rows = []
        for alias, d in self.parameters.items():
            rows.append({"alias": alias, "symbol": d.symbol, "address": d.address,
                         "dtype": d.dtype, "byte_size": d.byte_size,
                         "display_range": self._display[alias], "write_range": d.write_range,
                         "resolved": d.address is not None, "readable": d.readable,
                         "acl": d.write_range is not None, "effect": "unknown", "tunable": False,
                         "writable": d.writable,
                         "evidence": {"resolved": d.type_source.value,
                                      "readable": "matching artifacts required; device read still requires live response",
                                      "acl": "FW 3469da8 user/source/debug_monitor_core.c:s_writeRules",
                                      "effect": d.effect_condition,
                                      "tunable": "no bench/library semantics verification; allowed_modes empty"}})
        return {"schema_version": 1, "pack_id": self.pack_id, "parameters": rows,
                "acl_count": sum(r["acl"] for r in rows),
                "denied_count": sum(not r["acl"] for r in rows), "diagnostics": self.diagnostics}


@dataclass(frozen=True)
class Verification:
    verified: bool = False
    build_id: bytes | None = None
    manifest_sha256: str | None = None
    errors: tuple[str, ...] = ()


def sha256_file(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_manifest(path, elf_path, device_build_id, pack_id):
    """Validate local artifacts and the ELF embedded ID against a live board ID.

    Relative artifact paths are resolved at the manifest directory. This is build
    consistency, not cryptographic device authentication or write permission.
    """
    errors = []
    manifest_hash = None
    build_id = None
    try:
        path = Path(path)
        raw = path.read_bytes()
        manifest_hash = hashlib.sha256(raw).hexdigest()
        m = json.loads(raw)
        model, version = PACKS[pack_id]
        if model is None or m["schema_version"] != 1 or m["status"] != "BUILT":
            raise ValueError("unsupported pack/schema or incomplete build")
        if m["model"] != model or m["device_pack_version"] != version:
            raise ValueError("model or DevicePack version mismatch")
        inputs = m["build_inputs"]
        canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        build_id = bytes.fromhex(m["build_id"])
        if len(build_id) != 32 or hashlib.sha256(canonical).digest() != build_id or build_id != device_build_id:
            raise ValueError("build inputs/device ID mismatch")
        if inputs["model"] != model or inputs["schema_version"] != 1 or inputs["fw_commit"] != m["fw_commit"]:
            raise ValueError("inconsistent build inputs")
        if not inputs["inputs"] or not inputs["toolchain"]["version"]:
            raise ValueError("missing input/toolchain evidence")
        if not m["static_libraries"] or m["static_libraries"] != inputs["static_libraries"]:
            raise ValueError("unknown or inconsistent library version")
        if type(inputs["dirty"]) is not bool:
            raise ValueError("missing dirty provenance")
        artifacts = [m["artifacts"]["elf"], m["artifacts"]["bin"], *m["static_libraries"]]
        if inputs["dirty"]:
            artifacts.append(m["source_snapshot"])
        for artifact in artifacts:
            local = path.parent / artifact["path"]
            if sha256_file(local) != artifact["sha256"]:
                raise ValueError(f"artifact hash mismatch: {artifact['path']}")
        if inputs["dirty"]:
            with zipfile.ZipFile(path.parent / m["source_snapshot"]["path"]) as archive:
                records = inputs["inputs"]
                names = [row["path"] for row in records]
                if len(set(names)) != len(names) or sorted(archive.namelist()) != sorted(names):
                    raise ValueError("source snapshot inputs mismatch")
                for row in records:
                    if hashlib.sha256(archive.read(row["path"])).hexdigest() != row["sha256"]:
                        raise ValueError("source snapshot content mismatch")
        if sha256_file(elf_path) != m["artifacts"]["elf"]["sha256"]:
            raise ValueError("selected ELF mismatch")
        from elftools.elf.elffile import ELFFile
        with open(elf_path, "rb") as stream:
            section = ELFFile(stream).get_section_by_name(".powerscope_build_id")
            if section is None or section.data() != build_id:
                raise ValueError("ELF embedded build ID missing/mismatch")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ELFError, zipfile.BadZipFile) as exc:
        errors.append(str(exc))
    return Verification(not errors, build_id, manifest_hash, tuple(errors))
