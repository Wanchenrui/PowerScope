import struct

from power_scope.ui.serial_upgrade_view import SerialUpgradeController


def _valid_image(size=600):
    return struct.pack("<II", 0x20001000, 0x08000101) + bytes(size - 8)


def test_temporary_upgrade_protocol_sends_size_and_256_byte_blocks(qapp):
    writes = []
    completed = []
    controller = SerialUpgradeController(writer=writes.append)
    controller.finished.connect(lambda ok, message: completed.append((ok, message)))
    image = _valid_image()

    controller.begin_bytes(image)
    assert writes == [SerialUpgradeController.TRIGGER]

    controller.feed(bytes([SerialUpgradeController.READY]))
    assert writes[-1] == struct.pack("<I", len(image))

    controller.feed(bytes([SerialUpgradeController.ACK]))  # size accepted
    controller.feed(bytes([SerialUpgradeController.ACK]))  # erase complete
    assert writes[-1] == image[:256]

    controller.feed(bytes([SerialUpgradeController.ACK]))
    assert writes[-1] == image[256:512]
    controller.feed(bytes([SerialUpgradeController.ACK]))
    assert writes[-1] == image[512:]
    controller.feed(bytes([SerialUpgradeController.ACK]))
    controller.feed(bytes([SerialUpgradeController.DONE]))

    assert completed and completed[-1][0] is True
    assert controller.active is False


def test_upgrade_rejects_invalid_vector_table_without_writing(qapp):
    controller = SerialUpgradeController(writer=lambda _data: None)
    invalid = struct.pack("<II", 0x10000000, 0x08000100)

    try:
        controller.begin_bytes(invalid)
    except ValueError as exc:
        assert "向量表" in str(exc)
    else:
        raise AssertionError("invalid vector table must be rejected")
