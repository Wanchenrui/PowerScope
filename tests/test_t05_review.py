"""Independent B1 T05 lifecycle/manifest review regressions."""
import os
from dataclasses import replace


def test_queued_elf_result_cannot_repopulate_new_profile(qapp):
    from power_scope.config.device_profile import load_profile
    from power_scope.ui.main_window import MainWindow
    profile = load_profile('power_scope/profiles/ns800rt_smoke.yaml')
    profile.elf_file = ''
    window = MainWindow(profile)
    try:
        assert window._var_view.load_elf(os.environ['POWERSCOPE_TEST_ELF'], show_error=False)
        # EventBus queues ELF completion; profile boundary occurs before dispatch.
        window.apply_profile(replace(profile, name='new profile'))
        qapp.processEvents()
        assert not window._symbols
        assert not window._catalog_elf_path
        assert all(d.address is None for d in window._catalog.parameters.values())
    finally:
        window.close()


def test_verified_identity_refresh_does_not_recurse_or_duplicate_stream(qapp, monkeypatch):
    from power_scope.config.device_profile import load_profile
    from power_scope.config.device_pack import Verification
    from power_scope.core.contracts import DeviceIdentity, Capabilities
    from power_scope.ui.main_window import MainWindow
    import power_scope.ui.main_window as module
    profile = load_profile('power_scope/profiles/ns800rt_smoke.yaml')
    profile.elf_file = ''
    profile.manifest_file = 'fixture.json'
    window = MainWindow(profile)
    try:
        identity = DeviceIdentity(family='NS800RT5039', build_id=b'x'*32, protocol_version=1)
        window._session.identity = identity
        window._session.ready = True
        window._session.capabilities = Capabilities(sample_items=16)
        window._symbols = {'unbound': object()}
        window._catalog_elf_path = 'fixture.elf'
        verified, started = [], []
        def verify(*args):
            verified.append(args)
            return Verification(True, b'x'*32, 'a'*64)
        monkeypatch.setattr(module, 'verify_manifest', verify)
        window._start_streaming = lambda: started.append(1)
        window._on_session_identity(identity)
        assert len(verified) == 1 and started == [1]
        assert window._session.identity.artifacts_verified
    finally:
        window.close()


def test_newer_elf_and_other_window_own_their_completion(qapp, tmp_path):
    import shutil
    from power_scope.config.device_profile import load_profile
    from power_scope.ui.main_window import MainWindow
    profile = load_profile('power_scope/profiles/ns800rt_smoke.yaml')
    profile.elf_file = ''
    first = MainWindow(profile)
    second = MainWindow(replace(profile))
    path = os.environ['POWERSCOPE_TEST_ELF']
    newer = tmp_path / 'newer.elf'
    shutil.copyfile(path, newer)
    try:
        assert first._var_view.load_elf(path, show_error=False)
        assert first._var_view.load_elf(str(newer), show_error=False)
        qapp.processEvents()
        assert first._catalog_elf_path == str(newer)
        assert len(first._catalog.parameters) == 18
        assert not second._symbols and not second._catalog_elf_path
        # A failed replacement also invalidates the former catalog and parser.
        assert not first._var_view.load_elf(str(tmp_path / 'missing.elf'), show_error=False)
        qapp.processEvents()
        assert not first._symbols and not first._catalog_elf_path
        assert first._var_view._elf_parser is None
    finally:
        first.close()
        second.close()
