from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.firmware.codec import (  # noqa: E402
    decode_image,
    encode_image,
    substitution_map,
    unpack_sram,
    vector_table,
)


class CodecTests(unittest.TestCase):
    def test_substitution_map_is_a_permutation_and_round_trips(self):
        table = substitution_map()
        self.assertEqual(len(table), 256)
        self.assertEqual(sorted(table), list(range(256)))
        sample = bytes(range(256)) * 3
        self.assertEqual(decode_image(encode_image(sample, table), table), sample)

    def test_unpack_sram_zero_fill_stream(self):
        output_length = 0x898
        stream = bytearray()
        full_runs, remainder = divmod(output_length, 15)
        stream.extend([0xF1] * full_runs)
        if remainder:
            stream.append(remainder << 4 | 0x01)
        image = bytes(0x8360) + bytes(stream)
        self.assertEqual(unpack_sram(image), bytes(output_length))

    def test_vector_table_accepts_cortex_m4_application(self):
        image = (0x20000E58).to_bytes(4, "little") + (0x08004165).to_bytes(4, "little")
        self.assertEqual(vector_table(image), (0x20000E58, 0x08004165))
