"""Document the current compiled announcement graph without guessing new rules."""
from __future__ import annotations

import collections
import hashlib
import json
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from bank_format import Bank, array_field, bus_volume_offset, fsb_tables, guid, record_id
from build_test_package import ROOT, BASE, VOICE_EVENT, indexed, current_voice_map
from workspace_paths import REFERENCE_PROJECT


def conditions(payload, parameters):
    if len(payload) < 130:
        return {"opaque_hex":payload.hex()}
    size = struct.unpack_from("<I",payload,126)[0]
    data = payload[130:]
    if size != len(data) or size%32:
        return {"opaque_hex":data.hex(),"declared_bytes":size}
    result=[]
    for offset in range(0,size,32):
        block=data[offset:offset+32]
        parameter=block[4:20]
        result.append({"parameter":parameters.get(parameter,guid(parameter)),
                       "parameter_guid":guid(parameter),
                       "raw_kind_flags":block[:4].hex(),
                       "raw_comparison_flags":block[20:24].hex(),
                       "minimum":struct.unpack_from("<f",block,24)[0],
                       "maximum":struct.unpack_from("<f",block,28)[0]})
    return result


def source_event_names():
    metadata=REFERENCE_PROJECT/"Metadata"
    folders={}
    for path in (metadata/"EventFolder").glob("*.xml"):
        for obj in ET.parse(path).getroot().findall("object"):
            folders[obj.get("id")]=(obj.findtext("property[@name='name']/value",""),
                                    obj.findtext("relationship[@name='folder']/destination"))
    result={}
    for path in (metadata/"Event").glob("*.xml"):
        obj=next((x for x in ET.parse(path).getroot().findall("object") if x.get("class")=="Event"),None)
        if obj is None:
            continue
        ident=obj.findtext("relationship[@name='folder']/destination")
        parts=[]
        while ident in folders:
            name,ident=folders[ident]
            parts.insert(0,name)
        result[obj.get("id")]="/".join(parts+[obj.findtext("property[@name='name']/value","")])
    return result


def main():
    bank=Bank.read(BASE/"tanks_engines.bank")
    asset=Bank.read(BASE/"tanks_engines.assets.bank")
    fsbs=fsb_tables(BASE/"tanks_engines.assets.bank")
    wave_names={ident:name for name,ident in current_voice_map(asset,fsbs).items()}
    params={}
    for record in bank.records("PRMS"):
        data=record.child("PRMB").payload
        length=struct.unpack_from("<H",data,24)[0]
        params[data[:16]]=data[26:26+length].decode("utf-8")
    event_data=indexed(bank,"EVTS")[VOICE_EVENT].child("EVTB").payload
    timeline=indexed(bank,"TLNS")[event_data[32:48]].child("TLNB").payload
    arr1,_,end=array_field(timeline,16)
    arr2,_,end=array_field(timeline,end)
    slots={slot[:16]:slot for slot in arr1+arr2}
    voice_instruments=[]
    for record in bank.records("WAIS"):
        header=record.child("WAIB").payload
        if header[16:32] not in wave_names:
            continue
        slot=slots[header[:16]]
        voice_instruments.append({"instrument":guid(header),"sample":wave_names[header[16:32]],
                                  "start_seconds":struct.unpack_from("<I",slot,16)[0]/48000,
                                  "length_seconds":struct.unpack_from("<I",slot,20)[0]/48000,
                                  "conditions":conditions(record.child("INST").payload,params),
                                  "raw_record_sha256":hashlib.sha256(record.encode()).hexdigest()})
    calls={record_id(c):c for c in bank.records("EVIS") if c.child("EVIB").payload[16:32]==VOICE_EVENT}
    owner_events={c.child("EVTB").payload[32:48]:guid(record_id(c)) for c in bank.records("EVTS")}
    event_names=source_event_names()
    parent_schedules=[]
    for record in bank.records("TLNS"):
        data=record.child("TLNB").payload
        if not any(ident in data for ident in calls):
            continue
        first,_,end=array_field(data,16)
        second,_,end=array_field(data,end)
        schedule=[]
        for slot in first+second:
            if slot[:16] not in calls:
                continue
            module=calls[slot[:16]]
            schedule.append({"instance":guid(slot),
                             "start_seconds":struct.unpack_from("<I",slot,16)[0]/48000,
                             "length_seconds":struct.unpack_from("<I",slot,20)[0]/48000,
                             "conditions":conditions(module.child("INST").payload,params),
                             "raw_record_sha256":hashlib.sha256(module.encode()).hexdigest()})
        event_id=owner_events[data[:16]]
        parent_schedules.append({"event":event_id,"source_name_annotation":event_names.get(event_id),
                                 "timeline":guid(data),"instances":sorted(schedule,key=lambda x:(x["start_seconds"],x["instance"])),
                                 "timeline_sha256":hashlib.sha256(record.encode()).hexdigest()})
    assert len(parent_schedules)==72 and sum(len(p["instances"]) for p in parent_schedules)==2952
    assert all(len(p["instances"])==41 for p in parent_schedules)
    inventory=[]
    masters=indexed(bank,"MBSS")
    for rec in bank.records("EVTS"):
        data=rec.child("EVTB").payload
        name=event_names.get(guid(data))
        if not name or "/ground/engines/" not in name:
            continue
        master=masters[data[64:80]].child("BUS ").payload
        inventory.append({"event":guid(data),"path_annotation":name,
                          "role_annotation":"enemy" if "/_enemies/" in name else "friendly_ai" if "/ai/" in name else "self_or_shared",
                          "master_guid":guid(data[64:80]),
                          "compiled_master_db":struct.unpack_from("<f",master,bus_volume_offset(master))[0],
                          "runtime_verified":False})
    result={"voice_event":guid(VOICE_EVENT),"raw_event_header_hex":event_data.hex(),
            "voice_instruments":voice_instruments,"parent_schedules":parent_schedules,
            "parent_count":len(parent_schedules),"trigger_instance_count":len(calls),
            "repeat_rule":"The full 41-instance schedule and every encoded condition per parent are retained verbatim.",
            "time_unit":"48000 serialized ticks per second; verified against original sample durations",
            "qualification":"Names are annotations from historical XML; behavior comes from current bank bytes."}
    (ROOT/"source/current_announcement_logic.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    (ROOT/"reports/current_compiled_event_inventory.json").write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"parents":len(parent_schedules),"trigger_instances":len(calls),
                      "voice_instruments":voice_instruments,
                      "current_compiled_ground_events":len(inventory)},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
