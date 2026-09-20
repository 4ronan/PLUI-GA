import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "public" / "index.html"
REQUEST = Path(os.getenv("DIAG_REQUEST_SCRIPT", str(ROOT / "scripts" / "diagnostic_request.py"))).resolve()
OUTPUT = ROOT / "output"
PUBLISHED = OUTPUT / "published"
OUTPUT.mkdir(exist_ok=True)
MAX_BODY_BYTES = 8192
JOB_LIMIT = int(os.getenv("DIAG_JOB_QUEUE_LIMIT", "20"))
JOB_RETENTION_SECONDS = int(os.getenv("DIAG_JOB_RETENTION_SECONDS", "86400"))
RATE_LIMIT = int(os.getenv("DIAG_RATE_LIMIT_PER_MINUTE", "10"))
GENERATION_TIMEOUT = int(os.getenv("DIAG_GENERATION_TIMEOUT_SECONDS", "1800"))


def now_epoch():
    return time.time()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_scale(value):
    aliases = {
        "departement": "department", "département": "department",
        "department": "department", "dept": "department",
        "region": "region", "région": "region",
        "france": "france", "national": "france", "nationale": "france",
    }
    raw = str(value or "").strip().lower()
    if raw not in aliases:
        raise ValueError("échelle requise : département, région ou France")
    return aliases[raw]


def validate_request(territory, scale):
    code = str(territory or "").strip().upper()
    if not re.fullmatch(r"[0-9A-Z]{5}", code):
        raise ValueError("code INSEE communal attendu sur 5 caractères alphanumériques")
    return code, normalize_scale(scale)


def published_bundle(territory):
    published = PUBLISHED / territory
    paths = {
        "diagnostic": published / "diagnostic.json",
        "levers": published / "levers.json",
        "priorities": published / "priorities.json",
        "panel": OUTPUT / "diagnostic-3v-panel.json",
        "cache_manifest": OUTPUT / "diagnostic-3ub-manifest.json",
        "production_manifest": OUTPUT / "diagnostic-3u-manifest.json",
    }
    missing = [name for name, path in paths.items() if not path.exists() or path.stat().st_size <= 0]
    if missing:
        raise RuntimeError("fichiers publiés absents : " + ", ".join(missing))
    bundle = {name: read_json(path) for name, path in paths.items()}
    if bundle["diagnostic"].get("territory") != territory or bundle["panel"].get("territory") != territory:
        raise RuntimeError("la publication ne correspond pas au territoire demandé")
    return bundle


class JobManager:
    def __init__(self):
        self.pending = queue.Queue(maxsize=JOB_LIMIT)
        self.jobs = {}
        self.active_by_request = {}
        self.lock = threading.Lock()
        self.worker = threading.Thread(target=self._worker, name="diagnostic-worker", daemon=True)
        self.worker.start()

    def submit(self, territory, scale):
        request_key = f"{territory}|{scale}"
        with self.lock:
            self._purge_locked()
            existing_id = self.active_by_request.get(request_key)
            if existing_id and existing_id in self.jobs:
                return self._public(self.jobs[existing_id]), False
            if self.pending.full():
                raise queue.Full
            job_id = uuid.uuid4().hex
            job = {
                "id": job_id, "status": "queued", "territory": territory, "scale": scale,
                "created_at": now_epoch(), "started_at": None, "finished_at": None,
                "error": None, "result": None,
            }
            self.jobs[job_id] = job
            self.active_by_request[request_key] = job_id
            self.pending.put_nowait(job_id)
            return self._public(job), True

    def get(self, job_id):
        with self.lock:
            self._purge_locked()
            job = self.jobs.get(job_id)
            return self._public(job) if job else None

    def stats(self):
        with self.lock:
            running = sum(1 for item in self.jobs.values() if item["status"] == "running")
            return {"queued": self.pending.qsize(), "running": running, "capacity": JOB_LIMIT}

    def _purge_locked(self):
        cutoff = now_epoch() - JOB_RETENTION_SECONDS
        stale = [job_id for job_id, job in self.jobs.items() if job.get("finished_at") and job["finished_at"] < cutoff]
        for job_id in stale:
            self.jobs.pop(job_id, None)

    @staticmethod
    def _public(job):
        if not job:
            return None
        payload = {key: value for key, value in job.items() if key != "result"}
        if job["status"] == "success":
            payload["result"] = job["result"]
            payload["result_url"] = f"/diagnostics/{job['territory']}/"
        return payload

    def _worker(self):
        while True:
            job_id = self.pending.get()
            with self.lock:
                job = self.jobs.get(job_id)
                if not job:
                    self.pending.task_done()
                    continue
                job["status"] = "running"
                job["started_at"] = now_epoch()
            try:
                proc = subprocess.run(
                    [sys.executable, str(REQUEST), job["territory"], job["scale"]],
                    cwd=ROOT, env=os.environ.copy(), text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=GENERATION_TIMEOUT,
                )
                lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
                request_result = None
                for line in reversed(lines):
                    try:
                        candidate = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(candidate, dict) and candidate.get("status"):
                        request_result = candidate
                        break
                if proc.returncode != 0 or not request_result or request_result.get("status") != "success":
                    message = (((request_result or {}).get("error") or {}).get("message") or "la génération du diagnostic a échoué")
                    raise RuntimeError(message)
                result = {"status": "success", "request": request_result, **published_bundle(job["territory"])}
                with self.lock:
                    job["status"] = "success"
                    job["result"] = result
            except subprocess.TimeoutExpired:
                with self.lock:
                    job["status"] = "failure"
                    job["error"] = {"type": "timeout", "message": "le délai maximal de génération a été dépassé"}
            except Exception as exc:
                with self.lock:
                    job["status"] = "failure"
                    job["error"] = {"type": type(exc).__name__, "message": str(exc)}
            finally:
                with self.lock:
                    job["finished_at"] = now_epoch()
                    self.active_by_request.pop(f"{job['territory']}|{job['scale']}", None)
                self.pending.task_done()


