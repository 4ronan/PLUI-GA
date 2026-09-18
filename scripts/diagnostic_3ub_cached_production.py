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

from diagnostic_runtime import target, commune_name, panel_peers, runtime_metadata

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
COMMUNE=commune_name()
PEERS=panel_peers()
PUBLISHED_NAMES=('index.html','diagnostic.json','synthesis.json','levers.json','priorities.json')

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

def engine_fingerprint():
    return fingerprint_files((ROOT/'scripts').glob('*.py'))

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
    if len(expected)!=5:
        return False
    for item in expected:
        rel=item.get('name')
        p=cache_pub/rel
        if not rel or not p.exists() or p.stat().st_size<=0:
            return False
        if p.stat().st_size!=item.get('bytes') or sha256_file(p)!=item.get('sha256'):
            return False
    return True

started=time.monotonic()
engine_sha=engine_fingerprint()
data_sha=local_data_fingerprint()
panel_signature=hashlib.sha256(','.join(PEERS).encode()).hexdigest()
commune_signature=hashlib.sha256(COMMUNE.encode('utf-8')).hexdigest()
cache_key=f"{TARGET}-{commune_signature[:10]}-{panel_signature[:12]}-{engine_sha[:12]}-{data_sha[:12]}"
cache_dir=CACHE_ROOT/cache_key
cache_pub=cache_dir/'published'
cache_meta_path=cache_dir/'cache-meta.json'
ttl_hours=float(os.getenv('DIAG_CACHE_TTL_HOURS','24'))
force_refresh=truthy(os.getenv('DIAG_FORCE_REFRESH'))
now_epoch=time.time()

manifest={
    'stage':'3U-B',
    'status':'running',
    'territory':TARGET,
    'commune_name':COMMUNE,
    'runtime':runtime_metadata(),
    'panel_reference_n':len(PEERS),
    'panel_codes':PEERS,
    'cache':{
        'key':cache_key,
        'root':str(CACHE_ROOT.relative_to(ROOT)) if CACHE_ROOT.is_relative_to(ROOT) else str(CACHE_ROOT),
        'ttl_hours':ttl_hours,
        'force_refresh':force_refresh,
        'hit':False,
        'reason':None,
        'engine_sha256':engine_sha,
        'local_data_sha256':data_sha,
        'panel_sha256':panel_signature,
        'commune_sha256':commune_signature,
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
    same_target=cache_meta.get('territory')==TARGET
    same_commune=cache_meta.get('commune_name')==COMMUNE and cache_meta.get('commune_sha256')==commune_signature
    files_ok=validate_cached_files(cache_pub,cache_meta)
    if age_hours<=ttl_hours and same_engine and same_data and same_panel and same_target and same_commune and files_ok:
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
    elif not same_target:
        reason='territory_changed'
    elif not same_commune:
        reason='commune_name_changed'
    else:
        reason='cache_integrity_failure'

if cache_valid:
    restore_publication_atomically(cache_pub,PUBLISHED/TARGET)
    source_manifest=cache_dir/'diagnostic-3u-manifest.json'
    if source_manifest.exists():
        shutil.copy2(source_manifest,OUTPUT/'diagnostic-3u-manifest.json')
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
        'commune_sha256':commune_signature,
        'engine_sha256':engine_sha,
        'local_data_sha256':data_sha,
        'created_at':now_iso(),
        'created_at_epoch':time.time(),
        'files':file_meta,
    }
    write_json(cache_meta_path,cache_meta)
    manifest['source_generation_manifest']=str(source_manifest_path.relative_to(ROOT))
    manifest['status']='success'

manifest['finished_at']=now_iso()
manifest['duration_seconds']=round(time.monotonic()-started,3)
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
