"""Replay the measured native master delta, never infer opaque HASH semantics."""
import hashlib
import json
import struct
import uuid
from pathlib import Path
from bank_format import Bank, array_field, encode_array, bus_volume_offset, record_id

ROOT = Path(__file__).resolve().parents[1]


def main():
    contract = json.loads((ROOT/'contracts/native_master_delta.json').read_text(encoding='utf-8'))
    path = ROOT/'baseline/package/masterbank.bank'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == contract['baseline_sha256']
    bank = Bank.read(path)
    records = {record_id(x): x for x in bank.records('GBSS')}
    tags, stride, end = array_field(bank.project.child('HASH').payload, 0)
    assert stride == 20 and end == len(bank.project.child('HASH').payload)
    for change in contract['changes']:
        ident = uuid.UUID(change['guid'].strip('{}')).bytes_le
        chunk = records[ident].child('BUS ')
        data = bytearray(chunk.payload)
        offset = bus_volume_offset(data)
        assert struct.unpack_from('<f', data, offset)[0] == change['before_db']
        struct.pack_into('<f', data, offset, change['after_db'])
        chunk.payload = bytes(data)
        indices = [i for i, tag in enumerate(tags) if tag[:16] == ident]
        assert len(indices) == 1
        i = indices[0]
        assert tags[i][16:].hex() == change['before_hash_tag_hex']
        tags[i] = ident + bytes.fromhex(change['after_hash_tag_hex'])
    bank.project.child('HASH').payload = encode_array(tags, 20)
    output = bank.encode()
    assert hashlib.sha256(output).hexdigest() == contract['output_sha256']
    target = ROOT/'source/native-compiled'
    target.mkdir(parents=True, exist_ok=True)
    (target/'masterbank.bank').write_bytes(output)
    print('PASS measured native master delta and complete output SHA256')


if __name__ == '__main__': main()
