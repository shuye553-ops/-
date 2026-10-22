"""Exercise real FMOD voice triggers using 3D positions and offline mixing."""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import math
import wave
from pathlib import Path

from runtime_probe import Runtime,ROOT,P,I,U,F

VOICE='e775566d-d1c7-46f5-aab3-22ee19f0a56c'


class Vector(C.Structure):
    _fields_=[('x',F),('y',F),('z',F)]


class Attributes(C.Structure):
    _fields_=[('position',Vector),('velocity',Vector),('forward',Vector),('up',Vector)]


class Parameter(C.Structure):
    _fields_=[('name',C.c_char_p),('id',U*2),('minimum',F),('maximum',F),('default',F),
              ('type',I),('flags',U),('guid',C.c_byte*16)]


def attributes(distance,angle):
    radians=math.radians(angle)
    return Attributes(Vector(distance*math.sin(radians),0,distance*math.cos(radians)),
                      Vector(0,0,0),Vector(0,0,1),Vector(0,1,0))


def render(variant,distance,angle,parent=None,seconds=3.5,label=None,trajectory=None,headphones=0,parameter_overrides=None,snapshots=None,extra_banks=None):
    label=label or f'd{distance:g}_a{angle:g}'
    output=ROOT/'work/runtime-audio'/variant/(label+'.wav')
    output.parent.mkdir(parents=True,exist_ok=True)
    relative=output.relative_to(ROOT).as_posix()
    runtime=Runtime(5,relative)
    sounds=[];errors=[];parent_instance=P();clock=C.c_ulonglong();parent_clock=C.c_ulonglong();master=P()
    callback_type=C.WINFUNCTYPE(I,U,P,P)
    def callback(kind,event,parameters):
        try:
            if kind==0x2000:
                name=C.create_string_buffer(512)
                runtime.call('Sound_GetName',P(parameters),name,len(name))
                timeline=I();runtime.call('Studio_EventInstance_GetTimelinePosition',event,C.byref(timeline))
                runtime.call('ChannelGroup_GetDSPClock',master,C.byref(clock),C.byref(parent_clock))
                parent_position=I()
                if parent_instance.value:
                    runtime.call('Studio_EventInstance_GetTimelinePosition',parent_instance,C.byref(parent_position))
                sounds.append({'sample':name.value.decode('utf-8'), 'voice_timeline_ms':timeline.value,
                               'dsp_clock':clock.value,'parent_timeline_ms':parent_position.value})
        except Exception as error:errors.append(str(error))
        return 0
    callback_ref=callback_type(callback)
    try:
        runtime.load(ROOT/('baseline/package' if variant=='baseline' else 'test-package/sound/mod'))
        for bank_path in (extra_banks or []):
            extra_bank=P()
            runtime.call('Studio_System_LoadBankFile',runtime.system,str(bank_path).encode('utf-8'),0,C.byref(extra_bank))
            runtime.banks.append(extra_bank)
        runtime.call('Studio_System_SetParameterByName',runtime.system,b'headphones',float(headphones),1)
        runtime.call('System_GetMasterChannelGroup',runtime.core_system,C.byref(master))
        listener=attributes(0,0)
        runtime.call('Studio_System_SetListenerAttributes',runtime.system,0,C.byref(listener),None)
        for snapshot in (snapshots or []):
            snapshot_desc=runtime.event(snapshot)
            snapshot_instance=P()
            runtime.call('Studio_EventDescription_CreateInstance',snapshot_desc,C.byref(snapshot_instance))
            runtime.call('Studio_EventInstance_Start',snapshot_instance)
            runtime.call('Studio_EventInstance_Release',snapshot_instance)
        voice=runtime.event(VOICE)
        runtime.call('Studio_EventDescription_SetCallback',voice,C.cast(callback_ref,P),0x2000)
        desc=runtime.event(parent) if parent else voice
        runtime.call('Studio_EventDescription_LoadSampleData',desc)
        runtime.call('Studio_System_FlushSampleLoading',runtime.system)
        state=I();runtime.call('Studio_EventDescription_GetSampleLoadingState',desc,C.byref(state));assert state.value==3,state.value
        runtime.call('Studio_EventDescription_CreateInstance',desc,C.byref(parent_instance))
        runtime.call('Studio_EventInstance_SetCallback',parent_instance,C.cast(callback_ref,P),0x2000)
        position=attributes(distance,angle)
        runtime.call('Studio_EventInstance_Set3DAttributes',parent_instance,C.byref(position))
        if parent:
            count=I();runtime.call('Studio_EventDescription_GetParameterDescriptionCount',desc,C.byref(count))
            parameters={}
            for index in range(count.value):
                parameter=Parameter();runtime.call('Studio_EventDescription_GetParameterDescriptionByIndex',desc,index,C.byref(parameter))
                parameters[parameter.name]=parameter
            controls={b'rpm':50.,b'load':0.5,b'is_visible':1.}
            controls.update({key.encode('utf-8'):float(value) for key,value in (parameter_overrides or {}).items()})
            for key,value in controls.items():
                if key in parameters and not parameters[key].flags&1:
                    runtime.call('Studio_EventInstance_SetParameterByName',parent_instance,key,value,1)
        runtime.call('Studio_EventInstance_Start',parent_instance)
        movements={round(t*100):(d,a) for t,d,a in (trajectory or [])}
        for tick in range(math.ceil(seconds*100)):
            if tick in movements:
                position=attributes(*movements[tick])
                runtime.call('Studio_EventInstance_Set3DAttributes',parent_instance,C.byref(position))
            runtime.call('Studio_System_Update',runtime.system)
        timeline=I();runtime.call('Studio_EventInstance_GetTimelinePosition',parent_instance,C.byref(timeline))
        runtime.call('Studio_EventInstance_Stop',parent_instance,1)
        runtime.call('Studio_System_Update',runtime.system)
        runtime.call('Studio_EventInstance_Release',parent_instance)
        assert not errors,errors
    finally:
        runtime.close()
    with wave.open(str(output),'rb') as stream:
        pcm=stream.readframes(stream.getnframes())
        audio={'frames':stream.getnframes(),'rate':stream.getframerate(),'channels':stream.getnchannels(),
               'pcm_sha256':hashlib.sha256(pcm).hexdigest()}
    result={'variant':variant,'distance':distance,'angle':angle,'parent':parent,'sounds':sounds,'errors':errors,
            'trajectory':trajectory,'headphones':headphones,
            'parameter_overrides':parameter_overrides,
            'snapshots':snapshots,
            'audio':audio,'path':str(output),'last_timeline_ms':timeline.value}
    (output.with_suffix('.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--variant',choices=['baseline','test'],required=True)
    parser.add_argument('--distance',type=float,default=50);parser.add_argument('--angle',type=float,default=0)
    parser.add_argument('--parent');parser.add_argument('--seconds',type=float,default=3.5);parser.add_argument('--label')
    args=parser.parse_args()
    result=render(args.variant,args.distance,args.angle,args.parent,args.seconds,args.label)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
