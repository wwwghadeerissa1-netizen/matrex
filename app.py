import json
import os
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / 'cases.db'
ENGINE_VERSION = '2.0.0'

FAULT_LABELS = {
    'no_power': 'لا يعمل', 'bootloop': 'Bootloop / Restart', 'charging': 'لا يشحن',
    'display': 'لا توجد صورة', 'thermal': 'حرارة / استهلاك مرتفع', 'network': 'شبكة / إشارة',
    'wifi': 'Wi‑Fi / Bluetooth', 'audio': 'صوت / ميكروفون', 'liquid': 'ضرر ماء / أكسدة',
}

PROFILES = {
    'no_power': [('main_power','دائرة التغذية الرئيسية / PMIC',28),('main_short','قصر على خط تغذية رئيسي',26),('power_key','مسار Power / زر التشغيل',18),('boot_sequence','تسلسل الإقلاع / CPU / Storage',14),('battery_path','البطارية / BMS / مسار البطارية',10)],
    'bootloop': [('boot_sequence','تسلسل الإقلاع / CPU / Storage',30),('main_power','تغذية غير مستقرة',24),('storage','NAND / Storage',20),('peripheral','طرفية أو حساس يسبب إعادة التشغيل',14),('software','Firmware / Software',12)],
    'charging': [('usb_path','USB / Port / FPC',28),('charge_ic','دائرة الشحن',26),('battery_path','Battery / BMS',20),('vbus_path','VBUS / حماية / مسار الإدخال',18),('software','Software / Accessory',8)],
    'display': [('display_power','تغذيات الشاشة',28),('display_fpc','Display FPC / Connector',22),('display_path','مسار الصورة / Backlight',20),('display_ic','Display/PMIC related IC',18),('board_damage','ضرر لوحة / Filters',12)],
    'thermal': [('rail_short','Short / Leakage على Rail',35),('pmic','PMIC / Power IC',25),('component_leak','مكوّن متسرب',18),('cpu_load','CPU / SoC load',12),('battery','Battery',10)],
    'network': [('rf','RF front-end',28),('baseband','Baseband / Power',27),('antenna','Antenna / Coax / Filters',20),('sim','SIM / Connector',13),('software','Calibration / Software',12)],
    'wifi': [('wifi_ic','Wi‑Fi / Bluetooth IC',34),('rf_power','RF power',24),('antenna','Antenna / Matching',18),('clock','Clock / Crystal',12),('software','Software',12)],
    'audio': [('codec','Audio Codec / IC',30),('audio_path','Speaker / Mic path',25),('connector','Connector / FPC',20),('audio_power','Audio power',15),('software','Software',10)],
    'liquid': [('corrosion','Corrosion / Leakage',32),('rail_short','Shorted capacitor / Rail',25),('connector','Connector damage',20),('power_damage','Power rail damage',15),('secondary','Secondary component failure',8)],
}


