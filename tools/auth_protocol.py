"""Bounded build-12340 auth qualification codec for the pinned AuthSession.cpp.

This is a test client, not the reconstructed game client or a general login API.
Network callers must first verify the owned loopback authserver process and DB.
Credentials/proofs/session keys are deliberately absent from error messages.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import socket
import struct
import time

from runtime.provision_local_account import N

N_BYTES = N.to_bytes(32, 'little')
VERSION_CHALLENGE = bytes.fromhex('baa31e99a00b2157fc373fb369cdd2f1')
BUILD = 12340


def require(condition, message):
    if not condition:
        raise ValueError(message)


def upper(value):
    return ''.join(chr(ord(c) - 32) if 'a' <= c <= 'z' else c for c in value)


def sha(*values):
    result = hashlib.sha1()
    for value in values:
        result.update(value)
    return result.digest()


def challenge_packet(username):
    require(isinstance(username, str) and username.isascii() and username.isalnum() and 0 < len(username) <= 17,
            'invalid qualification username')
    name = upper(username).encode('ascii')
    # The packed source struct is34 fixed bytes + I_len; size excludes its first4.
    return struct.pack('<BBH4sBBBH4s4s4sI4sB', 0, 0, 30 + len(name), b'WoW\0', 3, 3, 5, BUILD,
                       b'68x\0', b'niW\0', b'SUne', 0, socket.inet_aton('127.0.0.1'), len(name)) + name


def interleave(shared):
    require(len(shared) == 32, 'invalid SRP shared secret length')
    start = 0
    while start < 32 and shared[start] == 0:
        start += 1
    start = (start + (start & 1)) // 2
    even, odd = sha(shared[::2][start:]), sha(shared[1::2][start:])
    return bytes(value for pair in zip(even, odd) for value in pair)


def client_proof(username, password, salt, server_b, *, private=None):
    """Exact SRP6 client counterpart to the pinned VerifyChallengeResponse.

    An explicit private scalar is for fixed-vector tests only. Production probe
    calls use cryptographic randomness and never persist the ephemeral value.
    """
    require(len(salt) == len(server_b) == 32, 'invalid SRP challenge length')
    require(0 < len(username) <= 17 and 0 < len(password) <= 16, 'invalid SRP credential length')
    private = secrets.token_bytes(32) if private is None else private
    require(isinstance(private, bytes) and len(private) == 32 and any(private), 'invalid SRP private scalar')
    a = int.from_bytes(private, 'little')
    public_a = pow(7, a, N).to_bytes(32, 'little')
    b = int.from_bytes(server_b, 'little')
    require(0 < b < N, 'invalid SRP server public value')
    x = int.from_bytes(sha(salt, sha((upper(username) + ':' + upper(password)).encode())), 'little')
    u = int.from_bytes(sha(public_a, server_b), 'little')
    require(u != 0, 'invalid SRP scrambling value')
    shared = pow((b - 3 * pow(7, x, N)) % N, a + u * x, N).to_bytes(32, 'little')
    require(any(shared), 'invalid SRP shared value')
    key = interleave(shared)
    xor = bytes(a ^ b for a, b in zip(sha(N_BYTES), sha(b'\x07')))
    proof = sha(xor, sha(upper(username).encode()), salt, public_a, server_b, key)
    server_proof = sha(public_a, proof, key)
    return public_a, proof, server_proof, key


def read_exact(connection, count, deadline):
    require(0 <= count <= 65535, 'auth packet size exceeds bound')
    result = bytearray()
    while len(result) < count:
        remaining = deadline - time.monotonic()
        require(remaining > 0, 'auth protocol deadline exceeded')
        connection.settimeout(remaining)
        part = connection.recv(count - len(result))
        require(part, 'authserver closed an incomplete packet')
        result.extend(part)
    return bytes(result)


def read_challenge(connection, deadline, expected_salt):
    require(read_exact(connection, 3, deadline) == b'\0\0\0', 'authserver rejected build/account challenge')
    public = read_exact(connection, 32, deadline)
    require(read_exact(connection, 2, deadline) == b'\1\7', 'authserver SRP generator differs')
    require(read_exact(connection, 1, deadline) == b'\x20' and read_exact(connection, 32, deadline) == N_BYTES,
            'authserver SRP modulus differs')
    salt = read_exact(connection, 32, deadline)
    require(hmac.compare_digest(salt, expected_salt), 'authserver account salt differs from owned intent')
    require(read_exact(connection, 16, deadline) == VERSION_CHALLENGE and read_exact(connection, 1, deadline) == b'\0',
            'unexpected version challenge or account security requirements')
    return salt, public


def parse_realms(body):
    require(8 <= len(body) <= 65535, 'realm list size exceeds bounds')
    marker, count = struct.unpack_from('<IH', body)
    require(marker == 0 and 1 <= count <= 100, 'unexpected realm-list header')
    position = 6
    rows = []
    def take(size):
        nonlocal position
        require(size <= len(body) - position, 'truncated realm-list entry')
        result = body[position:position + size]; position += size
        return result
    def string(maximum):
        nonlocal position
        end = body.find(b'\0', position, min(len(body), position + maximum + 1))
        require(end >= position, 'unbounded realm-list string')
        value = body[position:end].decode('utf-8', errors='strict'); position = end + 1
        return value
    for _ in range(count):
        kind, locked, flags = take(3)
        name, address = string(128), string(255)
        require(len(name) <= 32, 'realm name exceeds source character bound')
        population, characters, timezone, identifier = struct.unpack('<fBBB', take(7))
        require(math.isfinite(population) and population >= 0 and locked in (0, 1), 'invalid realm-list values')
        build = struct.unpack('<BBBH', take(5)) if flags & 4 else None
        rows.append(dict(id=identifier, type=kind, locked=locked, flags=flags, name=name, address=address,
                         population=population, characterCount=characters, timezone=timezone, build=build))
    require(take(2) == b'\x10\0' and position == len(body), 'unexpected realm-list trailer')
    require(len({row['id'] for row in rows}) == len(rows), 'duplicate realm identifiers')
    return rows


def login(connection, intent):
    """Return public realm rows and a private session key to the owning harness."""
    require(connection.getpeername()[0] == '127.0.0.1' and connection.getpeername()[1] == 3724,
            'auth qualification must use the fixed local endpoint')
    deadline = time.monotonic() + 30
    connection.settimeout(30)
    connection.sendall(challenge_packet(intent['username']))
    salt, public = read_challenge(connection, deadline, bytes.fromhex(intent['saltHex']))
    a, proof, server_proof, key = client_proof(intent['username'], intent['password'], salt, public)
    # crc_hash is unused by the selected source's StrictVersionCheck=0 profile.
    # The owning harness verifies that setting rather than silently disabling it.
    connection.sendall(b'\1' + a + proof + bytes(20) + b'\0\0')
    require(read_exact(connection, 2, deadline) == b'\1\0', 'authserver rejected SRP proof')
    reply = read_exact(connection, 30, deadline)
    require(hmac.compare_digest(reply[:20], server_proof), 'authserver SRP proof did not authenticate the server')
    _, survey, login_flags = struct.unpack('<IIH', reply[20:])
    require(survey == login_flags == 0, 'unexpected login survey/security flags')
    connection.sendall(b'\x10' + bytes(4))
    header = read_exact(connection, 3, deadline)
    require(header[0] == 0x10, 'unexpected realm-list opcode')
    size = struct.unpack_from('<H', header, 1)[0]
    return parse_realms(read_exact(connection, size, deadline)), key
