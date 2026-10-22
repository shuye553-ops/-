"""Compare baseline/test behavior in the real vendor runtime, offline."""
from __future__ import annotations

import json
import hashlib
import math
import wave

import numpy as np

from runtime_playback_check import render
from runtime_probe import ROOT


def voices(result):
    return [s for s in result['sounds'] if s['sample'].startswith('dist_')]


def signature(result, names=True):
    sounds=voices(result)
    origin=sounds[0]['dsp_clock'] if sounds else 0
    return [(s['sample'] if names else 'voice',s['dsp_clock']-origin) for s in sounds]


def level(result):
    with wave.open(result['path'],'rb') as stream:
        x=np.frombuffer(stream.readframes(stream.getnframes()),'<i2').astype(float)/32768
    rms=float(np.sqrt(np.mean(x*x)))
    return {'rms':rms,'peak':float(max(abs(x))),'rms_dbfs':20*math.log10(rms) if rms else None}


def aligned_pcm(result,seconds=3.5):
    # FMOD's output file can include a different number of silent startup DSP
    # blocks. Align by the observed first sound's DSP clock, never by correlation.
    with wave.open(result['path'],'rb') as stream:
        stream.setpos(voices(result)[0]['dsp_clock'])
        pcm=stream.readframes(round(seconds*stream.getframerate()))
        assert len(pcm)==round(seconds*stream.getframerate())*stream.getnchannels()*stream.getsampwidth()
        return pcm