def db_init():
    con = sqlite3.connect(DB)
    con.execute('CREATE TABLE IF NOT EXISTS cases (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, result TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
    con.commit(); con.close()


def num(value):
    if value is None: return None
    m = re.search(r'-?\d+(?:[\.,]\d+)?', str(value).replace('Ω','').replace('°',''))
    if not m: return None
    try: return float(m.group(0).replace(',','.'))
    except ValueError: return None


def has(value, *terms):
    s = str(value or '').lower()
    return any(t.lower() in s for t in terms)


def parse_current(text):
    s = str(text or '').replace('→','->').replace('–','-').replace('—','-')
    vals = []
    for token in re.findall(r'\d+(?:[\.,]\d+)?\s*[mµu]?a', s.lower()):
        n = num(token)
        if n is None: continue
        if 'ma' in token: n /= 1000
        vals.append(n)
    if not vals:
        return None
    return vals


def analyze(data):
    fault = data.get('fault') if data.get('fault') in PROFILES else 'no_power'
    scores = {k: float(v) for k,_,v in PROFILES[fault]}
    names = {k:n for k,n,_ in PROFILES[fault]}
    evidence, contradictions, actions = [], [], []
    measurements = {}

    current_text = data.get('current_draw','').strip()
    current = parse_current(current_text)
    if current:
        measurements['current'] = current
        evidence.append(f'سحب الباور: {current_text}')
        if len(current) >= 2 and current[-1] <= 0.005 and max(current) < 0.5:
            scores['boot_sequence'] = scores.get('boot_sequence',0) + 10
            scores['main_power'] = scores.get('main_power',0) + 4
        if len(current) == 1 and current[0] >= 1.0:
            scores['main_short'] = scores.get('main_short',0) + 25
            scores['rail_short'] = scores.get('rail_short',0) + 20
        if current and max(current) >= 0.3 and max(current) < 1.0:
            scores['boot_sequence'] = scores.get('boot_sequence',0) + 7
        if current and all(v <= 0.01 for v in current):
            scores['power_key'] = scores.get('power_key',0) + 15
            scores['battery_path'] = scores.get('battery_path',0) + 10
            actions.append('قِس هل يصل أمر Power/PP_BATT إلى اللوحة أثناء الضغط؛ سحب قريب من الصفر لا يثبت وجود Short.')
    else:
        actions.append('سجّل منحنى السحب من لحظة الضغط على Power حتى 5 ثوانٍ، وليس رقمًا واحدًا فقط.')

    resistance = num(data.get('resistance'))
    resistance_location = data.get('resistance_location','').strip()
    if resistance is not None:
        measurements['resistance'] = resistance
        evidence.append(f'المقاومة إلى الأرضي: {data.get("resistance")} {"عند " + resistance_location if resistance_location else ""}')
        if resistance_location:
            if resistance < 1:
                scores['main_short'] = scores.get('main_short',0) + 18; scores['rail_short'] = scores.get('rail_short',0) + 18
            elif resistance < 5:
                scores['main_short'] = scores.get('main_short',0) + 9; scores['rail_short'] = scores.get('rail_short',0) + 8
        else:
            contradictions.append('قراءة المقاومة بلا تحديد اسم الـRail أو نقطة القياس لا تكفي لإثبات Short.')
            scores['main_short'] = scores.get('main_short',0) + 3
    else:
        actions.append('قِس المقاومة إلى الأرضي على Rail محدد، واكتب اسم الـRail ونقطة القياس وحالة البطارية/المصدر.')

    diode = num(data.get('diode'))
    diode_location = data.get('diode_location','').strip()
    if diode is not None:
        measurements['diode'] = diode
        evidence.append(f'Diode Mode: {data.get("diode")}{" عند " + diode_location if diode_location else ""}')
        if not diode_location:
            contradictions.append('Diode Mode بدون تحديد الخط واتجاه القياس لا يمكن مقارنته بمرجع موثوق.')
        elif diode < 0.15:
            scores['main_short'] = scores.get('main_short',0) + 12; scores['rail_short'] = scores.get('rail_short',0) + 12
        elif diode > 0.9:
            scores['power_key'] = scores.get('power_key',0) + 4
    else:
        actions.append('أضف Diode Mode للخط المشكوك فيه مع اسم الخط واتجاه القياس.')

    battery = num(data.get('battery_voltage'))
    if battery is not None:
        measurements['battery_voltage'] = battery
        evidence.append(f'جهد البطارية: {data.get("battery_voltage")}')
        if battery < 3.2:
            scores['battery_path'] = scores.get('battery_path',0) + 22
            contradictions.append('جهد البطارية منخفض؛ لا يصح تحميل العطل مباشرة على PMIC قبل استبعاد مصدر الطاقة.')
        elif battery >= 3.6:
            scores['battery_path'] = max(0, scores.get('battery_path',0)-5)
    else:
        actions.append('تحقق من جهد البطارية قبل تشخيص دائرة الطاقة، خصوصًا في حالات No Power.')

    rail = data.get('rail','').strip()
    if rail:
        evidence.append(f'Rails: {rail}')
        if has(rail,'مفقود','missing','0v','0 v'):
            scores['main_power'] = scores.get('main_power',0) + 15; scores['rail_short'] = scores.get('rail_short',0) + 8
        if has(rail,'4.2','4.1','4.0'):
            scores['main_power'] = max(0, scores.get('main_power',0)-3)
    else:
        actions.append('قِس الـRails الأساسية أثناء محاولة التشغيل وحدد أي Rail مفقود أو ينهار.')

    thermal = data.get('thermal','').strip()
    if thermal:
        evidence.append(f'الحرارة: {thermal}')
        if has(thermal,'لا توجد','none','طبيعية','normal'):
            contradictions.append('لا توجد نقطة ساخنة واضحة؛ هذا يقلل أولوية القصر الحراري لكنه لا ينفي Short.')
        elif has(thermal,'سخونة','حرارة','hot','°c','c'):
            scores['rail_short'] = scores.get('rail_short',0) + 15; scores['pmic'] = scores.get('pmic',0) + 8
            actions.append('حدد المكوّن الساخن بقياس حراري أو IPA مع تحديد تيار الحقن ضمن حدود آمنة.')

    history = data.get('history','').strip(); symptoms = data.get('symptoms','').strip(); visual = data.get('visual','').strip()
    if history: evidence.append(f'كيفية حدوث العطل: {history}')
    if symptoms: evidence.append(f'الأعراض: {symptoms}')
    if visual:
        evidence.append(f'الفحص البصري: {visual}')
        if has(visual,'أكسدة','ماء','corrosion','liquid'):
            scores['corrosion'] = scores.get('corrosion',0) + 25; scores['connector'] = scores.get('connector',0) + 10
        if has(visual,'كسر','سقوط','damage','crack'):
            scores['board_damage'] = scores.get('board_damage',0) + 15; scores['connector'] = scores.get('connector',0) + 8
    if has(history,'سقوط','drop','وقع'):
        scores['connector'] = scores.get('connector',0) + 7; scores['board_damage'] = scores.get('board_damage',0) + 8
        actions.append('بعد السقوط: افحص FPCs والكونكتورات والفلترات والمكونات المتشققة قبل استبدال IC.')
    if has(history,'ماء','liquid','water'):
        scores['corrosion'] = scores.get('corrosion',0) + 20; actions.append('بعد الماء: افصل الطاقة، افحص الأكسدة والـFPCs ومقاومات الخطوط قبل أي تشغيل متكرر.')

    # Cross-measurement consistency checks.
    if resistance is not None and diode is not None and resistance < 2 and diode > 0.25:
        contradictions.append('المقاومة منخفضة نسبيًا بينما Diode Mode ليس قريبًا من الصفر؛ لا تعتبر الحالة Short مؤكدًا قبل المقارنة المرجعية.')
        scores['main_short'] = max(0, scores.get('main_short',0)-8)
    if rail and battery is not None and battery >= 3.6 and has(rail,'vdd_main','pp_vdd_main') and has(rail,'4.2','4.1'):
        evidence.append('الـMain rail يبدو موجودًا وفق الوصف؛ هذا يقلل احتمال انقطاع الإدخال الخام.')
        scores['power_key'] = scores.get('power_key',0) + 4

    # Remove irrelevant keys for the current fault profile, while retaining cross-cutting diagnoses.
    labels_extra = {
        'possible_short':'قصر محتمل', 'power_path_or_short':'مسار تغذية / قصر محتمل', 'localized_thermal_fault':'عطل حراري موضعي',
        'connector':'Connector / FPC / Filters', 'rail_short':'Short / Leakage على Rail', 'pmic':'PMIC / Power IC',
        'battery_path':'Battery / BMS / مسار البطارية', 'main_power':'دائرة التغذية الرئيسية / PMIC', 'main_short':'Short على Rail رئيسي',
        'power_key':'Power Key / مسار التشغيل', 'boot_sequence':'تسلسل الإقلاع', 'storage':'Storage / NAND', 'peripheral':'طرفية / Sensor',
        'software':'Software / Firmware', 'usb_path':'USB / Port / FPC', 'charge_ic':'Charging IC', 'vbus_path':'VBUS / Protection',
        'display_power':'Display Power', 'display_fpc':'Display FPC / Connector', 'display_path':'Display / Backlight path', 'display_ic':'Display IC',
        'board_damage':'Board damage', 'rail_short':'Short / Leakage على Rail', 'component_leak':'Component leakage', 'cpu_load':'CPU / SoC load', 'battery':'Battery',
        'rf':'RF front-end', 'baseband':'Baseband / Power', 'antenna':'Antenna / Coax', 'sim':'SIM / Connector', 'wifi_ic':'Wi‑Fi / BT IC', 'rf_power':'RF Power', 'clock':'Clock / Crystal',
        'codec':'Audio Codec / IC', 'audio_path':'Audio path', 'audio_power':'Audio Power', 'corrosion':'Corrosion / Leakage', 'power_damage':'Power rail damage', 'secondary':'Secondary component failure'
    }
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    ranked = [(k,v) for k,v in ranked if v > 0]
    total = sum(v for _,v in ranked[:8]) or 1
    top = ranked[:6]
    hypotheses = []
    for i,(key,raw) in enumerate(top,1):
        share = round(raw/total*100)
        hypotheses.append({'rank':i,'key':key,'name':names.get(key, labels_extra.get(key,key)),'score':share,'raw_score':round(raw,1)})

    # Confidence is capped when critical context is missing or contradictory.
    confidence = 35 + (hypotheses[0]['score'] if hypotheses else 0)//2
    if not current: confidence -= 8
    if fault in ('no_power','bootloop') and battery is None: confidence -= 8
    if resistance is None: confidence -= 7
    if contradictions: confidence -= min(18, 4*len(contradictions))
    confidence = max(20, min(92, int(confidence)))

    # Select a discriminating next measurement, not a generic list.
    next_steps = []
    if fault in ('no_power','bootloop') and not current:
        next_steps.append('الأولوية 1: سجّل منحنى DCPS أثناء الضغط: قيمة البداية، الذروة، مدة السحب، وهل يعود للصفر أو يبقى ثابتًا.')
    elif fault in ('no_power','bootloop') and not battery:
        next_steps.append('الأولوية 1: قِس جهد البطارية تحت الحمل. لا تعتمد على قراءة البطارية بدون تحميل.')
    elif fault in ('no_power','bootloop') and not resistance_location:
        next_steps.append('الأولوية 1: حدد اسم Rail ونقطة قياس المقاومة، ثم قارنها بلوحة سليمة/Boardview قبل استنتاج Short.')
    elif resistance is not None and diode is None:
        next_steps.append('الأولوية 1: قِس Diode Mode على نفس الخط وبالاتجاه نفسه المرجعي؛ هذه القراءة ستفصل بين Low impedance طبيعي وShort محتمل.')
    elif rail and has(rail,'missing','مفقود','0v'):
        next_steps.append('الأولوية 1: تتبع الـRail المفقود من المصدر إلى الحمل، وقِس قبل/بعد الملف أو الـfilter لتحديد نقطة الانقطاع.')
    elif thermal and has(thermal,'سخونة','hot','حرارة'):
        next_steps.append('الأولوية 1: حدد أول مكوّن ترتفع حرارته، ثم أعد القياس بتيار محدود لتحديد مسار التسريب.')
    else:
        next_steps.append('الأولوية 1: اختر القياس الذي يميّز بين أعلى احتمالين بدل تبديل أي IC.')
    next_steps += actions[:5]

    return {
        'engine_version': ENGINE_VERSION, 'fault_label': FAULT_LABELS.get(fault,fault), 'confidence': confidence,
        'hypotheses': hypotheses, 'evidence': evidence, 'contradictions': contradictions,
        'measurements': measurements, 'next_steps': list(dict.fromkeys(next_steps))[:7],
        'method': ['تحليل نمط العطل','وزن القياسات','فحص التناقضات','اختيار القياس الأكثر تمييزًا','إعادة التقييم بعد القياس'],
        'disclaimer':'النتيجة ترجيح تشخيصي وليست إثباتًا. لا تستبدل IC أو تحقن تيارًا اعتمادًا على الاحتمال وحده. استخدم مخطط/Boardview ومرجع لوحة سليمة عندما يتوفران.'
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type='application/json'):
        raw = body if isinstance(body, bytes) else body.encode('utf-8')
        self.send_response(code); self.send_header('Content-Type',content_type); self.send_header('Content-Length',str(len(raw))); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Access-Control-Allow-Headers','Content-Type'); self.end_headers(); self.wfile.write(raw)
    def do_OPTIONS(self): self._send(204,b'')
    def do_GET(self):
        if self.path == '/api/health': return self._send(200,json.dumps({'ok':True,'service':'matrex','engine_version':ENGINE_VERSION}))
        if self.path in ('/','/index.html'): return self._send(200,(ROOT/'index.html').read_text(encoding='utf-8'),'text/html; charset=utf-8')
        if self.path == '/app.js': return self._send(200,(ROOT/'app.js').read_text(encoding='utf-8'),'text/javascript; charset=utf-8')
        self._send(404,json.dumps({'error':'not found'}))
    def do_POST(self):
        try: length=int(self.headers.get('Content-Length','0')); data=json.loads(self.rfile.read(length) or '{}')
        except Exception: return self._send(400,json.dumps({'error':'invalid json'}))
        if self.path == '/api/analyze':
            result=analyze(data); return self._send(200,json.dumps(result,ensure_ascii=False))
        if self.path == '/api/cases':
            result=analyze(data); con=sqlite3.connect(DB); cur=con.execute('INSERT INTO cases(data,result) VALUES (?,?)',(json.dumps(data,ensure_ascii=False),json.dumps(result,ensure_ascii=False))); con.commit(); cid=cur.lastrowid; con.close(); return self._send(201,json.dumps({'id':cid,'result':result},ensure_ascii=False))
        self._send(404,json.dumps({'error':'not found'}))

if __name__ == '__main__':
    db_init(); port=int(os.environ.get('PORT','8000')); ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
