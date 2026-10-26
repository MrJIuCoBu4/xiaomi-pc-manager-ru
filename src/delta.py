"""Bounded copy/insert delta codec. No executable code is loaded from a patch."""
import struct
MAGIC = b'XPRD1\0'
MAX_FILE_SIZE = 128 * 1024 * 1024

def encode(source, target, block=32):
    index = {}
    for offset in range(0, len(source) - block + 1, block):
        index.setdefault(source[offset:offset + block], offset)
    result = bytearray(MAGIC)
    pending = bytearray()
    def flush():
        if pending:
            result.extend(b'A' + struct.pack('<Q', len(pending)) + pending)
            pending.clear()
    pos = 0
    while pos < len(target):
        offset = index.get(target[pos:pos + block]) if pos + block <= len(target) else None
        if offset is None:
            pending.append(target[pos]); pos += 1; continue
        length = block
        while pos + length < len(target) and offset + length < len(source) and target[pos + length] == source[offset + length]:
            length += 1
        flush()
        result.extend(b'C' + struct.pack('<QQ', offset, length))
        pos += length
    flush()
    result.extend(b'E')
    return bytes(result)

def apply(source, delta, expected_size):
    if not 0 <= expected_size <= MAX_FILE_SIZE or not delta.startswith(MAGIC):
        raise ValueError('Invalid delta header or output size')
    pos = len(MAGIC); output = bytearray()
    def number():
        nonlocal pos
        if pos + 8 > len(delta): raise ValueError('Truncated delta')
        value = struct.unpack_from('<Q', delta, pos)[0]; pos += 8
        return value
    while pos < len(delta):
        opcode = delta[pos:pos + 1]; pos += 1
        if opcode == b'E':
            if pos != len(delta) or len(output) != expected_size: raise ValueError('Invalid delta ending')
            return bytes(output)
        if opcode == b'C':
            offset, length = number(), number()
            if offset > len(source) or length > len(source) - offset: raise ValueError('Copy outside source')
            fragment = source[offset:offset + length]
        elif opcode == b'A':
            length = number()
            if length > len(delta) - pos: raise ValueError('Insert outside delta')
            fragment = delta[pos:pos + length]; pos += length
        else:
            raise ValueError('Unknown delta opcode')
        if len(fragment) > expected_size - len(output): raise ValueError('Delta output exceeds expected size')
        output.extend(fragment)
    raise ValueError('Missing delta ending')
