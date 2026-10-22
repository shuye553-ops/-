"""Read-only workspace/input/install integrity checks, with a local report."""
import argparse
import hashlib
import json
import wave
from pathlib import Path
from workspace_paths import (ROOT,AUDIO_DIR,ORIGINAL_PACKAGE,OUTPUT_DIR,REFERENCE_PROJECT,
                             FMOD_CLI,VGMSTREAM,RUNTIME_DIR,GAME_MOD_DIR,VERIFY_INSTALLED)


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--inputs-only',action='store_true');args=parser.parse_args()
    required=[AUDIO_DIR,ORIGINAL_PACKAGE,REFERENCE_PROJECT,FMOD_CLI,VGMSTREAM,RUNTIME_DIR]
    for path in required:assert path is not None and path.exists(),f'Missing configured input/tool: {path}'
    assert (REFERENCE_PROJECT/'sounds.fspro').exists(),'Reference project must provide sounds.fspro'
    manifest=json.loads((ROOT/'baseline/manifest.json').read_text(encoding='utf-8-sig'))
    for item in manifest:
        for folder in [ROOT/'baseline/package',ORIGINAL_PACKAGE]:
            assert digest(folder/item['name'])==item['sha256'],str(folder/item['name'])
    audio=[]
    for name in ['dist_120m','dist_160m','dist_200m']:
        path=AUDIO_DIR/(name+'.wav')
        with wave.open(str(path),'rb') as stream:
            assert (stream.getframerate(),stream.getnchannels(),stream.getsampwidth())==(24000,1,2)
            audio.append({'name':path.name,'frames':stream.getnframes(),'sha256':digest(path)})
    for name in ['fmod.dll','fmodstudio.dll','fmodL.dll','fmodstudioL.dll','include/fmod_common.h']:
        assert (RUNTIME_DIR/name).is_file(),name
    installed=False
    if VERIFY_INSTALLED:
        assert GAME_MOD_DIR and GAME_MOD_DIR.is_dir()
        receipt_path=ROOT/'reports/deployment.latest.json'
        receipt=json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else {}
        hashes=receipt.get('newHashes',{}) if receipt.get('status')=='DEPLOYED' else {}
        for item in manifest:assert digest(GAME_MOD_DIR/item['name'])==hashes.get(item['name'],item['sha256'])
        installed=True
    if not args.inputs_only:
        native=json.loads((ROOT/'source/native-compiled/manifest.json').read_text(encoding='utf-8'))
        for item in native['files']:assert digest(ROOT/'source/native-compiled'/item['name'])==item['sha256']
        package=json.loads((ROOT/'test-package/manifest.json').read_text(encoding='utf-8'))
        for item in package['files']:assert digest(ROOT/'test-package'/item['path'])==item['sha256']
    report={'status':'PASS','root':str(ROOT),'audio':audio,'installed_checked':installed,
            'output':str(OUTPUT_DIR),'game_modified':False,'inputs_only':args.inputs_only}
    (ROOT/'reports').mkdir(exist_ok=True)
    (ROOT/'reports/workspace_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
