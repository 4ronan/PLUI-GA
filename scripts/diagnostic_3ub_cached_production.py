import hashlib
import json
import fcntl
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from diagnostic_runtime import target, commune_name, panel_peers, comparison_scale, runtime_metadata
from diagnostic_3v_panel_selector import ensure_runtime_panel

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'output'
PUBLISHED=OUTPUT/'published'
CACHE_ROOT=Path(os.getenv('DIAG_CACHE_DIR', str(OUTPUT/'cache')))
OUT_MANIFEST=OUTPUT/'diagnostic-3ub-manifest.json'
LOCK_PATH=OUTPUT/'.diagnostic-production.lock'

OUTPUT.mkdir(exist_ok=True)
_lock_handle=LOCK_PATH.open('a+')
fcntl.flock(_lock_handle.fileno(),fcntl.LOCK_EX)

TARGET=target()
COMPARISON_SCALE=comparison_scale()
PUBLISHED_NAMES=('index.html','diagnostic.json','synthesis.json','levers.json','priorities.json')
REQUEST_INDEX=CACHE_ROOT/'request-index.json'
REQUEST_ID=f'{TARGET}|{COMPARISON_SCALE}'
AUTO_REQUEST=not bool(os.getenv('DIAG_PANEL_CODES')) and not bool(os.getenv('DIAG_COMMUNE_NAME'))

def truthy(value):
    return str(value or '').strip().lower() in {'1','true','yes','oui','on'}

def sha256_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()

def fingerprint_files(paths):
    h=hashlib.sha256()
    for p in sorted(paths, key=lambda x:str(x)):
        rel=str(p.relative_to(ROOT))
        h.update(rel.encode())
        h.update(b'\0')
        if p.exists() and p.is_file():
            h.update(p.read_bytes())
        else:
            h.update(b'<MISSING>')
        h.update(b'\0')
    return h.hexdigest()

ENGINE_RELATIVE_FILES=[
    'scripts/diagnostic_runtime.py',
    'scripts/diagnostic_3v_panel_selector.py',
    'scripts/diagnostic_3vd_insee_zonings.py',
    'scripts/lovac_3kb_contract.py',
    'scripts/insee_log1_3kc_contract.py',
    'scripts/dvf_3kd_contract.py',
    'scripts/sitadel_3ke_contract.py',
    'scripts/rpls_3kf_contract.py',
    'scripts/insee_3jc_contract.py',
    'scripts/filosofi_panel_contract_3icde.py',
    'scripts/diagnostic_3kg_assembly.py',
    'scripts/diagnostic_3l_interpretation.py',
    'scripts/diagnostic_3m_discriminants.py',
    'scripts/diagnostic_3mp_missing_panels.py',
    'scripts/diagnostic_3m2_discriminants_extended.py',
    'scripts/diagnostic_3n_hypotheses.py',
    'scripts/diagnostic_3o_synthesis.py',
    'scripts/diagnostic_3p_levers.py',
    'scripts/diagnostic_3q_prioritization.py',
    'scripts/diagnostic_3r_page.py',
    'scripts/diagnostic_3t_multiterritory_validate.py',
    'scripts/diagnostic_3u_production.py',
    'scripts/diagnostic_3ub_cached_production.py',
]

def engine_fingerprint():
    return fingerprint_files(ROOT/p for p in ENGINE_RELATIVE_FILES)

def local_data_fingerprint():
    # Snapshots locaux qui influencent directement le diagnostic et doivent
    # invalider immédiatement le cache lorsqu'ils changent.
    files=[
        ROOT/'data/rpls-2025-communes.csv',
        ROOT/'data/rpls-2025-checks.json',
        ROOT/'data/insee-rp2023-panel-3j.csv',
    ]
    return fingerprint_files(files)

def now_iso():
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')

def write_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def copy_tree(src,dst):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src,dst)

def atomic_copy2(src,dst):
    dst.parent.mkdir(parents=True,exist_ok=True)
    tmp=dst.with_name(f".{dst.name}.{os.getpid()}.tmp")
    shutil.copy2(src,tmp)
    os.replace(tmp,dst)

def restore_publication_atomically(src_dir,dst_dir):
    dst_dir.mkdir(parents=True,exist_ok=True)
    expected=set(PUBLISHED_NAMES)
    for name in PUBLISHED_NAMES:
        p=src_dir/name
        if not p.exists() or not p.is_file():
            raise RuntimeError(f'Cache publié incomplet: {name}')
        atomic_copy2(p,dst_dir/name)
    for p in list(dst_dir.iterdir()):
        if p.is_file() and p.name not in expected:
            p.unlink()