class RateLimiter:
    def __init__(self):
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key):
        cutoff = now_epoch() - 60
        with self.lock:
            bucket = self.hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= RATE_LIMIT:
                return False
            bucket.append(now_epoch())
            return True


JOBS = JobManager()
LIMITER = RateLimiter()


class Handler(SimpleHTTPRequestHandler):
    server_version = "ZonageTerrainVacance/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("[diagnostic-web] " + fmt % args + "\n")

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self' https://geo.api.gouv.fr; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; base-uri 'self'; frame-ancestors 'self'")
        super().end_headers()

    def json_response(self, status, payload, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def client_key(self):
        forwarded = self.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
        return forwarded or self.client_address[0]

    def read_payload(self):
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("corps JSON absent ou trop volumineux")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def serve_page(self):
        if not PAGE.exists():
            self.send_error(503, "Interface indisponible")
            return
        data = PAGE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        self.wfile.write(data)

    def serve_published(self, parsed_path):
        match = re.fullmatch(r"/diagnostics/([0-9A-Z]{5})/(|index\.html|diagnostic\.json|synthesis\.json|levers\.json|priorities\.json)", parsed_path)
        if not match:
            return False
        territory, filename = match.groups()
        filename = filename or "index.html"
        path = PUBLISHED / territory / filename
        if not path.exists() or not path.is_file():
            self.send_error(404, "Diagnostic non publié")
            return True
        data = path.read_bytes()
        content_type = "text/html; charset=utf-8" if filename.endswith(".html") else "application/json; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        self.wfile.write(data)
        return True

    def submit_job(self, territory, scale):
        try:
            code, normalized_scale = validate_request(territory, scale)
        except ValueError as exc:
            self.json_response(400, {"status": "failure", "phase": "input_validation", "error": {"type": "invalid_input", "message": str(exc)}})
            return
        if not LIMITER.allow(self.client_key()):
            self.json_response(429, {"status": "failure", "error": {"type": "rate_limit", "message": "trop de demandes ; réessayez dans une minute"}}, {"Retry-After": "60"})
            return
        try:
            job, created = JOBS.submit(code, normalized_scale)
        except queue.Full:
            self.json_response(503, {"status": "failure", "error": {"type": "queue_full", "message": "le service est momentanément très sollicité"}}, {"Retry-After": "30"})
            return
        self.json_response(202, {**job, "reused": not created, "status_url": f"/api/jobs/{job['id']}"}, {"Location": f"/api/jobs/{job['id']}"})

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self.serve_page()
            return
        if parsed.path == "/robots.txt":
            body = b"User-agent: *\nAllow: /\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/health":
            self.json_response(200, {"status": "ok", "service": "diagnostic-vacance", "version": "1.0", "llm_used": False, "jobs": JOBS.stats()})
            return
        if parsed.path == "/api/ready":
            ready = PAGE.exists() and REQUEST.exists() and os.access(OUTPUT, os.W_OK)
            self.json_response(200 if ready else 503, {"status": "ready" if ready else "not_ready"})
            return
        job_match = re.fullmatch(r"/api/jobs/([0-9a-f]{32})", parsed.path)
        if job_match:
            job = JOBS.get(job_match.group(1))
            if not job:
                self.json_response(404, {"status": "failure", "error": {"type": "job_not_found", "message": "demande inconnue ou expirée"}})
                return
            headers = {"Retry-After": "2"} if job["status"] in {"queued", "running"} else None
            self.json_response(200, job, headers)
            return
        if parsed.path == "/api/diagnostic":
            query = parse_qs(parsed.query)
            self.submit_job((query.get("territory") or query.get("code") or [""])[0], (query.get("scale") or [""])[0])
            return
        if self.serve_published(parsed.path):
            return
        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/diagnostics":
            self.send_error(404, "Not Found")
            return
        try:
            payload = self.read_payload()
        except Exception as exc:
            self.json_response(400, {"status": "failure", "phase": "input_validation", "error": {"type": "invalid_json", "message": str(exc)}})
            return
        self.submit_job(payload.get("territory") or payload.get("code"), payload.get("scale"))


def main():
    parser = argparse.ArgumentParser(description="Service web public du diagnostic territorial de la vacance.")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8765")))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(json.dumps({"status": "ready", "url": f"http://{args.host}:{args.port}/", "health": "/api/health", "ready": "/api/ready", "llm_used": False}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
