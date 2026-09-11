import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / 'cases.db'

FAULT_RULES = {
    'no_power': [
        ('power_input', 25, 'Verify battery/USB input and main power path.'),
        ('short', 35, 'Measure resistance to ground on the main rail before injecting power.'),
        ('boot_sequence', 25, 'Capture the current-draw sequence at power-on.'),
    ],
    'charging': [
        ('usb_current', 30, 'Measure USB input current and compare with a known-good board.'),
        ('battery', 25, 'Check battery voltage and battery connector path.'),
        ('charging_rail', 30, 'Measure charger input/output rails and inspect for short.'),
    ],
    'bootloop': [
        ('boot_sequence', 35, 'Record current draw from button press through reset.'),
        ('rail', 25, 'Verify required rails during the boot attempt.'),
        ('thermal', 15, 'Check for abnormal component heating during the loop.'),
    ],
    'display': [
        ('display_power', 30, 'Measure display power rails at connector and during boot.'),
        ('backlight', 25, 'Check backlight rail/enable and diode measurements.'),
        ('connector', 20, 'Inspect connector, filters and nearby damage under microscope.'),
    ],
    'network': [
        ('rf_power', 30, 'Verify RF power rails and enable sequence.'),
        ('baseband', 25, 'Check baseband-related rails and boot state.'),
        ('antenna', 20, 'Inspect antenna path, connectors and filters.'),
    ],
}


def db_init():
    con = sqlite3.connect(DB)
    con.execute('CREATE TABLE IF NOT EXISTS cases (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
    con.commit(); con.close()


def analyze(data):
    fault = data.get('fault', 'no_power')
    evidence = []
    scores = {}
    next_steps = []
    current = data.get('current_draw', '').strip()
    if current:
        evidence.append(f'Current draw supplied: {current}')
        if '0' in current and ('0.0' in current or '0A' in current):
            scores['power_path_or_short'] = scores.get('power_path_or_short', 0) + 12
    resistance = data.get('resistance', '').strip()
    if resistance:
        evidence.append(f'Resistance supplied: {resistance}')
        try:
            r = float(resistance.replace('Ω','').replace('ohm','').strip())
            if r < 2:
                scores['possible_short'] = scores.get('possible_short', 0) + 35
                next_steps.append('Confirm the low resistance with polarity/diode mode and identify whether the rail is expected to be low impedance.')
            elif r < 10:
                scores['low_impedance_rail'] = scores.get('low_impedance_rail', 0) + 15
        except ValueError:
            evidence.append('Resistance could not be parsed; treat it as technician-entered text.')
    temp = data.get('thermal', '').lower()
    if temp and any(x in temp for x in ['hot','heat','سخونة','حرارة']):
        scores['localized_thermal_fault'] = scores.get('localized_thermal_fault', 0) + 30
        next_steps.append('Use thermal imaging or IPA carefully to localize the heating component, with current limited.')
    for key, pts, step in FAULT_RULES.get(fault, FAULT_RULES['no_power']):
        scores[key] = scores.get(key, 0) + pts
        next_steps.append(step)
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top = ranked[:5]
    max_score = max([v for _, v in top], default=0)
    confidence = min(95, max(10, int(40 + max_score))) if top else 10
    if not resistance and fault in ('no_power','bootloop','charging'):
        confidence = min(confidence, 55)
        next_steps.insert(0, 'Resistance/diode measurements are missing; obtain them before replacing ICs.')
    return {
        'confidence': confidence,
        'hypotheses': [{'name': k, 'score': v, 'rank': i+1} for i,(k,v) in enumerate(top)],
        'evidence': evidence,
        'next_steps': list(dict.fromkeys(next_steps))[:8],
        'disclaimer': 'Decision support only. Validate against the exact board revision, schematic and boardview.'
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type='application/json'):
        raw = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header('Content-Type', content_type); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.path == '/api/health': return self._send(200, json.dumps({'ok': True, 'service': 'mobile-repair-ai'}))
        if self.path in ('/', '/index.html'):
            return self._send(200, (ROOT/'index.html').read_text(encoding='utf-8'), 'text/html; charset=utf-8')
        if self.path == '/app.js': return self._send(200, (ROOT/'app.js').read_text(encoding='utf-8'), 'text/javascript; charset=utf-8')
        self._send(404, json.dumps({'error':'not found'}))
    def do_POST(self):
        length = int(self.headers.get('Content-Length','0'))
        try: data = json.loads(self.rfile.read(length) or '{}')
        except json.JSONDecodeError: return self._send(400, json.dumps({'error':'invalid json'}))
        if self.path == '/api/analyze': return self._send(200, json.dumps(analyze(data), ensure_ascii=False))
        if self.path == '/api/cases':
            con=sqlite3.connect(DB); cur=con.execute('INSERT INTO cases(data) VALUES (?)',(json.dumps(data,ensure_ascii=False),)); con.commit(); cid=cur.lastrowid; con.close(); return self._send(201,json.dumps({'id':cid}))
        self._send(404, json.dumps({'error':'not found'}))

if __name__ == '__main__':
    db_init()
    port = int(os.environ.get('PORT','8000'))
    print(f'Mobile Repair AI listening on http://127.0.0.1:{port}')
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