def snapshot_publication(src_dir,dst_dir):
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True,exist_ok=True)
    for name in PUBLISHED_NAMES:
        src=src_dir/name
        if not src.exists() or not src.is_file() or src.stat().st_size<=0:
            raise RuntimeError(f'Publication incomplète avant mise en cache: {name}')
        shutil.copy2(src,dst_dir/name)

def validate_cached_files(cache_pub,meta):
    expected=meta.get('files') or []
    if len(expected)!=5 or {x.get('name') for x in expected}!=set(PUBLISHED_NAMES):
        return False
    for item in expected:
        rel=item.get('name')
        p=cache_pub/rel
        if not rel or not p.exists() or p.stat().st_size<=0:
            return False
        if p.stat().st_size!=item.get('bytes') or sha256_file(p)!=item.get('sha256'):
            return False
    return True

def validate_cached_source_manifest(cache_dir,meta):
    item=meta.get('source_manifest') or {}
    p=cache_dir/'diagnostic-3u-manifest.json'
    if not p.exists() or p.stat().st_size<=0:
        return False
    if p.stat().st_size!=item.get('bytes') or sha256_file(p)!=item.get('sha256'):
        return False
    try:
        d=json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return False
    return d.get('status')=='success' and d.get('territory')==TARGET

def validate_cached_panel(cache_dir,meta):
    item=meta.get('panel_file') or {}
    p=cache_dir/'diagnostic-3v-panel.json'
    if not p.exists() or p.stat().st_size<=0:
        return False
    if p.stat().st_size!=item.get('bytes') or sha256_file(p)!=item.get('sha256'):
        return False
    try:
        d=json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return False
    return d.get('territory')==TARGET and d.get('panel_codes')==meta.get('panel_codes')

def load_request_index():
    if not REQUEST_INDEX.exists():
        return {'schema':'3U-B-request-index-v1','entries':{}}
    try:
        d=json.loads(REQUEST_INDEX.read_text(encoding='utf-8'))
        if d.get('schema')!='3U-B-request-index-v1' or not isinstance(d.get('entries'),dict):
            raise ValueError('index schema')
        return d
    except Exception:
        return {'schema':'3U-B-request-index-v1','entries':{}}

def update_request_index(cache_key):
    d=load_request_index()
    d['entries'][REQUEST_ID]={
        'cache_key':cache_key,
        'territory':TARGET,
        'comparison_scale':COMPARISON_SCALE,
        'updated_at':now_iso(),
    }
    write_json(REQUEST_INDEX,d)

started=time.monotonic()
engine_sha=engine_fingerprint()
data_sha=local_data_fingerprint()
ttl_hours=float(os.getenv('DIAG_CACHE_TTL_HOURS','24'))
force_refresh=truthy(os.getenv('DIAG_FORCE_REFRESH'))
now_epoch=time.time()

