"""Build and verify independent outputs; this entry point never deploys."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script, *args):
    log = ROOT/'reports'/('reproduce-'+Path(script).stem+'.log')
    print('RUN', script, *args, flush=True)
    with log.open('w',encoding='utf-8') as stream:
        subprocess.run([sys.executable,'-B',str(ROOT/'scripts'/script),*args],cwd=ROOT,
                       stdout=stream,stderr=subprocess.STDOUT,check=True)


def native_encode():
    from workspace_paths import FMOD_CLI, REFERENCE_PROJECT
    profile = ROOT/'work/profile-reproduction'
    env = os.environ.copy()
    for variable, folder in [('APPDATA','roaming'),('LOCALAPPDATA','local'),('TEMP','temp'),('TMP','temp')]:
        path = profile/folder
        path.mkdir(parents=True,exist_ok=True)
        env[variable] = str(path)
    log = ROOT/'reports/native-reproduction-console.log'
    # Bank-specific scripting prevents rebuilding the complete reference sound set.
    command = [str(FMOD_CLI),'-script',str(ROOT/'scripts/compile_voice_bank.js'),
               str(REFERENCE_PROJECT/'sounds.fspro')]
    started = time.time()
    stopped_after_success = False
    with log.open('w',encoding='utf-8') as output:
        process = subprocess.Popen(command,cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            success_since = None
            while process.poll() is None:
                logs = [p for p in profile.rglob('*_log.txt') if p.stat().st_mtime >= started-2]
                text = '\n'.join(p.read_text(encoding='utf-8',errors='replace') for p in logs)
                text += log.read_text(encoding='utf-8',errors='replace')
                if 'VOICE_BANK_BUILD_SUCCESS=true' in text and 'Closing Logging' in text:
                    success_since = success_since or time.monotonic()
                    if time.monotonic()-success_since > 15:
                        process.terminate()
                        stopped_after_success = True
                        break
                if time.time()-started > 600: raise TimeoutError('Native voice encoding exceeded 600 seconds')
                time.sleep(1)
            code = process.wait(timeout=30)
        finally:
            if process.poll() is None:
                process.kill(); process.wait()
    logs = [p for p in profile.rglob('*_log.txt') if p.stat().st_mtime >= started-2]
    text = '\n'.join(p.read_text(encoding='utf-8',errors='replace') for p in logs)
    text += log.read_text(encoding='utf-8',errors='replace')
    assert 'VOICE_BANK_BUILD_SUCCESS=true' in text, 'Native log did not confirm build success'
    assert code == 0 or stopped_after_success, f'Unexpected native exit: {code}'
    outputs = [p for p in (REFERENCE_PROJECT/'Build').rglob('voice_additions.assets.bank')
               if p.stat().st_mtime >= started-2]
    assert len(outputs) == 1, f'Expected one fresh voice bank: {outputs}'
    target = ROOT/'source/native-compiled'
    shutil.copy2(outputs[0],target/'voice_additions.assets.bank')
    files = []
    for name in ['masterbank.bank','voice_additions.assets.bank']:
        path = target/name
        files.append({'name':name,'bytes':path.stat().st_size,
                      'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    report = {'compiler':'FMOD Studio 2.02.22','files':files,'voice_source':'configured local recordings',
              'master_source':'measured native master delta contract',
              'voice_build_log':str(log.relative_to(ROOT)),
              'native_exit_code':code,'own_process_stopped_after_success_log':stopped_after_success,
              'qualification':'Native encoding only; real loading and playback checks run separately'}
    (target/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (ROOT/'reports/native-reproduction.log').write_text(text,encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check-only',action='store_true')
    a=p.parse_args()
    run('check_workspace.py','--inputs-only')
    if a.check_only: return
    run('materialize_master.py')
    run('prepare_rebuild_audio.py')
    print('RUN native voice encoding',flush=True)
    native_encode()
    for script,args in [('recover_current_logic.py',[]),('build_test_package.py',[]),
                        ('runtime_probe.py',['--variant','test','--debug']),
                        ('runtime_regression.py',[]),('verify_test_package.py',[]),
                        ('package_delivery.py',[]),('check_workspace.py',[])]:
        run(script,*args)
    print('PASS independent package. No game deployment was performed.')


if __name__ == '__main__': main()
