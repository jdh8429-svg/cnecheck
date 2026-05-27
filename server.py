import os
import json
import re
import subprocess
import threading
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from spell_engine import check as offline_check
import naver_spell

app = Flask(__name__, static_folder='public', static_url_path='')
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BINARY_PATH = os.path.join(BASE_DIR, 'bin', 'kogrammar.exe')
FOREIGN_WORDS_PATH = os.path.join(BASE_DIR, 'data', 'foreign-words.json')

with open(FOREIGN_WORDS_PATH, 'r', encoding='utf-8') as f:
    raw = json.load(f)
    FOREIGN_WORDS = {k: v for k, v in raw.items() if not k.startswith('_')}


# ──────────────────────────────────────────
#  MCP Client  (kogrammar.exe via stdio JSON-RPC)
# ──────────────────────────────────────────

class MCPClient:
    """Minimal MCP stdio client for kogrammar.exe."""

    def __init__(self, binary_path: str):
        self.binary_path = binary_path
        self.process = None
        self._id_counter = 0
        self._pending: dict[int, dict] = {}   # id → {event, result, error}
        self._id_lock = threading.Lock()
        self.ready = False

    # ── lifecycle ──────────────────────────

    def start(self) -> bool:
        if not os.path.exists(self.binary_path):
            print(f"[MCP] binary not found: {self.binary_path}")
            return False
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            self.process = subprocess.Popen(
                [self.binary_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=flags,
            )
            threading.Thread(target=self._read_loop, daemon=True).start()
            self._initialize()
            self.ready = True
            print("[MCP] kogrammar.exe ready")
            return True
        except Exception as exc:
            print(f"[MCP] start failed: {exc}")
            return False

    # ── I/O helpers ────────────────────────

    def _write_line(self, msg: dict):
        line = json.dumps(msg, ensure_ascii=False) + '\n'
        self.process.stdin.write(line.encode('utf-8'))
        self.process.stdin.flush()

    def _read_loop(self):
        for raw_bytes in self.process.stdout:
            line = raw_bytes.decode('utf-8', errors='replace').strip()
            if not line.startswith('{'):
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            mid = msg.get('id')
            if mid is not None and mid in self._pending:
                entry = self._pending[mid]   # update in-place, do NOT pop yet
                entry['result'] = msg.get('result')
                entry['error'] = msg.get('error')
                entry['event'].set()

    # ── RPC ────────────────────────────────

    def _rpc(self, method: str, params: dict, timeout: float = 20) -> dict:
        with self._id_lock:
            self._id_counter += 1
            mid = self._id_counter

        event = threading.Event()
        self._pending[mid] = {'event': event, 'result': None, 'error': None}

        self._write_line({'jsonrpc': '2.0', 'id': mid, 'method': method, 'params': params})

        if not event.wait(timeout):
            self._pending.pop(mid, None)
            raise TimeoutError('MCP call timed out')

        entry = self._pending.pop(mid)
        if entry['error']:
            raise Exception(str(entry['error']))
        return entry['result'] or {}

    def _notify(self, method: str):
        self._write_line({'jsonrpc': '2.0', 'method': method})

    def _initialize(self):
        self._rpc('initialize', {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'hangul-web', 'version': '1.0.0'},
        }, timeout=10)
        self._notify('notifications/initialized')

    # ── public API ─────────────────────────

    def check_grammar(self, text: str) -> dict:
        return self._rpc('tools/call', {
            'name': 'check_korean_grammar',
            'arguments': {'text': text},
        })


mcp = MCPClient(BINARY_PATH)
mcp.start()


# ──────────────────────────────────────────
#  Parse MCP tool result → structured data
# ──────────────────────────────────────────

def parse_grammar_result(raw: dict) -> dict:
    content = raw.get('content', [])
    text_out = '\n'.join(
        c.get('text', '') for c in content if c.get('type') == 'text'
    ).strip()

    corrections = []
    for m in re.finditer(r'"?([^"→\n]+?)"?\s*→\s*"?([^"\n]+?)"?(?=\s*$|\s*\n)', text_out, re.MULTILINE):
        orig = m.group(1).strip().strip('"')
        sugg = m.group(2).strip().strip('"')
        if orig and sugg and orig != sugg:
            corrections.append({'original': orig, 'suggestion': sugg})

    return {
        'raw': text_out,
        'corrections': corrections,
        'has_errors': bool(corrections),
    }


