"""Exercise compiled friendly engine/track routes without touching shared FX."""
from __future__ import annotations
import hashlib
import json
from runtime_probe import ROOT
from runtime_playback_check import render
from runtime_regression import level


def main():
    inventory=json.loads((ROOT/'reports/current_compiled_event_inventory.json').read_text(encoding='utf-8'))
    events=[x for x in inventory if x['role_annotation']=='friendly_ai' or
            ('/_enemies/' not in x['path_annotation'] and x['path_annotation'].split('/')[-1].startswith('tracks_ai'))]
    report={'status':'RUNNING','scope':'Real vendor runtime, isolated at 5m with speed/turn/load inputs; not a game trace',
            'tested_banks':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'test-package/sound/mod').glob('*.bank')},
            'events':[],'snapshot_cases':[]}
    path=ROOT/'reports/friendly_movement_audit.json'
    if path.exists():
        previous=json.loads(path.read_text(encoding='utf-8'))
        if previous.get('status')=='RUNNING' and previous.get('tested_banks')==report['tested_banks']:
            report=previous
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    start=len(report['events'])
    for index,event in enumerate(events[start:],start=start):
        row={'event':event['event'],'name':event['path_annotation'],'outputs':[]}
        for headphones in [0,1]:
            result=render('test',5,70,parent=event['event'],seconds=2,label=f'friendly_audit_{index:03d}_h{headphones}',
                          headphones=headphones,parameter_overrides={'speed':30,'turn':1,'material':3,'intense':1})
            row['outputs'].append({'headphones':headphones,**level(result),
                                    'sounds':sorted({s['sample'] for s in result['sounds']})})
        report['events'].append(row)
        if (index+1)%24==0:save();print(f'Friendly engine/track paths: {index+1}/{len(events)}',flush=True)
    snapshots=['f69ed748-b45b-4ce3-9886-83f90818bca5','c615d167-f76f-4866-b840-5bd314baeb79',
               '84e4586f-7c11-4e71-b1d2-0123b3d7c1b5','fc0ac4aa-feba-49f2-a871-1d1f617a2275']
    for index,snapshot in enumerate(snapshots):
        for headphones in [0,1]:
            for name,event in [('leo2a5','3416f6e0-f7c4-40fd-a610-cfca2e861062'),('tracks_mbt','069e937e-f9cb-4e99-90ab-6652876f1f29')]:
                result=render('test',5,70,parent=event,seconds=2,label=f'snapshot_audit_{index}_{name}_h{headphones}',
                              headphones=headphones,parameter_overrides={'speed':30,'turn':1,'material':3,'intense':1},snapshots=[snapshot])
                report['snapshot_cases'].append({'snapshot':snapshot,'event':event,'headphones':headphones,**level(result)})
    audible=[x for x in report['events'] if any(y['peak']>0 for y in x['outputs'])]
    report.update(status='COMPLETE',event_count=len(events),audible_event_count=len(audible),
                  audible_events=[{'event':x['event'],'name':x['name']} for x in audible])
    save();print(json.dumps({k:v for k,v in report.items() if k not in ['events','snapshot_cases','tested_banks']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
