import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'output'


def normalize_scale(value):
    raw=str(value or '').strip().lower()
    aliases={
        'departement':'department','département':'department','department':'department','dept':'department',
        'region':'region','région':'region',
        'france':'france','national':'france','nationale':'france',
    }
    if raw not in aliases:
        raise argparse.ArgumentTypeError('échelle attendue: département, région ou France')
    return aliases[raw]


def main():
    parser=argparse.ArgumentParser(
        description='Générer un diagnostic territorial de vacance à partir du seul code INSEE et de l’échelle de comparaison.'
    )
    parser.add_argument('territory',help='Code INSEE communal à 5 caractères')
    parser.add_argument('scale',type=normalize_scale,help='département, région ou France')
    parser.add_argument('--force-refresh',action='store_true',help='ignorer un cache valide et recalculer')
    parser.add_argument('--no-cache',action='store_true',help='exécuter directement le pipeline sans cache')
    args=parser.parse_args()

    env=os.environ.copy()
    env['DIAG_TERRITORY']=args.territory.strip().upper()
    env['DIAG_COMPARISON_SCALE']=args.scale
    for key in (
        'DIAG_COMMUNE_NAME','DIAG_COMMUNE_NAME_SOURCE',
        'DIAG_PANEL_CODES','DIAG_PANEL_SOURCE',
        'DIAG_COMPARISON_SCALE_SOURCE',
        'DIAG_DISABLE_INSEE_PANEL_TYPOLOGY',
    ):
        env.pop(key,None)
    if args.force_refresh:
        env['DIAG_FORCE_REFRESH']='1'
    else:
        env.pop('DIAG_FORCE_REFRESH',None)

    script='scripts/diagnostic_3u_production.py' if args.no_cache else 'scripts/diagnostic_3ub_cached_production.py'
    proc=subprocess.run(
        [sys.executable,str(ROOT/script)],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    cache_manifest_path=OUTPUT/'diagnostic-3ub-manifest.json'
    production_manifest_path=OUTPUT/'diagnostic-3u-manifest.json'
    cache_manifest=None
    production_manifest=None
    if cache_manifest_path.exists():
        try:
            cache_manifest=json.loads(cache_manifest_path.read_text(encoding='utf-8'))
        except Exception:
            cache_manifest=None
    if production_manifest_path.exists():
        try:
            production_manifest=json.loads(production_manifest_path.read_text(encoding='utf-8'))
        except Exception:
            production_manifest=None

    if proc.returncode!=0:
        error_manifest=cache_manifest if not args.no_cache else production_manifest
        result={
            'status':'failure',
            'territory':env['DIAG_TERRITORY'],
            'comparison_scale':args.scale,
            'runner':script,
            'return_code':proc.returncode,
            'error':(error_manifest or {}).get('error'),
            'phase':(error_manifest or {}).get('phase'),
            'log_tail':'\n'.join((proc.stdout or '').splitlines()[-30:]),
        }
        print(json.dumps(result,ensure_ascii=False))
        return proc.returncode

    published=OUTPUT/'published'/env['DIAG_TERRITORY']
    page_path=published/'diagnostic.json'
    if not page_path.exists():
        raise RuntimeError(f'Publication absente après succès: {page_path}')
    page=json.loads(page_path.read_text(encoding='utf-8'))

    result={
        'status':'success',
        'territory':page['territory'],
        'commune_name':page['subtitle'].split(' · code INSEE ')[0],
        'comparison_scale_requested':page['method'].get('comparison_scale_requested'),
        'comparison_scale_effective':page['method'].get('comparison_scale_effective'),
        'panel_source':page['method'].get('panel_source'),
        'panel_reference_n':page['method'].get('panel_reference_n'),
        'cache':(
            {
                'hit':cache_manifest.get('cache',{}).get('hit'),
                'reason':cache_manifest.get('cache',{}).get('reason'),
                'key':cache_manifest.get('cache',{}).get('key'),
            }
            if cache_manifest and not args.no_cache else None
        ),
        'quality':page.get('quality'),
        'published':{
            'html':str((published/'index.html').relative_to(ROOT)),
            'diagnostic':str((published/'diagnostic.json').relative_to(ROOT)),
            'synthesis':str((published/'synthesis.json').relative_to(ROOT)),
            'levers':str((published/'levers.json').relative_to(ROOT)),
            'priorities':str((published/'priorities.json').relative_to(ROOT)),
        },
    }
    print(json.dumps(result,ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
