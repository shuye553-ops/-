"""Extract the baseline voices and compile only the three new voice assets."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import struct
import subprocess
import uuid
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from bank_format import fsb_tables
from workspace_paths import AUDIO_DIR, REFERENCE_PROJECT, VGMSTREAM

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = uuid.UUID("829787ec-818a-4d10-afc2-67439ab1e8e0")


def stable(name):
    return "{" + str(uuid.uuid5(NAMESPACE, name)) + "}"


def read_wave(path):
    with wave.open(str(path), "rb") as stream:
        assert stream.getnchannels() == 1 and stream.getsampwidth() == 2
        assert stream.getframerate() == 24000
        return np.frombuffer(stream.readframes(stream.getnframes()), "<i2").astype(float) / 32768


def write_wave(path, audio):
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        stream.writeframes(np.rint(np.clip(audio, -1, 32767/32768) * 32768).astype("<i2").tobytes())


def set_prop(obj, key, value):
    node = obj.find(f"property[@name='{key}']")
    if node is None:
        node = ET.SubElement(obj, "property", {"name": key})
        ET.SubElement(node, "value")
    node.find("value").text = str(value)


def main():
    baseline = ROOT / "baseline/package/tanks_engines.assets.bank"
    fsb = fsb_tables(baseline)[0]
    raw = baseline.read_bytes()
    end = fsb["offset"] + 60 + fsb["header_size"] + fsb["name_size"] + fsb["data_size"]
    fsb_path = ROOT / "work/current_audio.fsb"
    fsb_path.write_bytes(raw[fsb["offset"]:end])
    output = ROOT / "source/current-voices"
    output.mkdir(parents=True, exist_ok=True)
    tool = VGMSTREAM
    voices = []
    for index, sample in enumerate(fsb["samples"]):
        if sample["name"].startswith("dist_"):
            path = output / (sample["name"] + ".wav")
            subprocess.run([str(tool), "-o", str(path), "-s", str(index+1), str(fsb_path)],
                           check=True, capture_output=True)
            audio = read_wave(path)
            voices.append({"name": sample["name"], "frames": len(audio),
                           "rms": float(np.sqrt(np.mean(audio**2))),
                           "peak": float(np.max(np.abs(audio)))})
    target_rms = float(np.median([x["rms"] for x in voices
                                 if x["name"] in ["dist_100m", "dist_140m", "dist_180m"]]))
    reference = REFERENCE_PROJECT
    asset_dir = reference / "Assets/vox_update"
    asset_dir.mkdir(exist_ok=True)
    new_voices = []
    normalized_dir = ROOT / "source/new-voices"
    normalized_dir.mkdir(exist_ok=True)
    bank_id = stable("voice_additions_bank")
    bank_objects = ET.Element("objects", {"serializationModel": "Studio.02.02.00"})
    bank = ET.SubElement(bank_objects, "object", {"class": "Bank", "id": bank_id})
    set_prop(bank, "name", "voice_additions")
    bank_folder = ET.SubElement(bank, "relationship", {"name": "folder"})
    ET.SubElement(bank_folder, "destination").text = "{48173a23-aee7-43d3-8c5d-444e218594e8}"
    ET.ElementTree(bank_objects).write(reference/"Metadata/Bank"/(bank_id+".xml"),
                                      encoding="UTF-8", xml_declaration=True)
    template_path = reference / "Metadata/Event/{95513cdf-5279-45f2-9f85-0a1bd553c74f}.xml"
    template = ET.parse(template_path).getroot()
    local_originals = ROOT/"source/local-voices-original"
    local_originals.mkdir(exist_ok=True)
    for name in ["dist_120m", "dist_160m", "dist_200m"]:
        source_path = AUDIO_DIR/(name+".wav")
        shutil.copy2(source_path, local_originals/source_path.name)
        audio = read_wave(source_path)
        source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        # Match the reference's RMS with a bounded soft limiter, only on new clips.
        low, high = 0., 100.
        for _ in range(40):
            gain = (low + high)/2
            transformed = .98 * np.tanh(gain * audio / .98)
            if np.sqrt(np.mean(transformed**2)) < target_rms:
                low = gain
            else:
                high = gain
        audio = .98 * np.tanh(high * audio / .98)
        fade = min(120, len(audio)//10)
        audio[:fade] *= np.linspace(0, 1, fade)
        audio[-fade:] *= np.linspace(1, 0, fade)
        wav_path = normalized_dir/(name+".wav")
        write_wave(wav_path, audio)
        shutil.copy2(wav_path, asset_dir/wav_path.name)
        audio_id = stable(name+"/audio")
        metadata = ET.Element("objects", {"serializationModel": "Studio.02.02.00"})
        af = ET.SubElement(metadata, "object", {"class": "AudioFile", "id": audio_id})
        for key, value in {"assetPath": "vox_update/"+wav_path.name,
                           "frequencyInKHz": 24, "channelCount": 1,
                           "length": len(audio)/24000}.items():
            set_prop(af, key, value)
        relationship = ET.SubElement(af, "relationship", {"name": "masterAssetFolder"})
        ET.SubElement(relationship, "destination").text = "{81dc2e2f-1fe8-4962-9976-ac27d7c0b961}"
        ET.ElementTree(metadata).write(reference/"Metadata/AudioFile"/(audio_id+".xml"),
                                      encoding="UTF-8", xml_declaration=True)
        event = copy.deepcopy(template)
        remap = {obj.get("id"): stable(name+"/"+obj.get("id")) for obj in event.findall("object")}
        for obj in event.findall("object"):
            obj.set("id", remap[obj.get("id")])
            for dest in obj.findall("relationship/destination"):
                dest.text = remap.get(dest.text, dest.text)
            if obj.get("class") == "Event":
                set_prop(obj, "name", name)
                for destination in obj.findall("relationship[@name='banks']/destination"):
                    destination.text = bank_id
            if obj.get("class") == "SingleSound":
                set_prop(obj, "length", len(audio)/24000)
                obj.find("relationship[@name='audioFile']/destination").text = audio_id
        event_obj = next(x for x in event.findall("object") if x.get("class") == "Event")
        ET.ElementTree(event).write(reference/"Metadata/Event"/(event_obj.get("id")+".xml"),
                                    encoding="UTF-8", xml_declaration=True)
        new_voices.append({"name": name, "audio_id": audio_id, "frames": len(audio),
                           "seconds": len(audio)/24000, "rms": float(np.sqrt(np.mean(audio**2))),
                           "peak": float(np.max(np.abs(audio))),
                           "voice": "user local recording", "source": str(source_path),
                           "source_sha256": source_sha256,
                           "source_frames_preserved": True,
                           "processing": "existing RMS matching, bounded soft limiter and 5ms edge fades; no speech synthesis, trimming or time stretch",
                           "voice_identity_matched": False})
    report = {"current_voices": voices, "new_voices": new_voices,
              "target_rms": target_rms,
              "qualification": "Original encoded clips stay byte-identical. Three additions use configured local recordings; only loudness and short edge fades are processed, with original lengths retained."}
    (ROOT/"reports/rebuilt_voice_assets.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