# ──────────────────────────────────────────
#  Routes
# ──────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')


@app.route('/api/status')
def api_status():
    return jsonify({
        'kogrammar_ready': mcp.ready,
        'binary_exists': os.path.exists(BINARY_PATH),
    })


@app.route('/api/spell-check', methods=['POST'])
def spell_check():
    body = request.get_json(silent=True) or {}
    text = (body.get('text') or '').strip()
    if not text:
        return jsonify({'error': '텍스트를 입력해주세요.'}), 400
    if len(text) > 3000:
        return jsonify({'error': '텍스트는 3000자 이내로 입력해주세요.'}), 400

    # 1순위: 네이버 맞춤법 검사기 (인터넷 연결 시)
    try:
        result = naver_spell.check(text)
        result['engine'] = '네이버 맞춤법 검사기'
        return jsonify(result)
    except Exception as naver_exc:
        pass   # 네이버 실패 시 다음 단계로

    # 2순위: kogrammar MCP (인터넷 연결 시)
    if mcp.ready:
        try:
            raw = mcp.check_grammar(text)
            result = parse_grammar_result(raw)
            result['engine'] = 'kogrammar (온라인)'
            return jsonify(result)
        except Exception:
            pass

    # 3순위: 오프라인 규칙 엔진
    result = offline_check(text)
    result['engine'] = '오프라인 규칙 엔진 (인터넷 연결 불필요)'
    return jsonify(result)


@app.route('/api/foreign-convert', methods=['POST'])
def foreign_convert():
    body = request.get_json(silent=True) or {}
    text = (body.get('text') or '').strip()
    if not text:
        return jsonify({'error': '텍스트를 입력해주세요.'}), 400

    result = text
    changes = []
    # Longer phrases first to avoid partial matches
    for foreign, korean in sorted(FOREIGN_WORDS.items(), key=lambda x: -len(x[0])):
        pattern = re.compile(re.escape(foreign))
        if pattern.search(result):
            changes.append({'from': foreign, 'to': korean})
            result = pattern.sub(f'\x00{korean}\x00', result)  # temp sentinel

    # Replace sentinels (prevents double-substitution)
    result = result.replace('\x00', '')

    return jsonify({
        'original': text,
        'converted': result,
        'changes': changes,
        'change_count': len(changes),
    })


@app.route('/api/foreign-words')
def list_foreign_words():
    categories = {
        '회의·행사': ['미팅', '워크숍', '세미나', '포럼', '심포지엄', '콘퍼런스', '컨퍼런스',
                    '어젠다', '아젠다', '프레젠테이션', '프리젠테이션', '웨비나'],
        '문서·보고': ['매뉴얼', '리포트', '가이드라인', '가이드', '체크리스트', '로드맵',
                    '타임라인', '마일스톤', '보도자료', '프레스릴리즈', '뉴스레터'],
        '디지털·IT': ['데이터', '빅데이터', '플랫폼', '네트워크', '인프라', '소프트웨어',
                     '하드웨어', '홈페이지', '웹사이트', '이메일', '클라우드', '모바일'],
        '경영·조직': ['아웃소싱', '컨설팅', '리더십', '매니지먼트', '거버넌스', '스타트업',
                    '파트너십', '팀워크', '시너지', '콜라보레이션', '이노베이션'],
        '공공·행정': ['MOU', 'TF', '태스크포스', '샌드박스', '규제샌드박스', 'SNS',
                    '바우처', '인센티브', 'KPI', '원스톱', '원스톱서비스'],
    }
    assigned = set()
    grouped = {}
    for cat, keys in categories.items():
        grouped[cat] = {k: FOREIGN_WORDS[k] for k in keys if k in FOREIGN_WORDS}
        assigned.update(keys)
    grouped['기타'] = {k: v for k, v in FOREIGN_WORDS.items() if k not in assigned}
    return jsonify(grouped)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"한글 유틸리티 서버 시작: http://localhost:{port}")
    app.run(debug=False, host='0.0.0.0', port=port)
