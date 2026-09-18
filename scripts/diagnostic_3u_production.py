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

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
RUNS = OUTPUT / "runs"
PUBLISHED = OUTPUT / "published"
MANIFEST = OUTPUT / "diagnostic-3u-manifest.json"
LOCK_PATH = OUTPUT / ".diagnostic-production.lock"

OUTPUT.mkdir(exist_ok=True)
_lock_handle = None
if os.getenv("DIAG_PRODUCTION_LOCK_HELD") != "1":
    _lock_handle = LOCK_PATH.open("a+")
    fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_EX)

TARGET = target()
COMMUNE = commune_name()
PEERS = panel_peers()

STEPS = [
    ("3K-B", "scripts/lovac_3kb_contract.py"),
    ("3K-C", "scripts/insee_log1_3kc_contract.py"),
    ("3K-D", "scripts/dvf_3kd_contract.py"),
    ("3K-E", "scripts/sitadel_3ke_contract.py"),
    ("3K-F", "scripts/rpls_3kf_contract.py"),
    ("3J-C", "scripts/insee_3jc_contract.py"),
    ("3I-C/D/E", "scripts/filosofi_panel_contract_3icde.py"),
    ("3K-G", "scripts/diagnostic_3kg_assembly.py"),
    ("3L", "scripts/diagnostic_3l_interpretation.py"),
    ("3M", "scripts/diagnostic_3m_discriminants.py"),
    ("3M-P", "scripts/diagnostic_3mp_missing_panels.py"),
    ("3M-2", "scripts/diagnostic_3m2_discriminants_extended.py"),
    ("3N", "scripts/diagnostic_3n_hypotheses.py"),
    ("3O", "scripts/diagnostic_3o_synthesis.py"),
    ("3P", "scripts/diagnostic_3p_levers.py"),
    ("3Q", "scripts/diagnostic_3q_prioritization.py"),
    ("3R", "scripts/diagnostic_3r_page.py"),
    ("3T-M", "scripts/diagnostic_3t_multiterritory_validate.py"),
]

FINAL_FILES = [
    OUTPUT / "diagnostic-3r-page.json",
    OUTPUT / "diagnostic-3r-page.html",
    OUTPUT / "diagnostic-3o-synthesis.json",
    OUTPUT / "diagnostic-3p-levers.json",
    OUTPUT / "diagnostic-3q-priorities.json",
]

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def safe_slug(value):
    return "".join(c.lower() if c.isalnum() else "-" for c in value).strip("-") or "commune"

def atomic_copy2(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.{os.getpid()}.tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)

started = time.monotonic()
started_at = now_iso()
run_id = f"{TARGET}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{os.getpid()}"
run_dir = RUNS / run_id
log_dir = run_dir / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

manifest = {
    "stage": "3U-A",
    "run_id": run_id,
    "status": "running",
    "started_at": started_at,
    "finished_at": None,
    "duration_seconds": None,
    "territory": TARGET,
    "commune_name": COMMUNE,
    "panel_reference_n": len(PEERS),
    "panel_codes": PEERS,
    "runtime": runtime_metadata(),
    "git": {
        "sha": os.getenv("GITHUB_SHA"),
        "ref": os.getenv("GITHUB_REF_NAME") or os.getenv("GITHUB_REF"),
    },
    "generation": {
        "mode": "deterministic_pipeline",
        "serialized_workspace": True,
        "llm_used": False,
        "external_knowledge_generation": False,
    },
    "steps": [],
    "outputs": [],
    "error": None,
}

def write_manifest():
    OUTPUT.mkdir(exist_ok=True)
    payload = json.dumps(manifest, ensure_ascii=False, indent=2)
    MANIFEST.write_text(payload, encoding="utf-8")
    (run_dir / "manifest.json").write_text(payload, encoding="utf-8")

write_manifest()

try:
    for index, (stage, script) in enumerate(STEPS, start=1):
        stage_started = time.monotonic()
        stamp = now_iso()
        proc = subprocess.run(
            [sys.executable, str(ROOT / script)],
            cwd=ROOT,
            env=os.environ.copy(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        duration = round(time.monotonic() - stage_started, 3)
        log_path = log_dir / f"{index:02d}-{stage.replace('/', '-')}.log"
        log_path.write_text(proc.stdout or "", encoding="utf-8")
        step = {
            "order": index,
            "stage": stage,
            "script": script,
            "started_at": stamp,
            "duration_seconds": duration,
            "return_code": proc.returncode,
            "status": "success" if proc.returncode == 0 else "failure",
            "log": str(log_path.relative_to(ROOT)),
        }
        manifest["steps"].append(step)
        write_manifest()
        if proc.returncode != 0:
            tail = "\n".join((proc.stdout or "").splitlines()[-30:])
            raise RuntimeError(f"Échec {stage} ({script})\n{tail}")

    for path in FINAL_FILES:
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError(f"Sortie finale absente ou vide: {path.relative_to(ROOT)}")

    page = json.loads((OUTPUT / "diagnostic-3r-page.json").read_text(encoding="utf-8"))
    if page.get("territory") != TARGET or page.get("quality", {}).get("status") != "ok":
        raise RuntimeError("La sortie 3R ne correspond pas au territoire ou n'est pas validée")

    publish_dir = PUBLISHED / TARGET
    publish_dir.mkdir(parents=True, exist_ok=True)
    publication_map = {
        OUTPUT / "diagnostic-3r-page.html": publish_dir / "index.html",
        OUTPUT / "diagnostic-3r-page.json": publish_dir / "diagnostic.json",
        OUTPUT / "diagnostic-3o-synthesis.json": publish_dir / "synthesis.json",
        OUTPUT / "diagnostic-3p-levers.json": publish_dir / "levers.json",
        OUTPUT / "diagnostic-3q-priorities.json": publish_dir / "priorities.json",
    }
    for src, dst in publication_map.items():
        atomic_copy2(src, dst)

    manifest["outputs"] = [
        {
            "path": str(dst.relative_to(ROOT)),
            "bytes": dst.stat().st_size,
            "sha256": sha256(dst),
        }
        for dst in publication_map.values()
    ]
    manifest["diagnostic_summary"] = {
        "kpi_count": page["quality"]["kpi_count"],
        "discriminant_factor_count": page["quality"]["discriminant_factor_count"],
        "hypothesis_count": page["quality"]["hypothesis_count"],
        "priority_count": page["quality"]["priority_count"],
    }
    manifest["status"] = "success"
except Exception as exc:
    manifest["status"] = "failure"
    manifest["error"] = {
        "type": type(exc).__name__,
        "message": str(exc),
    }
    raise
finally:
    manifest["finished_at"] = now_iso()
    manifest["duration_seconds"] = round(time.monotonic() - started, 3)
    write_manifest()

print(json.dumps({
    "status": manifest["status"],
    "stage": manifest["stage"],
    "territory": TARGET,
    "commune_name": COMMUNE,
    "duration_seconds": manifest["duration_seconds"],
    "published_dir": str((PUBLISHED / TARGET).relative_to(ROOT)),
    "manifest": str(MANIFEST.relative_to(ROOT)),
}, ensure_ascii=False))
