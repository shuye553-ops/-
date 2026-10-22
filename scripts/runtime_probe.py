"""Load the baseline/test banks in an isolated FMOD process, without a device."""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from workspace_paths import RUNTIME_DIR, GAME_MOD_DIR, REFERENCE_PROJECT

ROOT=Path(__file__).resolve().parents[1]
P=C.c_void_p
I=C.c_int
U=C.c_uint
F=C.c_float


class Runtime:
    def __init__(self, output_type=4, output_path=None, debug=False):
        self.dir=RUNTIME_DIR
        self.search=os.add_dll_directory(str(self.dir))
        self.core=C.WinDLL(str(self.dir/('fmodL.dll' if debug else 'fmod.dll')))
        self.studio=C.WinDLL(str(self.dir/('fmodstudioL.dll' if debug else 'fmodstudio.dll')))
        common=(self.dir/'include/fmod_common.h').read_text(encoding='utf-8')
        enum=common[common.index('FMOD_OK'):common.index('FMOD_RESULT;')]
        self.errors=re.findall(r'^\s*(FMOD_(?:OK|ERR_\w+))\b',enum,re.M)
        self.calls=[]
        if debug:
            self.call('Debug_Initialize',7,1,None,b'reports/runtime-debug.log')
        self.system=P();self.core_system=P()
        self.call('Studio_System_Create',C.byref(self.system),0x00020214)
        self.call('Studio_System_GetCoreSystem',self.system,C.byref(self.core_system))
        version=U();self.call('System_GetVersion',self.core_system,C.byref(version))
        self.version=f'{version.value:08x}'
        self.call('System_SetOutput',self.core_system,output_type)
        self.call('System_SetSoftwareFormat',self.core_system,24000,3,0)
        self.call('System_SetDSPBufferSize',self.core_system,240,4)
        self.output_buffer=C.create_string_buffer(os.fsencode(output_path)) if output_path else None
        self.call('Studio_System_Initialize',self.system,512,4,3,self.output_buffer)
        self.banks=[]

    def call(self,name,*args,allow_error=False):
        library=self.studio if name.startswith('Studio_') else self.core
        fn=getattr(library,'FMOD_'+name)
        fn.restype=I
        fn.argtypes=[P if x is None or isinstance(x,(C.c_void_p,C.Array)) or hasattr(x,'_obj') else C.c_char_p if isinstance(x,bytes) else F if isinstance(x,float) else I for x in args]
        result=fn(*args)
        error=self.errors[result] if 0<=result<len(self.errors) else str(result)
        self.calls.append({'api':name,'result':result,'error':error})
        if result and not allow_error:
            raise RuntimeError(f'{name}: {error} ({result})')
        return result

    def load(self,folder):
        for name in ['masterbank.bank','masterbank.assets.bank','masterbank.strings.bank','tanks_engines.assets.bank','tanks_engines.bank']:
            bank=P()
            self.call('Studio_System_LoadBankFile',self.system,str(folder/name).encode('utf-8'),0,C.byref(bank))
            self.banks.append(bank)
        self.call('Studio_System_FlushCommands',self.system)

    def event(self,ident):
        desc=P();raw=C.create_string_buffer(uuid.UUID(ident.strip('{}')).bytes_le)
        self.call('Studio_System_GetEventByID',self.system,raw,C.byref(desc))
        return desc

    def close(self):
        try:
            self.call('Studio_System_Release',self.system)
        finally:
            self.search.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--variant',choices=['baseline','test','native','installed'],required=True)
    parser.add_argument('--debug',action='store_true')
    args=parser.parse_args()
    folder=ROOT/('baseline/package' if args.variant=='baseline' else 'test-package/sound/mod')
    if args.variant=='installed':
        assert GAME_MOD_DIR is not None,'Configure game_root before checking installed files'
        folder=GAME_MOD_DIR
    runtime=None
    report={'variant':args.variant,'status':'FAIL','game_launched':False}
    if args.variant!='native':
        report['tested_banks']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob('*.bank')}
    try:
        runtime=Runtime(debug=args.debug)
        report['runtime_version_hex']=runtime.version
        if args.variant=='native':
            native=REFERENCE_PROJECT/'Build/sound'
            for name in ['masterbank.bank','masterbank.assets.bank','voice_additions.assets.bank','voice_additions.bank']:
                bank=P();runtime.call('Studio_System_LoadBankFile',runtime.system,str(native/name).encode('utf-8'),0,C.byref(bank));runtime.banks.append(bank)
        else:
            runtime.load(folder)
        count=I();runtime.call('Studio_Bank_GetEventCount',runtime.banks[-1],C.byref(count))
        assert count.value==(3 if args.variant=='native' else 1025),count.value
        if args.variant=='native':
            import xml.etree.ElementTree as ET
            event_id=next(obj.get('id') for path in (REFERENCE_PROJECT/'Metadata/Event').glob('*.xml')
                          for obj in ET.parse(path).getroot().findall('object')
                          if obj.get('class')=='Event' and obj.findtext("property[@name='name']/value")=="dist_120m")
        else:
            event_id='e775566d-d1c7-46f5-aab3-22ee19f0a56c'
        event=runtime.event(event_id)
        runtime.call('Studio_EventDescription_LoadSampleData',event)
        runtime.call('Studio_System_FlushSampleLoading',runtime.system)
        state=I();runtime.call('Studio_EventDescription_GetSampleLoadingState',event,C.byref(state))
        assert state.value==3, state.value
        instance=P();runtime.call('Studio_EventDescription_CreateInstance',event,C.byref(instance))
        runtime.call('Studio_EventInstance_Start',instance)
        for _ in range(500):
            runtime.call('Studio_System_Update',runtime.system)
            runtime.call('System_Update',runtime.core_system)
        runtime.call('Studio_EventInstance_Stop',instance,1)
        runtime.call('Studio_EventInstance_Release',instance)
        report.update(status='PASS_BANK_LOAD_AND_SAMPLE_LOAD',event_count=count.value,sample_loading_state=state.value)
    except Exception as error:
        report['error']=str(error)
    finally:
        if runtime:
            try: runtime.close()
            except Exception as error: report['release_error']=str(error)
            report['calls']=runtime.calls
        (ROOT/f'reports/runtime-probe-{args.variant}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='calls'},indent=2))
    if report['status'].startswith('FAIL'):raise SystemExit(1)


if __name__=='__main__':main()
