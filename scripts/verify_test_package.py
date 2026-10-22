"""Verify the exact allowed graph differences and original audio preservation."""
from __future__ import annotations

import hashlib
import json
import math
import struct
import subprocess
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from workspace_paths import AUDIO_DIR, ORIGINAL_PACKAGE, GAME_MOD_DIR, VERIFY_INSTALLED, VGMSTREAM

from bank_format import Bank, array_field, bus_volume_offset, fsb_tables, guid, record_id
from build_test_package import (BASE, ROOT, VOICE_EVENT, FRIEND_HEADPHONES, FRIEND_TRACKS,
                                ENEMY_STOPS, indexed, stable, current_voice_map)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def volume(record):
    data = record.child("BUS ").payload
    return struct.unpack_from("<f", data, bus_volume_offset(data))[0]


def assert_volume_only(before, after, value):
    a = before.child("BUS ").payload
    b = after.child("BUS ").payload
    offset = bus_volume_offset(a)
    assert a[:offset] == b[:offset] and a[offset+4:] == b[offset+4:]
    assert volume(after) == value
    for ca, cb in zip(before.children, after.children):
        if ca.tag != b"BUS ":
            assert ca.encode() == cb.encode()


def main():
    target = ROOT/"test-package/sound/mod"
    before = {name: Bank.read(BASE/name) for name in ["masterbank.bank", "tanks_engines.bank", "tanks_engines.assets.bank"]}
    after = {name: Bank.read(target/name) for name in before}
    orig_tank, new_tank = before["tanks_engines.bank"], after["tanks_engines.bank"]
    orig_master, new_master = before["masterbank.bank"], after["masterbank.bank"]
    changes = json.loads((ROOT/"reports/rebuild_changes.json").read_text(encoding="utf-8"))
    allowed_ids = {
        "WAIS": {bytes.fromhex("")}, "TLNS": set(), "PMLS": set(), "MBSS": set(ENEMY_STOPS),
    }
    orig_fsbs = fsb_tables(BASE/"tanks_engines.assets.bank")
    names = current_voice_map(before["tanks_engines.assets.bank"], orig_fsbs)
    old_wai = indexed(orig_tank, "WAIS")
    original_by_name = {name: next(c for c in old_wai.values() if c.child("WAIB").payload[16:32] == wid)
                        for name, wid in names.items()}
    allowed_ids["WAIS"] = {record_id(original_by_name[n]) for n in ["dist_100m", "dist_140m", "dist_180m"]}
    old_voice_event = indexed(orig_tank, "EVTS")[VOICE_EVENT].child("EVTB").payload
    allowed_ids["TLNS"].add(old_voice_event[32:48])
    allowed_ids["PMLS"] = {record_id(c) for c in orig_tank.records("PMLS")
                           if record_id(original_by_name["dist_140m"]) in c.child("PMLB").payload}
    assert len(allowed_ids["PMLS"]) == 1
    graph_diffs = {}
    for section_node in orig_tank.project.children:
        if not section_node.kind:
            assert section_node.encode() == new_tank.project.child(section_node.tag).encode()
            continue
        section = section_node.kind.decode("ascii")
        a, b = indexed(orig_tank, section), indexed(new_tank, section)
        extra, removed = b.keys()-a.keys(), a.keys()-b.keys()
        changed = {k for k in a.keys() & b.keys() if a[k].encode() != b[k].encode()}
        assert not removed
        if section == "WAIS":
            assert extra == {stable(n+"/instrument") for n in ["dist_120m", "dist_160m", "dist_200m"]}
        else:
            assert not extra
        assert changed == allowed_ids.get(section, set()), (section, [guid(k) for k in changed])
        graph_diffs[section] = {"unchanged": len(a)-len(changed), "changed": [guid(k) for k in sorted(changed)],
                                "added": [guid(k) for k in sorted(extra)]}
        count = next((c for c in new_tank.section(section).children if c.tag == b"LCNT"), None)
        if count:
            assert struct.unpack("<I", count.payload)[0] == len(b)
    for section_node in orig_master.project.children:
        if section_node.kind != b"GBSS" and section_node.tag != b"HASH":
            assert section_node.encode() == new_master.project.child(section_node.kind or section_node.tag).encode()
    assert (target/"masterbank.bank").read_bytes() == (ROOT/"source/native-compiled/masterbank.bank").read_bytes()
    old_hashes, _, _ = array_field(orig_master.project.child("HASH").payload, 0)
    new_hashes, _, _ = array_field(new_master.project.child("HASH").payload, 0)
    old_hashes = {x[:16]: x[16:] for x in old_hashes}
    new_hashes = {x[:16]: x[16:] for x in new_hashes}
    assert old_hashes.keys() == new_hashes.keys()
    assert {k for k in old_hashes if old_hashes[k] != new_hashes[k]} == {FRIEND_HEADPHONES, FRIEND_TRACKS}
    a, b = indexed(orig_master, "GBSS"), indexed(new_master, "GBSS")
    assert a.keys() == b.keys()
    changed = {k for k in a if a[k].encode() != b[k].encode()}
    assert changed == {FRIEND_HEADPHONES, FRIEND_TRACKS}
    for ident in changed:
        assert_volume_only(a[ident], b[ident], -80.)
    for ident in ENEMY_STOPS:
        assert_volume_only(indexed(orig_tank,"MBSS")[ident], indexed(new_tank,"MBSS")[ident], -2.)
    for name in ["dist_100m", "dist_140m", "dist_180m"]:
        a = original_by_name[name]
        b = indexed(new_tank,"WAIS")[record_id(a)]
        assert a.child("INST").payload[:-4] == b.child("INST").payload[:-4]
        for ca, cb in zip(a.children, b.children):
            if ca.tag != b"INST":
                assert ca.encode() == cb.encode()
    # Check every allowed timeline/parameter-list edit, including unchanged
    # headers and suffixes; adding records alone is insufficient verification.
    for ident in allowed_ids["TLNS"]:
        old_record, new_record = indexed(orig_tank,"TLNS")[ident], indexed(new_tank,"TLNS")[ident]
        old_payload, new_payload = old_record.child("TLNB").payload, new_record.child("TLNB").payload
        _, _, old_start = array_field(old_payload,16)
        _, _, new_start = array_field(new_payload,16)
        old_slots, old_stride, old_end = array_field(old_payload,old_start)
        new_slots, new_stride, new_end = array_field(new_payload,new_start)
        assert old_payload[:old_start] == new_payload[:new_start]
        assert old_payload[old_end:] == new_payload[new_end:] and old_stride == new_stride == 24
        assert len(old_slots)==15 and len(new_slots)==18 and set(old_slots) <= set(new_slots)
        for item in changes["distance_changes"]:
            old_id = record_id(original_by_name[item["template"]])
            new_id = stable(item["new_distance"]+"/instrument")
            old_slot = next(s for s in old_slots if s[:16]==old_id)
            new_slot = next(s for s in new_slots if s[:16]==new_id)
            assert new_slot[16:20]==old_slot[16:20]
            assert struct.unpack_from("<I",new_slot,20)[0]==round(item["new_voice_seconds"]*48000)
            old_wai = original_by_name[item["template"]]
            new_wai = indexed(new_tank,"WAIS")[new_id]
            assert old_wai.child("INST").payload[:-8]==new_wai.child("INST").payload[:-8]
            assert guid(new_wai.child("WAIB").payload[16:32])==item["wave"]
    for ident in allowed_ids["PMLS"]:
        old_payload=indexed(orig_tank,"PMLS")[ident].child("PMLB").payload
        new_payload=indexed(new_tank,"PMLS")[ident].child("PMLB").payload
        old_modules, old_stride, old_end=array_field(old_payload,32)
        new_modules, new_stride, new_end=array_field(new_payload,32)
        assert old_payload[:32]==new_payload[:32] and old_payload[old_end:]==new_payload[new_end:]
        assert old_stride==new_stride==16 and set(new_modules)-set(old_modules)=={stable(n+"/instrument") for n in ["dist_120m","dist_160m","dist_200m"]}
        assert len(new_modules)==len(old_modules)+3
    new_fsbs = fsb_tables(target/"tanks_engines.assets.bank")
    assert len(new_fsbs) == len(orig_fsbs)+1 == 3
    orig_raw = (BASE/"tanks_engines.assets.bank").read_bytes()
    new_raw = (target/"tanks_engines.assets.bank").read_bytes()
    original_fsb_proofs = []
    def raw_fsb(raw, fsb):
        end = fsb["offset"]+60+fsb["header_size"]+fsb["name_size"]+fsb["data_size"]
        return raw[fsb["offset"]:end]
    for a, b in zip(orig_fsbs,new_fsbs):
        old_blob, new_blob = raw_fsb(orig_raw,a), raw_fsb(new_raw,b)
        assert old_blob == new_blob
        original_fsb_proofs.append({"samples": a["count"], "sha256": sha(old_blob), "byte_identical": True})
    a = indexed(before["tanks_engines.assets.bank"],"WAVS")
    b = indexed(after["tanks_engines.assets.bank"],"WAVS")
    assert len(b)-len(a) == 3
    assert all(k in b and c.encode()==b[k].encode() for k,c in a.items())
    for record in b.values():
        field_type, bank_index, sample_index, flags = struct.unpack_from("<HIII",record.payload,16)
        assert field_type==12
        assert bank_index<len(new_fsbs) and sample_index<new_fsbs[bank_index]["count"]
        if record_id(record) not in a:
            assert bank_index==2
    sndh, stride, end = array_field(after["tanks_engines.assets.bank"].project.child("SNDH").payload,0)
    assert stride == 8 and len(sndh) == 3
    for item, fsb in zip(sndh,new_fsbs):
        off, size = struct.unpack("<II",item)
        assert off == fsb["offset"] and size == len(raw_fsb(new_raw,fsb)) and off%32 == 0
    check_dir = ROOT/"work/decoded-test-voices"
    check_dir.mkdir(exist_ok=True)
    fsb_file = check_dir/"new_voices.fsb"
    fsb_file.write_bytes(raw_fsb(new_raw,new_fsbs[-1]))
    audio_checks = []
    for index,sample in enumerate(new_fsbs[-1]["samples"]):
        name = sample["name"]
        path = check_dir/(name+".wav")
        subprocess.run([str(VGMSTREAM),"-o",str(path),"-s",str(index+1),str(fsb_file)],
                       check=True,capture_output=True)
        def read(p):
            with wave.open(str(p),"rb") as w:
                assert w.getframerate()==24000 and w.getnchannels()==1 and w.getsampwidth()==2
                return np.frombuffer(w.readframes(w.getnframes()),"<i2").astype(float)/32768
        decoded, source = read(path), read(ROOT/"source/new-voices"/(name+".wav"))
        difference = 20*math.log10(float(np.sqrt(np.mean(decoded**2)))/float(np.sqrt(np.mean(source**2))))
        assert abs(difference) < 1.0 and abs(len(decoded)-len(source)) <= 1
        assert max(abs(decoded)) <= 1
        audio_checks.append({"name":name,"decoded_frames":len(decoded),"rms_difference_db":difference,
                             "decoded_successfully":True})
    windows = []
    for rec in new_tank.records("WAIS"):
        wave_id = rec.child("WAIB").payload[16:32]
        inst = rec.child("INST").payload
        distance = None
        for name, original_wave_id in names.items():
            if original_wave_id == wave_id and name in changes["original_distance_windows"]:
                distance = name
        for item in changes["distance_changes"]:
            if guid(wave_id)==item["wave"]:
                distance = item["new_distance"]
        if distance:
            low, high = struct.unpack_from("<ff",inst,len(inst)-8)
            windows.append({"name":distance,"low":low,"high":high})
    windows.sort(key=lambda x:x["low"])
    assert [w["low"] for w in windows] == [0,30,65,100,120,140,160,180,200]
    assert [w["high"] for w in windows] == [30,65,100,float(np.nextafter(np.float32(120),np.float32(-np.inf))),140,
                                          float(np.nextafter(np.float32(160),np.float32(-np.inf))),180,
                                          float(np.nextafter(np.float32(200),np.float32(-np.inf))),210]
    # Runtime confirmed inclusive conditions. Preserve old overlap behavior at
    # old thresholds; require exactly one instrument at each new threshold.
    points = [0.,29.999,30.,64.999,65.,99.999,100.,119.999,120.,139.999,140.,159.999,160.,179.999,180.,199.999,200.,209.999]
    for point in points:
        point=float(np.float32(point))
        expected=2 if point in [30,65,100,140,180] else 1
        assert len([w for w in windows if w["low"]<=point<=w["high"]])==expected
    for threshold in [120,160,200]:
        for point in [float(np.nextafter(np.float32(threshold),np.float32(-np.inf))),float(threshold),
                      float(np.nextafter(np.float32(threshold),np.float32(np.inf)))]:
            assert sum(w["low"]<=point<=w["high"] for w in windows)==1
    original_instances = [c for c in orig_tank.records("EVIS") if c.child("EVIB").payload[16:32]==VOICE_EVENT]
    assert len(original_instances)==2952
    # EVIS, original parent timelines, all curves, conditions, and event limits have been compared above.
    raw_manifest = json.loads((ROOT/"baseline/manifest.json").read_text(encoding="utf-8-sig"))
    deployment_path=ROOT/"reports/deployment.latest.json"
    deployment=json.loads(deployment_path.read_text(encoding="utf-8")) if deployment_path.exists() else {}
    installed_hashes=deployment.get("newHashes",{}) if deployment.get("status")=="DEPLOYED" else {}
    check_bases=[BASE,ORIGINAL_PACKAGE]
    if VERIFY_INSTALLED:
        assert GAME_MOD_DIR is not None
        check_bases.append(GAME_MOD_DIR)
    for item in raw_manifest:
        for base in check_bases:
            expected=installed_hashes.get(item["name"],item["sha256"]) if base==GAME_MOD_DIR else item["sha256"]
            with (base/item["name"]).open("rb") as stream:
                assert hashlib.file_digest(stream,"sha256").hexdigest()==expected
    local_voices=json.loads((ROOT/"reports/rebuilt_voice_assets.json").read_text(encoding="utf-8"))["new_voices"]
    for item in local_voices:
        assert sha(Path(item["source"]).read_bytes())==item["source_sha256"]
        assert sha((ROOT/"source/local-voices-original"/Path(item["source"]).name).read_bytes())==item["source_sha256"]
    bank_hashes={p.name:sha(p.read_bytes()) for p in target.glob("*.bank")}
    runtime_pass=True
    for report_name,expected_status in [("runtime-probe-test.json","PASS_BANK_LOAD_AND_SAMPLE_LOAD"),
                                       ("runtime_regression.json","PASS_RUNTIME_LOAD_AND_OFFLINE_REGRESSION")]:
        report_path=ROOT/"reports"/report_name
        runtime_report=json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        runtime_pass=runtime_pass and runtime_report.get("status")==expected_status and runtime_report.get("tested_banks")==bank_hashes
    result = {"status":"PASS_STATIC_AND_DECODED_AUDIO", "baseline_roundtrip":True,
              "event_definitions_unchanged":len(orig_tank.records("EVTS")),
              "existing_repeat_instances_byte_identical":len(original_instances),
              "all_existing_curves_and_automation_byte_identical":True,
              "eight_direction_instruments_byte_identical":True,
              "original_audio_fsb_proofs":original_fsb_proofs,
              "original_wave_records_byte_identical":len(a),
              "new_voices":audio_checks,"distance_windows":windows,
              "graph_diffs":graph_diffs,"original_and_installed_banks_unchanged":True,
              "native_engine_bank_load_test":runtime_pass,"offline_playback_regression":runtime_pass,"in_game_test":False,
              "boundary_model_test":"PASS inclusive float32 coverage at new thresholds; original old-threshold overlaps preserved",
              "speaker_identity_matched":False}
    result["new_voice_source"]=str(AUDIO_DIR)+"; original lengths retained, loudness matched"
    result["installed_files_checked"]=VERIFY_INSTALLED
    result["installed_reference"]=deployment.get("timestamp","original baseline")
    (ROOT/"reports/test_package_verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    files=[]
    for path in sorted(target.glob("*.bank")):
        files.append({"path":str(path.relative_to(ROOT/"test-package")).replace("\\","/"),
                      "bytes":path.stat().st_size,"sha256":sha(path.read_bytes())})
    (ROOT/"test-package/manifest.json").write_text(json.dumps({"files":files,"verification":result["status"],
                                                              "runtime_verified":runtime_pass,
                                                              "in_game_verified":False},indent=2),encoding="utf-8")
    print(json.dumps({key:value for key,value in result.items() if key!="graph_diffs"},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