def main():
    report={'status':'RUNNING','runtime_version':'2.02.14 (00020214)',
            'tested_banks':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in (ROOT/'test-package/sound/mod').glob('*.bank')},
            'game_launched':False,'original_voice_cases':[],'new_voice_cases':[],
            'boundary_cases':[],'parent_schedule_cases':[],'movement_cases':[],'mix_cases':[]}
    path=ROOT/'reports/runtime_regression.json'
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    try:
        cases=sorted({(d,0) for d in [20,50,80,110,150,190]} | {(50,a) for a in [-135,-90,-45,0,45,90,135,180]})
        for d,a in cases:
            results=[render(v,d,a,label=f'regression_d{d}_a{a}') for v in ['baseline','test']]
            assert signature(results[0])==signature(results[1]),(d,a)
            assert aligned_pcm(results[0])==aligned_pcm(results[1]),(d,a,'PCM')
            assert len(voices(results[0]))==2,(d,a)
            report['original_voice_cases'].append({'distance':d,'angle':a,'pcm_identical_after_dsp_start_alignment':True,
                                                   'sample_and_clock_identical':True,'sounds':voices(results[1])})
        for d,name in [(130,'dist_120m'),(170,'dist_160m'),(205,'dist_200m')]:
            r=render('test',d,0,label=f'new_distance_{d}')
            assert [s['sample'] for s in voices(r)]==['dist_正前方',name]
            report['new_voice_cases'].append({'distance':d,'sounds':voices(r),'level':level(r)})
        for d in [119.999,120,120.001,159.999,160,160.001,199.999,200,200.001]:
            r=render('test',d,0,label=f'new_boundary_{d}')
            assert len(voices(r))==2,(d,voices(r))
            report['boundary_cases'].append({'distance':d,'sounds':voices(r),'single_distance_call':True})
        # Old exact-boundary behavior is retained, including any original overlap.
        for d in [30,65,100,140,180,210,215,216]:
            results=[render(v,d,0,label=f'old_boundary_{d}') for v in ['baseline','test']]
            assert signature(results[0],False)==signature(results[1],False),(d,'old boundary changed')
            report['boundary_cases'].append({'distance':d,'original_behavior_retained':True,
                                             'baseline_sounds':voices(results[0]),'test_sounds':voices(results[1])})
        save();print('Original PCM, directions, distances, exact boundaries: PASS',flush=True)
        logic=json.loads((ROOT/'source/current_announcement_logic.json').read_text(encoding='utf-8'))
        for index,parent in enumerate(logic['parent_schedules']):
            results=[render(v,50,0,parent=parent['event'],seconds=24,label=f'parent_{index:02d}')
                     for v in ['baseline','test']]
            assert len(voices(results[0]))>=8,(parent['event'],'insufficient voice callbacks')
            assert signature(results[0])==signature(results[1]),(parent['event'],'timing changed')
            report['parent_schedule_cases'].append({'event':parent['event'],'name':parent['source_name_annotation'],
                'seconds':24,'sample_and_clock_identical':True,'voice_callbacks':len(voices(results[1])),
                'signature':signature(results[1])})
            if (index+1)%12==0:
                save();print(f'Parent schedules: {index+1}/72 PASS',flush=True)
        leo='cd9f666e-02c4-4d42-b64a-799e1eae96d4'
        distances=[110,119.99,120,120.01,130,159.99,160,160.01,170,199.99,200,200.01,205,
                   200,199.99,170,160,159.99,130,120,119.99,110]
        trajectory=[(i*3,d,0) for i,d in enumerate(distances)]
        results=[render(v,110,0,parent=leo,seconds=66,label='movement_and_boundary_hold',trajectory=trajectory)
                 for v in ['baseline','test']]
        assert len(voices(results[0]))>=20
        before,after=voices(results[0]),voices(results[1])
        def direction_clocks(items):
            return [s['dsp_clock']-items[0]['dsp_clock'] for s in items if s['sample']=='dist_正前方']
        assert direction_clocks(before)==direction_clocks(after),'parent cadence changed'
        old_clocks={s['dsp_clock']-before[0]['dsp_clock'] for s in before}
        new_clocks={s['dsp_clock']-after[0]['dsp_clock'] for s in after}
        assert old_clocks <= new_clocks,'an original scheduled call was lost'
        extras=[s for s in after if s['dsp_clock']-after[0]['dsp_clock'] not in old_clocks]
        transition_times=[]
        for previous,current in zip(trajectory,trajectory[1:]):
            for threshold in [120,160,200]:
                if (previous[1]<threshold)!=(current[1]<threshold):transition_times.append(current[0])
        for sound in extras:
            when=(sound['dsp_clock']-after[0]['dsp_clock'])/24000
            assert any(abs(when-t)<=0.02 for t in transition_times),(sound,'unexplained extra call')
        report['movement_cases'].append({'seconds':66,'trajectory':trajectory,'parent_cadence_identical':True,
                                        'all_original_call_times_retained':True,'extra_new_boundary_calls':extras,
                                        'qualification':'Original conditions can retrigger inside an active instrument region when a distance band changes. New bands retain that rule; no new debounce policy was added.',
                                        'baseline':before,'test':after})
        for headphones in [0,1]:
            for d,name in [(130,'dist_120m'),(170,'dist_160m'),(205,'dist_200m')]:
                r=render('test',d,0,parent=leo,seconds=15,label=f'leo_enemy_{d}_h{headphones}',headphones=headphones)
                sounds=voices(r)
                assert len(sounds)==8 and all(s['sample'] in ['dist_正前方',name] for s in sounds)
                report['mix_cases'].append({'role':'enemy_leo2a5_candidate','headphones':headphones,'distance':d,
                                            'voice_callbacks':len(sounds),'level':level(r)})
            friendly='3416f6e0-f7c4-40fd-a610-cfca2e861062'
            r=render('test',50,0,parent=friendly,seconds=5,label=f'leo_friendly_h{headphones}',headphones=headphones)
            levels=level(r);assert levels['peak']==0,levels
            report['mix_cases'].append({'role':'friendly_leo2a5_candidate','headphones':headphones,'level':levels})
        for label,ident in [('abrams_stop','95513cdf-5279-45f2-9f85-0a1bd553c74f'),
                            ('hstvl_stop','dd54db4e-e998-4b8f-a9ce-2334bf75f611')]:
            pair=[level(render(v,20,0,parent=ident,seconds=4,label=label)) for v in ['baseline','test']]
            assert pair[1]['rms']>0 and pair[1]['rms']>pair[0]['rms']*100
            report['mix_cases'].append({'role':label,'event':ident,'baseline_level':pair[0],
                                       'test_level':pair[1],'restored_audio_verified':True})
        report.update(status='PASS_RUNTIME_LOAD_AND_OFFLINE_REGRESSION',parent_count=72,
                      qualification='Controlled FMOD offline replay; game integration, actual Leopard 2A7V mapping, and device listening remain unverified.')
        assert report['tested_banks']=={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in (ROOT/'test-package/sound/mod').glob('*.bank')}
        save()
        print(json.dumps({k:(len(v) if isinstance(v,list) else v) for k,v in report.items()},ensure_ascii=False,indent=2))
    except BaseException as error:
        report.update(status='FAIL',error=str(error));save();raise


if __name__=='__main__':main()
