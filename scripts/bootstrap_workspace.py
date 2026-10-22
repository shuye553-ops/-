"""Initialize a text-only checkout with explicitly provided local inputs."""
import argparse
import hashlib
import json
import shutil
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ['masterbank.bank', 'masterbank.assets.bank', 'masterbank.strings.bank',
        'tanks_engines.bank', 'tanks_engines.assets.bank']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['baseline', 'audio', 'reference', 'fmod', 'vgmstream', 'runtime']:
        p.add_argument('--'+name, required=True, type=Path)
    a = p.parse_args()
    assert not (ROOT/'workspace.local.json').exists(), 'Already configured; inspect existing workspace instead'
    assert not (ROOT/'work/fmod-reference').exists(), 'Work reference already exists'
    inputs = {k: v.resolve() for k, v in vars(a).items()}
    assert all(v.exists() for v in inputs.values()), 'Missing input/tool'
    reference = inputs['reference']
    assert (reference/'sounds.fspro').is_file(), 'Expected sounds.fspro'
    assert (reference/'Metadata/Event/{95513cdf-5279-45f2-9f85-0a1bd553c74f}.xml').is_file()
    for folder, ident in [('BankFolder','48173a23-aee7-43d3-8c5d-444e218594e8'),
                          ('Asset','81dc2e2f-1fe8-4962-9976-ac27d7c0b961')]:
        assert any(ident in f.read_text(encoding='utf-8-sig') for f in (reference/'Metadata'/folder).glob('*.xml')), folder
    contract = json.loads((ROOT/'contracts/baseline_manifest.json').read_text(encoding='utf-8'))
    manifest = []
    for item in contract:
        path = inputs['baseline']/item['name']
        if not path.exists() and item['name'] not in CORE: continue
        with path.open('rb') as stream: actual = hashlib.file_digest(stream,'sha256').hexdigest()
        assert actual == item['sha256'], f'Baseline mismatch: {path}'
        manifest.append(item)
    assert set(CORE) <= {x['name'] for x in manifest}
    audio_fingerprints = []
    for name in ['dist_120m','dist_160m','dist_200m']:
        path = inputs['audio']/(name+'.wav')
        with wave.open(str(path),'rb') as w:
            assert (w.getframerate(),w.getnchannels(),w.getsampwidth()) == (24000,1,2), path
            assert w.getnframes() > 240, 'Recording too short for edge fades'
            audio_fingerprints.append({'name':path.name,'frames':w.getnframes(),
                                       'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    for name in ['fmod.dll','fmodstudio.dll','fmodL.dll','fmodstudioL.dll','include/fmod_common.h']:
        assert (inputs['runtime']/name).is_file(), name
    for folder in ['baseline/package','work','reports','source','source/native-compiled']:
        (ROOT/folder).mkdir(parents=True,exist_ok=True)
    for item in manifest:
        destination = ROOT/'baseline/package'/item['name']
        assert not destination.exists(), f'Refuse overwrite: {destination}'
        shutil.copy2(inputs['baseline']/item['name'], destination)
    (ROOT/'baseline/manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Copying reference to isolated work directory...', flush=True)
    shutil.copytree(reference, ROOT/'work/fmod-reference',
                    ignore=shutil.ignore_patterns('.git','Build','Scripts','.cache','.user','*.user'))
    config = {'audio_dir':str(inputs['audio']),'original_package_dir':str(inputs['baseline']),
              'reference_project_dir':'work/fmod-reference','fmod_cli':str(inputs['fmod']),
              'vgmstream_exe':str(inputs['vgmstream']),'runtime_dir':str(inputs['runtime']),
              'output_dir':'releases','python_exe':sys.executable,'verify_installed':False}
    (ROOT/'workspace.local.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'reports/bootstrap_inputs.json').write_text(json.dumps({'audio':audio_fingerprints,
        'baseline_files':len(manifest),'game_modified':False},indent=2),encoding='utf-8')
    print('Configured. Next: python -B scripts/reproduce.py --check-only')


if __name__ == '__main__': main()