# Fast path: une requête territoire+échelle déjà indexée et encore valide
# peut être servie sans rappeler geo.api.gouv.fr ni les zonages de panel.
if not force_refresh and AUTO_REQUEST:
    request_entry=(load_request_index().get('entries') or {}).get(REQUEST_ID)
    if request_entry:
        indexed_key=request_entry.get('cache_key')
        indexed_dir=CACHE_ROOT/str(indexed_key)
        indexed_meta_path=indexed_dir/'cache-meta.json'
        try:
            indexed_meta=json.loads(indexed_meta_path.read_text(encoding='utf-8'))
        except Exception:
            indexed_meta=None
        if indexed_meta:
            age_hours=(now_epoch-float(indexed_meta.get('created_at_epoch',0)))/3600
            indexed_pub=indexed_dir/'published'
            indexed_selection=indexed_meta.get('panel_selection') or {}
            fast_valid=(
                age_hours<=ttl_hours
                and indexed_meta.get('territory')==TARGET
                and indexed_meta.get('comparison_scale')==COMPARISON_SCALE
                and indexed_meta.get('engine_sha256')==engine_sha
                and indexed_meta.get('local_data_sha256')==data_sha
                and isinstance(indexed_meta.get('panel_codes'),list)
                and len(indexed_meta.get('panel_codes'))==15
                and indexed_selection.get('algorithm') in {'3V-D-insee-typology-v2','3V-A-structural-v1','explicit_env_override'}
                and validate_cached_files(indexed_pub,indexed_meta)
                and validate_cached_source_manifest(indexed_dir,indexed_meta)
                and validate_cached_panel(indexed_dir,indexed_meta)
            )
            if fast_valid:
                COMMUNE=indexed_meta['commune_name']
                PEERS=indexed_meta['panel_codes']
                os.environ['DIAG_COMMUNE_NAME']=COMMUNE
                os.environ['DIAG_COMMUNE_NAME_SOURCE']='cache_index'
                os.environ['DIAG_PANEL_CODES']=','.join(PEERS)
                os.environ['DIAG_PANEL_SOURCE']=indexed_selection.get('algorithm')
                os.environ['DIAG_COMPARISON_SCALE']=COMPARISON_SCALE
                os.environ['DIAG_COMPARISON_SCALE_SOURCE']='env'
                restore_publication_atomically(indexed_pub,PUBLISHED/TARGET)
                atomic_copy2(indexed_dir/'diagnostic-3u-manifest.json',OUTPUT/'diagnostic-3u-manifest.json')
                atomic_copy2(indexed_dir/'diagnostic-3v-panel.json',OUTPUT/'diagnostic-3v-panel.json')
                fast_manifest={
                    'stage':'3U-B',
                    'status':'success',
                    'territory':TARGET,
                    'commune_name':COMMUNE,
                    'runtime':runtime_metadata(),
                    'panel_reference_n':len(PEERS),
                    'panel_codes':PEERS,
                    'panel_selection':indexed_selection,
                    'cache':{
                        'key':indexed_key,
                        'root':str(CACHE_ROOT.relative_to(ROOT)) if CACHE_ROOT.is_relative_to(ROOT) else str(CACHE_ROOT),
                        'ttl_hours':ttl_hours,
                        'force_refresh':False,
                        'hit':True,
                        'reason':'request_index_valid_cache',
                        'fast_path':True,
                        'engine_sha256':engine_sha,
                        'local_data_sha256':data_sha,
                        'panel_sha256':indexed_meta.get('panel_sha256'),
                        'panel_selection_sha256':indexed_meta.get('panel_selection_sha256'),
                        'commune_sha256':indexed_meta.get('commune_sha256'),
                        'comparison_scale':COMPARISON_SCALE,
                        'comparison_scale_sha256':indexed_meta.get('comparison_scale_sha256'),
                    },
                    'source_generation_manifest':str(indexed_dir/'diagnostic-3u-manifest.json'),
                    'serialized_workspace':True,
                    'started_at':now_iso(),
                    'finished_at':now_iso(),
                    'duration_seconds':round(time.monotonic()-started,3),
                }
                write_json(OUT_MANIFEST,fast_manifest)
                print(json.dumps({
                    'status':'success','stage':'3U-B','territory':TARGET,
                    'cache_hit':True,'cache_reason':'request_index_valid_cache',
                    'duration_seconds':fast_manifest['duration_seconds'],'cache_key':indexed_key,
                },ensure_ascii=False))
                raise SystemExit(0)

try:
    PANEL_SELECTION=ensure_runtime_panel()
except Exception as exc:
    preflight={
        'stage':'3U-B',
        'status':'failure',
        'phase':'panel_selection',
        'territory':TARGET,
        'commune_name':os.getenv('DIAG_COMMUNE_NAME'),
        'started_at':now_iso(),
        'finished_at':now_iso(),
        'error':{'type':type(exc).__name__,'message':str(exc)},
    }
    write_json(OUT_MANIFEST,preflight)
    raise
COMMUNE=commune_name()
PEERS=panel_peers()

