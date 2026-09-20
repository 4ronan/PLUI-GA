import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REQUEST=ROOT/'scripts/diagnostic_request.py'


def parse_codes(value):
    raw=[]
    p=Path(value)
    if p.exists() and p.is_file():
        raw=p.read_text(encoding='utf-8').replace(';',',').replace('\n',',').split(',')
    else:
        raw=str(value).replace(';',',').split(',')
    codes=[]
    seen=set()
    for item in raw:
        code=item.strip().upper()
        if not code:
            continue
        if len(code)!=5 or not code.isalnum():
            raise ValueError(f'code INSEE invalide: {code!r}')
        if code not in seen:
            seen.add(code)
            codes.append(code)
    if not codes:
        raise ValueError('aucun code INSEE fourni')
    return codes


def main():
    parser=argparse.ArgumentParser(
        description='Générer plusieurs diagnostics de vacance séquentiellement à partir de codes INSEE.'
    )
    parser.add_argument('codes',help='liste séparée par virgules/points-virgules ou chemin vers un fichier texte')
    parser.add_argument('scale',help='département, région ou France')
    parser.add_argument('--force-refresh',action='store_true')
    parser.add_argument('--stop-on-error',action='store_true')
    args=parser.parse_args()

    try:
        codes=parse_codes(args.codes)
    except ValueError as exc:
        print(json.dumps({
            'status':'failure','phase':'input_validation',
            'error':{'type':'invalid_codes','message':str(exc)}
        },ensure_ascii=False))
        return 2

    started=time.monotonic()
    results=[]
    for index,code in enumerate(codes,1):
        cmd=[sys.executable,str(REQUEST),code,args.scale]
        if args.force_refresh:
            cmd.append('--force-refresh')
        proc=subprocess.run(
            cmd,cwd=ROOT,env=os.environ.copy(),text=True,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        )
        result=None
        lines=[x for x in (proc.stdout or '').splitlines() if x.strip()]
        for line in reversed(lines):
            try:
                candidate=json.loads(line)
                if isinstance(candidate,dict) and candidate.get('status'):
                    result=candidate
                    break
            except Exception:
                pass
        if result is None:
            result={
                'status':'failure','territory':code,'phase':'runner',
                'error':{'type':'invalid_runner_output'},
                'log_tail':'\n'.join(lines[-20:])
            }
        result['batch_index']=index
        result['return_code']=proc.returncode
        results.append(result)
        if proc.returncode!=0 and args.stop_on_error:
            break

    ok=[x for x in results if x.get('status')=='success']
    failed=[x for x in results if x.get('status')!='success']
    summary={
        'status':'success' if not failed and len(results)==len(codes) else 'partial' if ok else 'failure',
        'requested_n':len(codes),
        'processed_n':len(results),
        'success_n':len(ok),
        'failure_n':len(failed),
        'duration_seconds':round(time.monotonic()-started,3),
        'comparison_scale':args.scale,
        'territories':codes,
        'results':results,
        'llm_used':False,
    }
    print(json.dumps(summary,ensure_ascii=False))
    return 0 if not failed and len(results)==len(codes) else 1


if __name__=='__main__':
    raise SystemExit(main())
