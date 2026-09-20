#!/usr/bin/env python3
"""Traite sur OVH les demandes déposées par public/api/diagnostics.php."""

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ENGINE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SITE_ROOT = Path(__file__).resolve().parents[3]
ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
TERRITORY_PATTERN = re.compile(r"^[0-9A-Z]{5}$")
SCALES = {"department", "region", "france"}
PUBLICATION_NAMES = (
    "index.html",
    "diagnostic.json",
    "synthesis.json",
    "levers.json",
    "priorities.json",
)


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def atomic_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def load_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def validate_request(request):
    job_id = str(request.get("id", "")).strip().lower()
    territory = str(request.get("territory", "")).strip().upper()
    scale = str(request.get("scale", "")).strip().lower()
    if not ID_PATTERN.fullmatch(job_id):
        raise ValueError("identifiant de demande invalide")
    if not TERRITORY_PATTERN.fullmatch(territory):
        raise ValueError("code INSEE invalide")
    if scale not in SCALES:
        raise ValueError("échelle de comparaison invalide")
    return job_id, territory, scale


def process_request(queue_path, site_root, engine_root, timeout_seconds):
    request = load_json(queue_path)
    if request is None:
        queue_path.unlink(missing_ok=True)
        return False

    try:
        job_id, territory, scale = validate_request(request)
    except ValueError:
        queue_path.unlink(missing_ok=True)
        return False

    jobs_dir = site_root / "jobs"
    runtime_dir = site_root / "runtime"
    logs_dir = runtime_dir / "logs"
    job_path = jobs_dir / f"{job_id}.json"
    previous = load_json(job_path) or request
    attempts = int(previous.get("attempts", 0)) + 1
    job = {
        "id": job_id,
        "status": "running",
        "territory": territory,
        "scale": scale,
        "cached": False,
        "created_at": previous.get("created_at") or request.get("created_at") or now_iso(),
        "started_at": now_iso(),
        "attempts": attempts,
        "executor": "ovh-python",
    }
    atomic_json(job_path, job)
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{job_id}.log"
    started = time.monotonic()

    env = os.environ.copy()
    env["DIAG_CACHE_DIR"] = str(runtime_dir / "cache")
    env["PYTHONUNBUFFERED"] = "1"
    request_script = engine_root / "scripts" / "diagnostic_request.py"
    command = [sys.executable, str(request_script), territory, scale]

    try:
        completed = subprocess.run(
            command,
            cwd=engine_root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
        )
        log = completed.stdout or ""
        log_path.write_text(log, encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(f"moteur terminé avec le code {completed.returncode}")

        source_dir = engine_root / "output" / "published" / territory
        required = [source_dir / name for name in PUBLICATION_NAMES]
        if not all(path.is_file() and path.stat().st_size > 0 for path in required):
            raise RuntimeError("publication déterministe incomplète")

        target_dir = site_root / "diagnostics" / territory / scale
        for source in required:
            atomic_copy(source, target_dir / source.name)
        extras = {
            engine_root / "output" / "diagnostic-3v-panel.json": target_dir / "panel.json",
            engine_root / "output" / "diagnostic-3ub-manifest.json": target_dir / "cache-manifest.json",
            engine_root / "output" / "diagnostic-3u-manifest.json": target_dir / "production-manifest.json",
        }
        for source, destination in extras.items():
            if not source.is_file() or source.stat().st_size <= 0:
                raise RuntimeError(f"sortie obligatoire absente : {source.name}")
            atomic_copy(source, destination)

        job.update(
            status="success",
            finished_at=now_iso(),
            duration_seconds=round(time.monotonic() - started, 3),
            result_url=f"diagnostics/{territory}/{scale}/",
        )
        atomic_json(job_path, job)
        queue_path.unlink(missing_ok=True)
        return True
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        log_path.write_text(partial + "\nTIMEOUT\n", encoding="utf-8")
        message = "Le calcul a dépassé la durée maximale autorisée sur OVH."
    except Exception as exc:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\nWORKER_ERROR: {type(exc).__name__}: {exc}\n")
        message = "Le diagnostic n’a pas pu être produit à partir des sources publiques disponibles."

    job.update(
        status="failure",
        finished_at=now_iso(),
        duration_seconds=round(time.monotonic() - started, 3),
        error={"type": "generation_failure", "message": message},
    )
    atomic_json(job_path, job)
    queue_path.unlink(missing_ok=True)
    return False


def main():
    parser = argparse.ArgumentParser(description="Worker OVH du diagnostic territorial de vacance")
    parser.add_argument("--site-root", type=Path, default=DEFAULT_SITE_ROOT)
    parser.add_argument("--engine-root", type=Path, default=ENGINE_ROOT)
    parser.add_argument("--max-jobs", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=3300)
    args = parser.parse_args()

    site_root = args.site_root.expanduser().resolve()
    engine_root = args.engine_root.expanduser().resolve()
    runtime_dir = site_root / "runtime"
    queue_dir = runtime_dir / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    lock_path = runtime_dir / "worker.lock"
    lock_handle = lock_path.open("a+")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"status": "busy", "executor": "ovh-python"}))
        return 0

    processed = 0
    succeeded = 0
    for queue_path in sorted(queue_dir.glob("*.json"), key=lambda path: path.stat().st_mtime):
        if processed >= max(1, args.max_jobs):
            break
        succeeded += int(process_request(queue_path, site_root, engine_root, max(60, args.timeout_seconds)))
        processed += 1

    print(json.dumps({
        "status": "success",
        "executor": "ovh-python",
        "processed": processed,
        "succeeded": succeeded,
        "finished_at": now_iso(),
    }, ensure_ascii=False))
    return 0 if processed == succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
