"""Package only verified independent outputs; never install anything."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import shutil
import struct
import zipfile
from pathlib import Path

from bank_format import Bank, bus_volume_offset
from build_test_package import ROOT, ENEMY_STOPS, indexed
from workspace_paths import OUTPUT_DIR

OUTPUT = OUTPUT_DIR


def sha_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def main():
    verification=json.loads((ROOT/"reports/test_package_verification.json").read_text(encoding="utf-8"))
    assert verification["status"]=="PASS_STATIC_AND_DECODED_AUDIO"
    assert verification["native_engine_bank_load_test"] and verification["offline_playback_regression"]
    package=ROOT/"test-package"
    manifest=json.loads((package/"manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["files"])==5
    for item in manifest["files"]:
        assert sha_file(package/item["path"])==item["sha256"]
    bank=Bank.read(package/"sound/mod/tanks_engines.bank")
    masters=indexed(bank,"MBSS")
    inventory=json.loads((ROOT/"reports/current_compiled_event_inventory.json").read_text(encoding="utf-8"))
    for item in inventory:
        import uuid
        ident=uuid.UUID(item["master_guid"].strip("{}")).bytes_le
        data=masters[ident].child("BUS ").payload
        item["test_master_db"]=struct.unpack_from("<f",data,bus_volume_offset(data))[0]
        item["change"]="enemy_stop_restore" if ident in ENEMY_STOPS else "event_unchanged"
        item["static_checked"]=True
        item["runtime_verified"]=False
        item["role_qualification"]="Historical XML name annotation; game vehicle mapping not verified"
    coverage={"counts":dict(collections.Counter(x["role_annotation"] for x in inventory)),
              "event_count":len(inventory),"events":inventory,
              "shared_bus_changes":[{"name":"friendly_ai_engine_headphones","before_db":-8,"after_db":-80},
                                    {"name":"friendly_ai_tracks","before_db":-8,"after_db":-80}],
              "all_vehicle_runtime_verified":False,
              "scope":"Current compiled bank event inventory; not a count or complete mapping of current game tank models"}
    (ROOT/"reports/compiled_coverage_after.json").write_text(json.dumps(coverage,ensure_ascii=False,indent=2),encoding="utf-8")
    with (ROOT/"reports/compiled_coverage_after.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(inventory[0]))
        writer.writeheader();writer.writerows(inventory)
    # Keep the first investigation's stopped state as historical evidence.
    old=ROOT/"reports/RESULTS.zh.md"
    if old.exists() and "BLOCKED_BASELINE" in old.read_text(encoding="utf-8"):
        shutil.copy2(old,ROOT/"reports/RESULTS.initial-blocked.zh.md")
    results=(ROOT/"source/RESULTS.current.zh.md").read_text(encoding="utf-8")
    old.write_text(results,encoding="utf-8")
    for source,destination in [(ROOT/"reports/test_package_verification.json",package/"verification.json"),
                               (ROOT/"reports/rebuild_changes.json",package/"changes.json"),
                               (ROOT/"reports/runtime_regression.json",package/"runtime_verification.json"),
                               (ROOT/"reports/runtime-probe-test.json",package/"runtime_load.json"),
                               (ROOT/"source/TESTING.zh.md",package/"TESTING.zh.md"),
                               (ROOT/"source/PACKAGE_README.zh.md",package/"README.zh.md")]:
        shutil.copy2(source,destination)
    preview=package/"preview"
    preview.mkdir(exist_ok=True)
    for path in (ROOT/"source/new-voices").glob("*.wav"):
        shutil.copy2(path,preview/path.name)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    archive=OUTPUT/"EchoContact-VOX-local-audio-20261022.zip"
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as target:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                target.write(path,path.relative_to(package).as_posix())
    # Verify archived bytes, not just the directory that was packaged.
    with zipfile.ZipFile(archive) as target:
        assert target.testzip() is None
        for item in manifest["files"]:
            with target.open(item["path"]) as stream:
                assert hashlib.file_digest(stream,"sha256").hexdigest()==item["sha256"]
    digest=sha_file(archive)
    (OUTPUT/(archive.name+".sha256")).write_text(digest+"  "+archive.name+"\n",encoding="ascii")
    deployment_path=ROOT/"reports/deployment.latest.json"
    deployment=json.loads(deployment_path.read_text(encoding="utf-8")) if deployment_path.exists() else {}
    deployed=deployment.get("status")=="DEPLOYED"
    receipt={"archive":str(archive),"bytes":archive.stat().st_size,"sha256":digest,
             "archive_crc_test":"PASS","archived_bank_sha256_test":"PASS",
             "bank_count":5,"game_installation_modified":deployed,
             "source_project":str(ROOT),"native_engine_bank_load_test":True,"offline_playback_regression":True,"in_game_test":False}
    (ROOT/"reports/delivery.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUTPUT/"delivery.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding="utf-8")
    final_path=ROOT/"reports/final_integrity_verification.json"
    final=json.loads(final_path.read_text(encoding="utf-8")) if final_path.exists() else {}
    final.update({"replacement_package_created":True,
                  "original_and_installed_banks_unchanged_at_predeployment_review":verification["original_and_installed_banks_unchanged"],
                  "original_and_installed_banks_unchanged":not deployed,
                  "independent_only":not deployed})
    (ROOT/"reports/final_integrity_verification.json").write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
