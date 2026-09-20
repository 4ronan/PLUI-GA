import argparse
import json
import re
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT=Path(__file__).resolve().parents[1]
PAGE=ROOT/'tests/diagnostic-vacance-page-test.html'
REQUEST=ROOT/'scripts/diagnostic_request.py'
OUTPUT=ROOT/'output'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT),**kwargs)

    def log_message(self,fmt,*args):
        sys.stderr.write('[diagnostic-test-server] '+fmt%args+'\n')

    def json_response(self,status,payload):
        body=json.dumps(payload,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed=urlparse(self.path)
        if parsed.path in {'/','/index.html'}:
            if not PAGE.exists():
                self.send_error(404,'Page test absente')
                return
            data=PAGE.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path=='/api/health':
            self.json_response(200,{
                'status':'ok',
                'service':'diagnostic-vacance-test',
                'interface':'territory+comparison_scale',
                'llm_used':False,
            })
            return
        if parsed.path=='/api/diagnostic':
            self.handle_diagnostic(parsed)
            return
        super().do_GET()

    def handle_diagnostic(self,parsed):
        q=parse_qs(parsed.query)
        territory=str((q.get('territory') or q.get('code') or [''])[0]).strip().upper()
        scale=str((q.get('scale') or [''])[0]).strip()
        refresh=str((q.get('refresh') or ['0'])[0]).strip().lower() in {'1','true','yes','oui','on'}

        if not re.fullmatch(r'[0-9A-Z]{5}',territory):
            self.json_response(400,{
                'status':'failure','phase':'input_validation',
                'error':{'type':'invalid_territory','message':'code INSEE communal attendu sur 5 caractères alphanumériques'},
            })
            return
        if not scale:
            self.json_response(400,{
                'status':'failure','phase':'input_validation',
                'error':{'type':'invalid_scale','message':'échelle requise: département, région ou France'},
            })
            return

        cmd=[sys.executable,str(REQUEST),territory,scale]
        if refresh:
            cmd.append('--force-refresh')
        try:
            proc=subprocess.run(
                cmd,cwd=ROOT,text=True,
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                timeout=1800,
            )
        except subprocess.TimeoutExpired:
            self.json_response(504,{
                'status':'failure','phase':'generation',
                'territory':territory,
                'error':{'type':'timeout','message':'génération interrompue après 1800 secondes'},
            })
            return

        lines=[x for x in (proc.stdout or '').splitlines() if x.strip()]
        request_result=None
        for line in reversed(lines):
            try:
                candidate=json.loads(line)
                if isinstance(candidate,dict) and candidate.get('status'):
                    request_result=candidate
                    break
            except Exception:
                pass
        if proc.returncode!=0 or not request_result or request_result.get('status')!='success':
            self.json_response(422,{
                'status':'failure',
                'phase':(request_result or {}).get('phase','generation'),
                'territory':territory,
                'request':request_result,
                'log_tail':'\n'.join(lines[-20:]),
            })
            return

        published=OUTPUT/'published'/territory
        paths={
            'diagnostic':published/'diagnostic.json',
            'levers':published/'levers.json',
            'priorities':published/'priorities.json',
            'panel':OUTPUT/'diagnostic-3v-panel.json',
            'cache_manifest':OUTPUT/'diagnostic-3ub-manifest.json',
            'production_manifest':OUTPUT/'diagnostic-3u-manifest.json',
        }
        missing=[name for name,path in paths.items() if not path.exists() or path.stat().st_size<=0]
        if missing:
            self.json_response(500,{
                'status':'failure','phase':'publication',
                'territory':territory,
                'error':{'type':'published_files_missing','files':missing},
            })
            return

        bundle={name:read_json(path) for name,path in paths.items()}
        if bundle['diagnostic'].get('territory')!=territory or bundle['panel'].get('territory')!=territory:
            self.json_response(500,{
                'status':'failure','phase':'publication',
                'territory':territory,
                'error':{'type':'territory_mismatch'},
            })
            return

        self.json_response(200,{
            'status':'success',
            'request':request_result,
            **bundle,
        })


def main():
    parser=argparse.ArgumentParser(description='Serveur local de test pour la page intégrée du diagnostic de vacance.')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    print(json.dumps({
        'status':'ready',
        'url':f'http://{args.host}:{args.port}/',
        'health':f'http://{args.host}:{args.port}/api/health',
        'page':str(PAGE.relative_to(ROOT)),
        'llm_used':False,
    },ensure_ascii=False),flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()
