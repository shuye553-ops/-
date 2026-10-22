"""Rebuild a test bank set from a lossless baseline graph and explicit deltas.

This is a bank-container maintenance project, not a claim that the missing
original Studio authoring project has been recovered. Original opaque records
and compressed audio are retained; all changed fields are recorded.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import struct
import uuid
from pathlib import Path

from bank_format import (Bank, Chunk, array_field, encode_array, bus_volume_offset,
                         fsb_tables, guid, record_id)

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "baseline/package"
SOURCE = ROOT / "source"
OUT = ROOT / "test-package"
NAMESPACE = uuid.UUID("829787ec-818a-4d10-afc2-67439ab1e8e0")
VOICE_EVENT = uuid.UUID("e775566d-d1c7-46f5-aab3-22ee19f0a56c").bytes_le
FRIEND_HEADPHONES = uuid.UUID("3404369c-3c74-4a69-b1de-6fef51b0fd6b").bytes_le
FRIEND_TRACKS = uuid.UUID("f715a920-8a95-40ee-b666-3d931eccd0bb").bytes_le
ENEMY_STOPS = {
    uuid.UUID("76492747-06e9-46e7-8873-64bd910c3981").bytes_le: "abrams/engine_stop",
    uuid.UUID("7037c86b-b557-4526-a97d-547d19b1196b").bytes_le: "hstvl/engine_stop",
}


def stable(name):
    return uuid.uuid5(NAMESPACE, name).bytes_le


def sha(data):
    return hashlib.sha256(data).hexdigest()


def previous_float32(value):
    """Largest positive float32 below an inclusive FMOD threshold."""
    bits = struct.unpack("<I", struct.pack("<f", value))[0]
    assert value > 0
    return struct.unpack("<f", struct.pack("<I", bits-1))[0]


def indexed(bank, section):
    return {record_id(c): c for c in bank.records(section)}


def set_volume(bank, section, ident, old_value, value):
    record = indexed(bank, section)[ident]
    chunk = record.child("BUS ")
    offset = bus_volume_offset(chunk.payload)
    actual = struct.unpack_from("<f", chunk.payload, offset)[0]
    assert actual == old_value, (guid(ident), actual, old_value)
    raw = bytearray(chunk.payload)
    struct.pack_into("<f", raw, offset, value)
    chunk.payload = bytes(raw)
    return {"section": section, "object": guid(ident), "field": "base_volume_db",
            "offset_in_BUS_payload": offset, "before": old_value, "after": value}


def native_audio():
    path = SOURCE / "native-compiled/voice_additions.assets.bank"
    bank = Bank.read(path)
    fsbs = fsb_tables(path)
    assert len(fsbs) == 1
    raw = path.read_bytes()
    fsb = fsbs[0]
    blob = raw[fsb["offset"]:fsb["offset"]+60+fsb["header_size"]+fsb["name_size"]+fsb["data_size"]]
    waves = {}
    for wave in bank.records("WAVS"):
        _, fi, index, _ = struct.unpack_from("<HIII", wave.payload, 16)
        assert fi == 0
        sample = fsb["samples"][index]
        waves[sample["name"]] = {"wave": wave, "sample": sample}
    assert set(waves) == {"dist_120m", "dist_160m", "dist_200m"}, set(waves)
    return bank, blob, waves


def current_voice_map(asset_bank, fsbs):
    result = {}
    for wave in asset_bank.records("WAVS"):
        _, fi, index, _ = struct.unpack_from("<HIII", wave.payload, 16)
        name = fsbs[fi]["samples"][index]["name"]
        if name.startswith("dist_"):
            result[name] = wave.payload[:16]
    return result


def write_graph_source(bank, path):
    def convert(node):
        result = {"tag": node.tag.decode("ascii")}
        if node.kind:
            result["kind"] = node.kind.decode("ascii")
            result["children"] = [convert(c) for c in node.children]
        else:
            result["payload_hex"] = node.payload.hex()
        if node.padding:
            result["padding_hex"] = node.padding.hex()
        return result
    path.write_text(json.dumps(convert(bank.root), separators=(",", ":")), encoding="utf-8")


def rebuild_sound_chunks(bank, old_fsbs, new_blob):
    original_data = (BASE/"tanks_engines.assets.bank").read_bytes()
    blobs = [original_data[f["offset"]:f["offset"]+60+f["header_size"]+f["name_size"]+f["data_size"]]
             for f in old_fsbs] + [new_blob]
    # SNDH records contain absolute file offsets and exact FSB lengths.
    bank.project.child("SNDH").payload = encode_array([struct.pack("<II", 0, len(blob)) for blob in blobs], 8)
    bank.root.children[:] = [c for c in bank.root.children if c.tag != b"SND "]
    offset = 12 + sum(len(c.encode()) for c in bank.root.children)
    entries = []
    for blob in blobs:
        padding = (-(offset + 8)) % 32
        data = b"\0"*padding + blob
        chunk = Chunk(b"SND ", payload=data)
        entries.append(struct.pack("<II", offset+8+padding, len(blob)))
        bank.root.children.append(chunk)
        offset += len(chunk.encode())
    bank.project.child("SNDH").payload = encode_array(entries, 8)


def main():
    SOURCE.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    target = OUT / "sound/mod"
    target.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT/"baseline/manifest.json").read_text(encoding="utf-8-sig"))
    for entry in manifest:
        assert sha((BASE/entry["name"]).read_bytes()) == entry["sha256"]
    native_manifest = json.loads((SOURCE/"native-compiled/manifest.json").read_text(encoding="utf-8"))
    for entry in native_manifest["files"]:
        assert sha((SOURCE/"native-compiled"/entry["name"]).read_bytes()) == entry["sha256"]
    master = Bank.read(BASE/"masterbank.bank")
    tank = Bank.read(BASE/"tanks_engines.bank")
    assets = Bank.read(BASE/"tanks_engines.assets.bank")
    # The untouched graph is itself an editable, bit-exact reconstruction source.
    write_graph_source(master, SOURCE/"masterbank.baseline.riff.json")
    write_graph_source(tank, SOURCE/"tanks_engines.baseline.riff.json")
    native, new_fsb, new_waves = native_audio()
    assert native.root.child("FMT ").payload == assets.root.child("FMT ").payload
    old_fsbs = fsb_tables(BASE/"tanks_engines.assets.bank")
    voice_waves = current_voice_map(assets, old_fsbs)
    wai = indexed(tank, "WAIS")
    existing_voices = {name: next(c for c in wai.values() if c.child("WAIB").payload[16:32] == wave)
                       for name, wave in voice_waves.items()}
    # Keep the extra duplicate rear-direction instrument as-is.
    event = indexed(tank, "EVTS")[VOICE_EVENT].child("EVTB").payload
    timeline = indexed(tank, "TLNS")[event[32:48]].child("TLNB")
    first_array, _, first_end = array_field(timeline.payload, 16)
    slots, stride, slots_end = array_field(timeline.payload, first_end)
    assert not first_array and stride == 24 and len(slots) == 15
    slots_by_id = {s[:16]: s for s in slots}
    distance_parameter = existing_voices["dist_140m"].child("INST").payload[-28:-12]
    pml = next(c for c in tank.records("PMLS")
               if record_id(existing_voices["dist_140m"]) in c.child("PMLB").payload)
    pmlb = pml.child("PMLB")
    modules, module_stride, modules_end = array_field(pmlb.payload, 32)
    assert module_stride == 16 and len(modules) == 15
    changes = []
    added_modules, added_slots = [], []
    original_windows = {}
    for name in ["dist_extreme_close", "dist_50m", "dist_80m", "dist_100m", "dist_140m", "dist_180m"]:
        inst = existing_voices[name].child("INST").payload
        assert len(inst) == 162 and inst[-28:-12] == distance_parameter
        original_windows[name] = list(struct.unpack_from("<ff", inst, len(inst)-8))
    wanted = [("dist_120m", "dist_100m", 120., 140.),
              ("dist_160m", "dist_140m", 160., 180.),
              ("dist_200m", "dist_180m", 200., 210.)]
    for name, old_name, lower, upper in wanted:
        original = existing_voices[old_name]
        old_id = record_id(original)
        assert original_windows[old_name][1] == upper
        clone = copy.deepcopy(original)
        new_id = stable(name+"/instrument")
        assert new_id not in wai
        native_wave = new_waves[name]["wave"]
        clone.child("WAIB").payload = new_id + native_wave.payload[:16]
        inst = bytearray(clone.child("INST").payload)
        struct.pack_into("<ff", inst, len(inst)-8, lower, upper)
        clone.child("INST").payload = bytes(inst)
        # Split the old range, retaining all other trigger flags and fields.
        old_inst = bytearray(original.child("INST").payload)
        # FMOD evaluates both condition endpoints inclusively. Exclude the new
        # threshold from the old instrument without leaving a float32 gap.
        struct.pack_into("<f", old_inst, len(old_inst)-4, previous_float32(lower))
        original.child("INST").payload = bytes(old_inst)
        tank.section("WAIS").children.append(clone)
        added_modules.append(new_id)
        sample = new_waves[name]["sample"]
        frequencies = [4000, 8000, 11025, 11000, 16000, 22050, 24000, 32000, 44100, 48000, 96000]
        frequency = frequencies[sample["frequency_index"]]
        ticks = round(sample["frame_count"]*48000/frequency)
        slot = bytearray(slots_by_id[old_id])
        slot[:16] = new_id
        struct.pack_into("<I", slot, 20, ticks)
        added_slots.append(bytes(slot))
        changes.append({"new_distance": name, "template": old_name,
                        "instrument": guid(new_id), "wave": guid(native_wave.payload),
                        "condition": [lower, upper], "timeline_start_seconds": struct.unpack_from("<I", slot, 16)[0]/48000,
                        "old_range_new_inclusive_maximum": previous_float32(lower),
                        "new_voice_seconds": ticks/48000})
    timeline.payload = (timeline.payload[:first_end] +
                        encode_array(sorted(slots+added_slots, key=lambda x:x[:16]), 24) +
                        timeline.payload[slots_end:])
    pmlb.payload = pmlb.payload[:32] + encode_array(sorted(modules+added_modules), 16) + pmlb.payload[modules_end:]
    tank.section("WAIS").children[1:] = sorted(tank.section("WAIS").children[1:], key=record_id)
    tank.update_count("WAIS")
    volume_changes = [set_volume(master, "GBSS", FRIEND_HEADPHONES, -8., -80.),
                      set_volume(master, "GBSS", FRIEND_TRACKS, -8., -80.)]
    native_master = Bank.read(SOURCE/"native-compiled/masterbank.bank")
    # Native compiler regenerates the two bus HASH values. All other sections
    # must exactly equal the independently patched baseline.
    for section in master.project.children:
        if section.tag != b"HASH":
            assert section.encode() == native_master.project.child(section.kind or section.tag).encode()
    master = native_master
    for ident, label in ENEMY_STOPS.items():
        change = set_volume(tank, "MBSS", ident, -80., -2.)
        change["event"] = label
        change["reference"] = "Gaijin official project EventMixerMaster volume approximately -2 dB"
        volume_changes.append(change)
    native_hashes, hash_stride, hash_end = array_field(native.project.child("HASH").payload, 0)
    assert hash_stride == 20 and hash_end == len(native.project.child("HASH").payload)
    hash_by_id = {h[:16]: h for h in native_hashes}
    asset_hashes, hash_stride, hash_end = array_field(assets.project.child("HASH").payload, 0)
    assert hash_stride == 20 and hash_end == len(assets.project.child("HASH").payload)
    for name in ["dist_120m", "dist_160m", "dist_200m"]:
        wave = copy.deepcopy(new_waves[name]["wave"])
        assert wave.payload[:16] not in {record_id(c) for c in assets.records("WAVS")}
        data = bytearray(wave.payload)
        struct.pack_into("<I", data, 18, len(old_fsbs))
        wave.payload = bytes(data)
        assets.section("WAVS").children.append(wave)
        asset_hashes.append(hash_by_id[wave.payload[:16]])
    assets.section("WAVS").children[1:] = sorted(assets.section("WAVS").children[1:], key=record_id)
    assets.update_count("WAVS")
    assets.project.child("HASH").payload = encode_array(sorted(asset_hashes, key=lambda x:x[:16]), 20)
    rebuild_sound_chunks(assets, old_fsbs, new_fsb)
    for name, bank in [("masterbank.bank", master), ("tanks_engines.bank", tank), ("tanks_engines.assets.bank", assets)]:
        (target/name).write_bytes(bank.encode())
        Bank.read(target/name)
    for name in ["masterbank.assets.bank", "masterbank.strings.bank"]:
        shutil.copy2(BASE/name, target/name)
    report = {"baseline_graph_roundtrip": "byte-identical", "voice_event": guid(VOICE_EVENT),
              "original_distance_windows": original_windows, "distance_changes": changes,
              "volume_changes": volume_changes,
              "master_bus_HASH_version_tags": "regenerated by FMOD Studio 2.02.22; only the two modified buses differ",
              "tank_event_HASH_version_tags": "preserved from baseline; semantics not decoded; runtime validation is recorded separately and bound to output SHA256",
              "new_wave_HASH_entries": "copied from FMOD Studio 2.02.22 native voice build",
              "validation_report": "reports/runtime_regression.json; valid only when tested_banks match output SHA256",
              "in_game_test": False,
              "qualification": "Independent experimental test package; original project and installation unchanged."}
    (ROOT/"reports/rebuild_changes.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (SOURCE/"update_spec.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