panel_signature=hashlib.sha256(','.join(PEERS).encode()).hexdigest()
panel_selection_payload={
    'algorithm':PANEL_SELECTION.get('algorithm'),
    'requested_scale':PANEL_SELECTION.get('requested_scale'),
    'effective_scale':PANEL_SELECTION.get('effective_scale'),
    'panel_codes':PANEL_SELECTION.get('panel_codes') or PEERS,
    'selected':[
        {
            'code':x.get('code'),
            'density7':x.get('density7'),
            'aav_category':x.get('aav_category'),
            'aav_size':x.get('aav_size'),
            'population_band':x.get('population_band'),
        }
        for x in (PANEL_SELECTION.get('selected') or [])
    ],
    'insee_density_sha256':((PANEL_SELECTION.get('source') or {}).get('insee_zonings') or {}).get('density_sha256'),
    'insee_aav_sha256':((PANEL_SELECTION.get('source') or {}).get('insee_zonings') or {}).get('aav_sha256'),
}
panel_selection_signature=hashlib.sha256(
    json.dumps(panel_selection_payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
).hexdigest()
commune_signature=hashlib.sha256(COMMUNE.encode('utf-8')).hexdigest()
scale_signature=hashlib.sha256(COMPARISON_SCALE.encode('utf-8')).hexdigest()
cache_key=f"{TARGET}-{commune_signature[:10]}-{scale_signature[:8]}-{panel_signature[:12]}-{panel_selection_signature[:12]}-{engine_sha[:12]}-{data_sha[:12]}"
cache_dir=CACHE_ROOT/cache_key
cache_pub=cache_dir/'published'
cache_meta_path=cache_dir/'cache-meta.json'
manifest={
    'stage':'3U-B',
    'status':'running',
    'territory':TARGET,
    'commune_name':COMMUNE,
    'runtime':runtime_metadata(),
    'panel_reference_n':len(PEERS),
    'panel_codes':PEERS,
    'panel_selection':{
        'algorithm':PANEL_SELECTION.get('algorithm'),
        'requested_scale':PANEL_SELECTION.get('requested_scale'),
        'effective_scale':PANEL_SELECTION.get('effective_scale'),
    },
    'cache':{
        'key':cache_key,
        'root':str(CACHE_ROOT.relative_to(ROOT)) if CACHE_ROOT.is_relative_to(ROOT) else str(CACHE_ROOT),
        'ttl_hours':ttl_hours,
        'force_refresh':force_refresh,
        'hit':False,
        'reason':None,
        'fast_path':False,
        'engine_sha256':engine_sha,
        'local_data_sha256':data_sha,
        'panel_sha256':panel_signature,
        'panel_selection_sha256':panel_selection_signature,
        'panel_selection':{
            'algorithm':PANEL_SELECTION.get('algorithm'),
            'requested_scale':PANEL_SELECTION.get('requested_scale'),
            'effective_scale':PANEL_SELECTION.get('effective_scale'),
        },
        'commune_sha256':commune_signature,
        'comparison_scale':COMPARISON_SCALE,
        'comparison_scale_sha256':scale_signature,
    },
    'source_generation_manifest':None,
    'serialized_workspace':True,
    'started_at':now_iso(),
    'finished_at':None,
    'duration_seconds':None,
}
write_json(OUT_MANIFEST,manifest)

cache_meta=None
if cache_meta_path.exists():
    try:
        cache_meta=json.loads(cache_meta_path.read_text(encoding='utf-8'))
    except Exception:
        cache_meta=None

cache_valid=False
reason='cache_absent'
if force_refresh:
    reason='forced_refresh'
elif cache_meta:
    age_hours=(now_epoch-float(cache_meta.get('created_at_epoch',0)))/3600
    same_engine=cache_meta.get('engine_sha256')==engine_sha
    same_data=cache_meta.get('local_data_sha256')==data_sha
    same_panel=cache_meta.get('panel_codes')==PEERS
    same_panel_selection=cache_meta.get('panel_selection_sha256')==panel_selection_signature
    same_target=cache_meta.get('territory')==TARGET
    same_commune=cache_meta.get('commune_name')==COMMUNE and cache_meta.get('commune_sha256')==commune_signature
    same_scale=cache_meta.get('comparison_scale')==COMPARISON_SCALE and cache_meta.get('comparison_scale_sha256')==scale_signature
    files_ok=validate_cached_files(cache_pub,cache_meta)
    source_manifest_ok=validate_cached_source_manifest(cache_dir,cache_meta)
    panel_file_ok=validate_cached_panel(cache_dir,cache_meta)
    if age_hours<=ttl_hours and same_engine and same_data and same_panel and same_panel_selection and same_target and same_commune and same_scale and files_ok and source_manifest_ok and panel_file_ok:
        cache_valid=True
        reason='valid_cache'
    elif age_hours>ttl_hours:
        reason='expired'
    elif not same_engine:
        reason='engine_changed'
    elif not same_data:
        reason='local_data_changed'
    elif not same_panel:
        reason='panel_changed'
    elif not same_panel_selection:
        reason='panel_selection_changed'
    elif not same_target:
        reason='territory_changed'
    elif not same_commune:
        reason='commune_name_changed'
    elif not same_scale:
        reason='comparison_scale_changed'
    else:
        reason='cache_integrity_failure'

if cache_valid:
    restore_publication_atomically(cache_pub,PUBLISHED/TARGET)
    source_manifest=cache_dir/'diagnostic-3u-manifest.json'
    atomic_copy2(source_manifest,OUTPUT/'diagnostic-3u-manifest.json')
    atomic_copy2(cache_dir/'diagnostic-3v-panel.json',OUTPUT/'diagnostic-3v-panel.json')
    manifest['cache']['hit']=True
    manifest['cache']['reason']=reason
    manifest['source_generation_manifest']=str(source_manifest)
    manifest['status']='success'
else:
    manifest['cache']['reason']=reason
    child_env=os.environ.copy()
    child_env['DIAG_PRODUCTION_LOCK_HELD']='1'
    proc=subprocess.run(
        [sys.executable,str(ROOT/'scripts/diagnostic_3u_production.py')],
        cwd=ROOT,
        env=child_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    (OUTPUT/'diagnostic-3ub-generation.log').write_text(proc.stdout or '',encoding='utf-8')
    if proc.returncode!=0:
        manifest['status']='failure'
        manifest['error']={
            'return_code':proc.returncode,
            'tail':'\n'.join((proc.stdout or '').splitlines()[-40:]),
        }
        manifest['finished_at']=now_iso()
        manifest['duration_seconds']=round(time.monotonic()-started,3)
        write_json(OUT_MANIFEST,manifest)
        raise SystemExit(proc.returncode)

    source_manifest_path=OUTPUT/'diagnostic-3u-manifest.json'
    source_manifest=json.loads(source_manifest_path.read_text(encoding='utf-8'))
    if source_manifest.get('status')!='success' or source_manifest.get('territory')!=TARGET:
        raise RuntimeError('Manifeste 3U-A invalide après génération')

    cache_dir.mkdir(parents=True,exist_ok=True)
    snapshot_publication(PUBLISHED/TARGET,cache_pub)
    shutil.copy2(source_manifest_path,cache_dir/'diagnostic-3u-manifest.json')
    panel_source_path=OUTPUT/'diagnostic-3v-panel.json'
    if not panel_source_path.exists() or panel_source_path.stat().st_size<=0:
        raise RuntimeError('Panel 3V absent après génération')
    shutil.copy2(panel_source_path,cache_dir/'diagnostic-3v-panel.json')
    cached_source_manifest=cache_dir/'diagnostic-3u-manifest.json'
    source_manifest_meta={
        'name':'diagnostic-3u-manifest.json',
        'bytes':cached_source_manifest.stat().st_size,
        'sha256':sha256_file(cached_source_manifest),
    }
    cached_panel=cache_dir/'diagnostic-3v-panel.json'
    panel_file_meta={
        'name':'diagnostic-3v-panel.json',
        'bytes':cached_panel.stat().st_size,
        'sha256':sha256_file(cached_panel),
    }
    file_meta=[]
    for p in sorted(cache_pub.iterdir()):
        if p.is_file():
            file_meta.append({'name':p.name,'bytes':p.stat().st_size,'sha256':sha256_file(p)})
    cache_meta={
        'schema':'3U-B-cache-v1',
        'territory':TARGET,
        'commune_name':COMMUNE,
        'panel_codes':PEERS,
        'panel_sha256':panel_signature,
        'panel_selection_sha256':panel_selection_signature,
        'panel_selection':{
            'algorithm':PANEL_SELECTION.get('algorithm'),
            'requested_scale':PANEL_SELECTION.get('requested_scale'),
            'effective_scale':PANEL_SELECTION.get('effective_scale'),
        },
        'commune_sha256':commune_signature,
        'comparison_scale':COMPARISON_SCALE,
        'comparison_scale_sha256':scale_signature,
        'engine_sha256':engine_sha,
        'local_data_sha256':data_sha,
        'created_at':now_iso(),
        'created_at_epoch':time.time(),
        'files':file_meta,
        'source_manifest':source_manifest_meta,
        'panel_file':panel_file_meta,
    }
    write_json(cache_meta_path,cache_meta)
    manifest['source_generation_manifest']=str(source_manifest_path.relative_to(ROOT))
    manifest['status']='success'

manifest['finished_at']=now_iso()
manifest['duration_seconds']=round(time.monotonic()-started,3)
if manifest['status']=='success' and AUTO_REQUEST:
    update_request_index(cache_key)
write_json(OUT_MANIFEST,manifest)
print(json.dumps({
    'status':manifest['status'],
    'stage':'3U-B',
    'territory':TARGET,
    'cache_hit':manifest['cache']['hit'],
    'cache_reason':manifest['cache']['reason'],
    'duration_seconds':manifest['duration_seconds'],
    'cache_key':cache_key,
},ensure_ascii=False))
