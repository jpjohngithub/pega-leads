import os
import sys
import json
import csv
import io
import time
import urllib.request
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import scrape

PORT = int(os.environ.get("PORT", 5000))

class LeadServer(SimpleHTTPRequestHandler):
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/" or url.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            tpl_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
            with open(tpl_path, "rb") as f:
                self.wfile.write(f.read())
        elif url.path == "/api/status":
            engine_ok = False
            try:
                st, _ = scrape.req("GET", "/api/v1/jobs")
                engine_ok = (st == 200)
            except Exception:
                engine_ok = False
            self.send_json({"engine_online": engine_ok, "base_url": scrape.BASE})
        else:
            return super().do_GET()

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/api/search":
            content_length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(content_length)
            params = json.loads(body_data.decode("utf-8"))

            keyword = params.get("keyword", "")
            city = params.get("city", "")
            depth = int(params.get("depth", 5))
            extract_socials = bool(params.get("socials", True))

            try:
                leads = self.hunt_leads(keyword, city, depth, extract_socials)
                self.send_json({"success": True, "leads": leads, "count": len(leads)})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)
        else:
            self.send_response(404)
            self.end_headers()

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def hunt_leads(self, keyword, city, depth, extract_socials):
        geo = scrape.geocode(city, with_bbox=True)
        if not geo:
            raise RuntimeError(f"Localizacao nao encontrada: {city}")
        lat, lon, bbox = geo

        search_term = f"{keyword} in {city}" if city.lower() not in keyword.lower() else keyword

        job_body = {
            "name": f"web_{int(time.time())}",
            "keywords": [search_term],
            "lang": "pt-BR",
            "zoom": 15,
            "lat": lat,
            "lon": lon,
            "fast_mode": False,
            "radius": 10000,
            "depth": depth,
            "email": True,
            "max_time": 300
        }

        try:
            job_id, rows = scrape.run_job(job_body)
        except Exception as e:
            # Fallback mockup caso o docker ainda nao esteja ativo
            raise RuntimeError(f"Falha ao conectar no Gosom Docker ({scrape.BASE}): {e}")

        # Deduplica e normaliza
        unique = scrape.dedupe(rows)

        # Enriquecimento com redes sociais
        if extract_socials:
            scrape.enrich_socials(unique)

        return unique

if __name__ == "__main__":
    os.chdir(os.path.join(os.path.dirname(__file__), "static"))
    server = HTTPServer(("0.0.0.0", PORT), LeadServer)
    print(f"Lead Hunter Web rodando em http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
