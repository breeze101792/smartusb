import unittest

from hubctl.devices.smartusbhub import protocol


def drain(buf):
    frames = []
    while True:
        frame = protocol.next_frame(buf)
        if frame is None:
            return frames
        frames.append(frame)


class ProtocolTests(unittest.TestCase):
    def test_v1_round_trip(self):
        packet = protocol.encode_v1(protocol.CMD_GET_HARDWARE, 0, 3)
        self.assertEqual(packet, bytes([0x55, 0x5A, 0xFE, 0x00, 0x03, 0x01]))
        frames = drain(bytearray(packet))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].cmd, 0xFE)
        self.assertEqual(frames[0].value, 3)

    def test_v2_measurement_is_big_endian(self):
        packet = protocol.encode_v2(protocol.CMD_GET_VOLTAGE, 0x01, 0x12, 0x34)
        frame = drain(bytearray(packet))[0]
        self.assertEqual(frame.cmd, protocol.CMD_GET_VOLTAGE)
        self.assertEqual(frame.value, (0x12, 0x34))
        self.assertEqual((frame.value[0] << 8) | frame.value[1], 0x1234)

    def test_v3_round_trip(self):
        packet = protocol.encode_v3(0x1A, b"\x01\x02\x03\x04")
        frame = drain(bytearray(packet))[0]
        self.assertEqual(frame.cmd, 0x1A)
        self.assertTrue(frame.value["v3"])
        self.assertEqual(frame.value["payload"], b"\x01\x02\x03\x04")

    def test_bad_v1_checksum_resyncs(self):
        bad = bytes([0x55, 0x5A, 0xFE, 0x00, 0x03, 0x00])
        good = protocol.encode_v1(protocol.CMD_GET_FIRMWARE, 2, 0)
        frames = drain(bytearray(bad + good))
        self.assertEqual([frame.cmd for frame in frames], [protocol.CMD_GET_FIRMWARE])

    def test_bad_v3_crc_resyncs(self):
        bad = bytearray(protocol.encode_v3(0x1A, b"\x01\x02"))
        bad[8] ^= 0xFF
        good = protocol.encode_v1(protocol.CMD_GET_HARDWARE, 0, 3)
        frames = drain(bytearray(bytes(bad) + good))
        self.assertEqual([frame.cmd for frame in frames], [protocol.CMD_GET_HARDWARE])

    def test_truncated_frame_is_buffered(self):
        packet = protocol.encode_v3(0x1A, b"\x01\x02")
        buf = bytearray(packet[:6])
        self.assertIsNone(protocol.next_frame(buf))
        self.assertEqual(len(buf), 6)

    def test_channel_mask(self):
        self.assertEqual(protocol.channel_mask([1, 4]), 0x09)
        self.assertEqual(protocol.mask_channels(0x0F), [1, 2, 3, 4])
        with self.assertRaises(ValueError):
            protocol.channel_mask([8])

    def test_reject_frame(self):
        self.assertEqual(protocol.REJECT_FRAME,
                         bytes([0x55, 0x5A, 0x01, 0xFF, 0xFF, 0xFF]))


if __name__ == "__main__":
    unittest.main()
