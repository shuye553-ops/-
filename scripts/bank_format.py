"""Lossless RIFF/FEV container reader. Unknown payloads are kept verbatim."""
from __future__ import annotations

from dataclasses import dataclass, field
import struct
import uuid
from pathlib import Path


@dataclass
class Chunk:
    tag: bytes
    payload: bytes = b""
    kind: bytes | None = None
    children: list["Chunk"] = field(default_factory=list)
    padding: bytes = b""

    def encode(self):
        data = self.kind + b"".join(c.encode() for c in self.children) if self.kind else self.payload
        return self.tag + struct.pack("<I", len(data)) + data + (self.padding or b"\0" if len(data) % 2 else b"")

    def child(self, name):
        name = name.encode("ascii") if isinstance(name, str) else name
        return next(c for c in self.children if c.tag == name or c.kind == name)

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def parse_chunks(data, start, end):
    children = []
    pos = start
    while pos < end:
        if pos + 8 > end:
            raise ValueError(f"Truncated chunk at {pos}")
        tag, size = struct.unpack_from("<4sI", data, pos)
        low, high = pos + 8, pos + 8 + size
        if high > end:
            raise ValueError(f"Chunk {tag!r} at {pos} crosses parent boundary")
        pad = data[high:high+1] if size % 2 else b""
        if tag in [b"RIFF", b"LIST"]:
            if size < 4:
                raise ValueError("Container lacks type")
            child = Chunk(tag=tag, kind=data[low:low+4],
                          children=parse_chunks(data, low+4, high), padding=pad)
        else:
            child = Chunk(tag=tag, payload=data[low:high], padding=pad)
        children.append(child)
        pos = high + size % 2
    if pos != end:
        raise ValueError("Invalid padding")
    return children


@dataclass
class Bank:
    root: Chunk
    trailer: bytes = b""

    @classmethod
    def read(cls, path):
        data = Path(path).read_bytes()
        if data[:4] != b"RIFF" or data[8:12] != b"FEV ":
            raise ValueError("Not a little-endian FEV bank")
        end = struct.unpack_from("<I", data, 4)[0] + 8
        roots = parse_chunks(data, 0, end)
        assert len(roots) == 1
        bank = cls(roots[0], data[end:])
        if bank.encode() != data:
            raise ValueError("Lossless round-trip failed")
        return bank

    def encode(self):
        return self.root.encode() + self.trailer

    @property
    def project(self):
        return self.root.child("PROJ")

    def section(self, name):
        return self.project.child(name)

    def records(self, section):
        return [c for c in self.section(section).children if c.tag != b"LCNT"]

    def update_count(self, section):
        node = self.section(section)
        count = sum(c.tag != b"LCNT" for c in node.children)
        node.child("LCNT").payload = struct.pack("<I", count)


def guid(data):
    return "{" + str(uuid.UUID(bytes_le=data[:16])) + "}"


def array_field(data, pos):
    tag = struct.unpack_from("<H", data, pos)[0]
    if not tag & 1:
        raise ValueError(f"Unsupported array encoding at {pos}: {tag}")
    count = tag >> 1
    pos += 2
    if not count:
        return [], 0, pos
    stride = struct.unpack_from("<H", data, pos)[0]
    pos += 2
    values = [data[pos+i*stride:pos+(i+1)*stride] for i in range(count)]
    if any(len(x) != stride for x in values):
        raise ValueError("Truncated array")
    return values, stride, pos + count*stride


def encode_array(values, stride):
    if not values:
        return struct.pack("<H", 1)
    if len(values) > 32767 or any(len(x) != stride for x in values):
        raise ValueError("Invalid array")
    return struct.pack("<HH", len(values)*2+1, stride) + b"".join(values)


def bus_volume_offset(payload):
    _, _, pos = array_field(payload, 8)
    _, _, pos = array_field(payload, pos)
    if struct.unpack_from("<H", payload, pos)[0] != 8:
        raise ValueError("Unexpected bus volume field")
    return pos + 2


def record_id(record):
    return (record.children[0].payload if record.children else record.payload)[:16]


def fsb_tables(path):
    data = Path(path).read_bytes()
    result = []
    import re
    for match in re.finditer(b"FSB5", data):
        off = match.start()
        if off + 60 > len(data):
            continue
        version, count, hs, ns, ds, mode = struct.unpack_from("<6I", data, off+4)
        if version != 1 or not 0 < count < 100000 or ns < 4 * count:
            continue
        table = off + 60 + hs
        if table + ns + ds > len(data):
            continue
        names = []
        for x in struct.unpack_from(f"<{count}I", data, table):
            start = table + x
            end = data.index(b"\0", start, table+ns)
            names.append(data[start:end].decode("utf-8"))
        samples, pos = [], off + 60
        for index in range(count):
            start = pos
            bits = struct.unpack_from("<Q", data, pos)[0]
            pos += 8
            more = bits & 1
            extras = []
            while more:
                value = struct.unpack_from("<I", data, pos)[0]
                more, size, typ = value & 1, (value >> 1) & 0xffffff, value >> 25
                pos += 4
                extras.append((typ, data[pos:pos+size]))
                pos += size
            samples.append({"name": names[index], "bits": bits,
                            "frequency_index": (bits >> 1) & 15,
                            "channels": ((bits >> 5) & 1) + 1,
                            "data_offset": ((bits >> 6) & 0xfffffff) * 32,
                            "frame_count": bits >> 34,
                            "header": data[start:pos], "extras": extras})
        if pos != off + 60 + hs:
            raise ValueError("FSB sample header parsing mismatch")
        for index, sample in enumerate(samples):
            end = samples[index+1]["data_offset"] if index+1 < count else ds
            sample["data"] = data[table+ns+sample["data_offset"]:table+ns+end]
        result.append({"offset": off, "count": count, "header_size": hs,
                       "name_size": ns, "data_size": ds, "mode": mode,
                       "header": data[off:off+60], "samples": samples})
    return result
