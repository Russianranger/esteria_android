import hashlib
import os
from pathlib import Path
import selectors
import struct
import subprocess
import time
import unittest

from tools import auth_protocol as protocol


def realm_body(address=b'127.0.0.1:8085', *, flags=2, count=1, name=b'Esteria'):
    row = bytes((0, 0, flags)) + name + b'\0' + address + b'\0' + struct.pack('<fBBB', .5, 0, 1, 1)
    if flags & 4:
        row += struct.pack('<BBBH', 3, 3, 5, 12340)
    return struct.pack('<IH', 0, count) + row * count + b'\x10\0'


class CodecTests(unittest.TestCase):
    def test_challenge_exact_source_struct_shape_and_limits(self):
        packet = protocol.challenge_packet('EST0123456789ABCD')
        self.assertEqual(len(packet), 51)
        self.assertEqual(packet[:4], b'\0\0\x2f\0')
        self.assertEqual(packet[4:13], b'WoW\0\3\3\5\x340')
        self.assertEqual(packet[13:25], b'68x\0niW\0SUne')
        self.assertEqual(packet[25:34], b'\0\0\0\0\x7f\0\0\1\x11')
        self.assertEqual(packet[34:], b'EST0123456789ABCD')
        for invalid in ('A' * 18, '', "A'", 'ä'):
            with self.assertRaises(ValueError): protocol.challenge_packet(invalid)

    def test_realm_shape_build_and_bounded_strings(self):
        row = protocol.parse_realms(realm_body(flags=6))[0]
        self.assertEqual(row['build'], (3, 3, 5, 12340))
        self.assertEqual(row['address'], '127.0.0.1:8085')
        self.assertEqual(protocol.parse_realms(realm_body(name=('界'*32).encode()))[0]['name'], '界'*32)
        for body in (realm_body()[:-1], realm_body() + b'junk', realm_body(count=2),
                     realm_body(address=b'a' * 256), realm_body(name=b'a'*33), struct.pack('<IH', 0, 101) + bytes(4)):
            with self.subTest(size=len(body)), self.assertRaises(ValueError): protocol.parse_realms(body)

    def test_interleave_source_zero_prefix_rule(self):
        # Source trims an even number of leading zero bytes before hashing halves.
        for prefix in (0, 1, 2, 3, 31, 32):
            shared = bytes(prefix) + bytes(range(1, 33-prefix))
            start = (prefix + (prefix & 1)) // 2
            even = hashlib.sha1(shared[::2][start:]).digest()
            odd = hashlib.sha1(shared[1::2][start:]).digest()
            self.assertEqual(protocol.interleave(shared), bytes(v for pair in zip(even, odd) for v in pair))

    def test_public_value_and_generator_bounds(self):
        for public in (bytes(31), bytes(32), protocol.N_BYTES):
            with self.assertRaises(ValueError): protocol.client_proof('ADMIN', 'PASSWORD', bytes(32), public)
        with self.assertRaises(ValueError):
            protocol.client_proof('ADMIN', 'PASSWORD', bytes(32), (7).to_bytes(32, 'little'), private=bytes(32))

    def test_reader_handles_fragments_eof_and_deadline(self):
        class Connection:
            def __init__(self, data): self.data = data
            def settimeout(self, seconds): pass
            def recv(self, count):
                result, self.data = self.data[:1], self.data[1:]
                return result
        self.assertEqual(protocol.read_exact(Connection(b'abc'), 3, time.monotonic()+1), b'abc')
        with self.assertRaises(ValueError): protocol.read_exact(Connection(b'ab'), 3, time.monotonic()+1)
        with self.assertRaises(ValueError): protocol.read_exact(Connection(b'ab'), 2, time.monotonic()-1)

    def test_network_probe_refuses_nonlocal_endpoint_before_credentials(self):
        class Connection:
            def getpeername(self): return ('203.0.113.8',3724)
        with self.assertRaisesRegex(ValueError,'fixed local endpoint'):
            protocol.login(Connection(), {})


@unittest.skipUnless(os.environ.get('ESTERIA_AUTH_SRP_REFERENCE'), 'requires actual pinned server C++ SRP6 reference binary')
class ActualServerSrp(unittest.TestCase):
    def roundtrip(self, wrong):
        executable = Path(os.environ['ESTERIA_AUTH_SRP_REFERENCE']).resolve(strict=True)
        child = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with selectors.DefaultSelector() as ready:
                ready.register(child.stdout, selectors.EVENT_READ)
                self.assertTrue(ready.select(10), 'C++ reference challenge timed out')
            public = child.stdout.readline(66)
            self.assertEqual(len(public),65)
            a, proof, expected, key = protocol.client_proof('Admin', 'password', bytes(range(32)), bytes.fromhex(public.decode().strip()))
            if wrong: proof = bytes([proof[0]^1]) + proof[1:]
            output, errors = child.communicate((a.hex()+'\n'+proof.hex()+'\n').encode(), timeout=10)
            self.assertEqual(errors,b'')
            if wrong:
                self.assertEqual(child.returncode,3);self.assertEqual(output,b'rejected\n')
            else:
                self.assertEqual(child.returncode,0)
                self.assertEqual(output.decode().splitlines(),[expected.hex(),key.hex()])
        finally:
            if child.poll() is None: child.kill();child.wait(timeout=5)

    def test_real_cpp_accepts_client_proof_and_returns_matching_key(self): self.roundtrip(False)
    def test_real_cpp_rejects_wrong_client_proof(self): self.roundtrip(True)


if __name__ == '__main__': unittest.main()
