import os
import json
import yaml
import time
import boto3
from flask import Flask, render_template_string, request, send_file, url_for, redirect

# --- New Relic 初期化 (Lambda環境変数を読み込む) ---
import newrelic.agent
try:
    # Lambda環境では設定ファイルなしで環境変数から初期化を試みる
    newrelic.agent.initialize()
except:
    pass

from pysmi.reader import FileReader
from pysmi.searcher import StubSearcher
from pysmi.writer import PyFileWriter
from pysmi.parser import SmiStarParser
from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler

app = Flask(__name__)

# New RelicでFlaskアプリ全体をラップ (WSGI計測)
app.wsgi_app = newrelic.agent.WSGIApplicationWrapper(app.wsgi_app)

# --- Lambda環境対応: 書き込み可能な /tmp ディレクトリを使用 ---
UPLOAD_FOLDER = '/tmp/uploads'
OUTPUT_FOLDER = '/tmp/outputs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ---------------------------------------------------------
# 1. 翻訳データ (Dictionary)
# ---------------------------------------------------------
TRANSLATIONS = {
    'ja': {
        'title': 'MIB to Ktranslate コンバーター',
        'step1_title': 'Step 1: MIBファイルのアップロード',
        'step1_desc': 'MIBファイルをアップロードしてください。次の画面で対象のOIDを選択できます。',
        'btn_parse': '解析して選択画面へ',
        'step2_title': 'Step 2: OIDの選択',
        'step2_desc': 'プロファイルに含めたいメトリクスを選択してください。',
        'toggle_all': '全て選択 / 解除',
        'col_select': '選択',
        'col_name': '名前 (Symbol)',
        'col_oid': 'OID',
        'col_ai_desc': 'AI解説 (Bedrock)',
        'col_importance': '重要度',
        'btn_generate': 'YAMLを生成する',
        'btn_back': '戻る',
        'step3_title': 'Step 3: 生成完了',
        'step3_desc': '以下の内容で生成されました。',
        'btn_download': 'YAMLファイルをダウンロード',
        'btn_home': '最初に戻る',
        'lang_switch_label': 'English',
        'ai_loading': 'AIが解析中...'
    },
    'en': {
        'title': 'MIB to Ktranslate Converter',
        'step1_title': 'Step 1: Upload MIB File',
        'step1_desc': 'Please upload a MIB file. You can select target OIDs in the next screen.',
        'btn_parse': 'Parse & Next',
        'step2_title': 'Step 2: Select OIDs',
        'step2_desc': 'Select metrics to include in the profile.',
        'toggle_all': 'Select All / None',
        'col_select': 'Select',
        'col_name': 'Symbol Name',
        'col_oid': 'OID',
        'col_ai_desc': 'AI Description (Bedrock)',
        'col_importance': 'Importance',
        'btn_generate': 'Generate YAML',
        'btn_back': 'Back',
        'step3_title': 'Step 3: Completed',
        'step3_desc': 'The profile has been generated successfully.',
        'btn_download': 'Download YAML',
        'btn_home': 'Go Home',
        'lang_switch_label': '日本語',
        'ai_loading': 'AI is analyzing...'
    }
}

# ---------------------------------------------------------
# 2. HTML テンプレート
# ---------------------------------------------------------
HTML_BASE = """
<!doctype html>
<html lang="{{ lang }}">
<head>
    <meta charset="UTF-8">
    <title>{{ txt.title }}</title>
    <style>
        body { font-family: sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; color: #333; }
        .container { border: 1px solid #ddd; padding: 20px; border-radius: 8px; background-color: #fff; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #eee; padding-bottom: 10px; margin-bottom: 20px; }
        .lang-switch a { text-decoration: none; font-weight: bold; color: #007bff; border: 1px solid #007bff; padding: 5px 10px; border-radius: 4px; }
        .lang-switch a:hover { background-color: #007bff; color: white; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 14px; }
        th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
        th { background-color: #f8f9fa; font-weight: bold; }
        button { padding: 10px 20px; background-color: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
        button:hover { background-color: #0056b3; }
        .back-btn { background-color: #6c757d; }
        .back-btn:hover { background-color: #5a6268; }
        textarea { width: 100%; height: 400px; font-family: monospace; border: 1px solid #ccc; padding: 10px; background-color: #f8f9fa; }
        .badge-high { color: #dc3545; font-weight: bold; background-color: #ffe6e6; padding: 2px 6px; border-radius: 4px; }
        .badge-low { color: #6c757d; background-color: #e9ecef; padding: 2px 6px; border-radius: 4px; }
        .loading { font-style: italic; color: #666; }
    </style>
    <script>
        function toggleAll(source) {
            checkboxes = document.getElementsByName('selected_symbols');
            for(var i=0, n=checkboxes.length;i<n;i++) {
                checkboxes[i].checked = source.checked;
            }
        }
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{{ txt.title }}</h1>
            <div class="lang-switch">
                <a href="?lang={{ 'en' if lang == 'ja' else 'ja' }}">{{ txt.lang_switch_label }}</a>
            </div>
        </div>
        {% block content %}{% endblock %}
    </div>
</body>
</html>
"""

HTML_UPLOAD = HTML_BASE + """
{% block content %}
    <h2>{{ txt.step1_title }}</h2>
    <p>{{ txt.step1_desc }}</p>
    <form action="/parse?lang={{ lang }}" method="post" enctype="multipart/form-data">
        <input type="file" name="mib_file" required>
        <br><br>
        <button type="submit">{{ txt.btn_parse }}</button>
    </form>
{% endblock %}
"""

HTML_SELECT = HTML_BASE + """
{% block content %}
    <h2>{{ txt.step2_title }}</h2>
    <p>{{ txt.step2_desc }} (MIB: {{ mib_name }})</p>
    
    <form action="/generate?lang={{ lang }}" method="post">
        <input type="hidden" name="json_path" value="{{ json_path }}">
        <input type="hidden" name="mib_name" value="{{ mib_name }}">
        
        <label><input type="checkbox" onClick="toggleAll(this)" checked> {{ txt.toggle_all }}</label>

        <table>
            <thead>
                <tr>
                    <th width="5%">{{ txt.col_select }}</th>
                    <th width="20%">{{ txt.col_name }}</th>
                    <th width="45%">{{ txt.col_ai_desc }}</th>
                    <th width="10%">{{ txt.col_importance }}</th>
                    <th width="20%">{{ txt.col_oid }}</th>
                </tr>
            </thead>
            <tbody>
            {% for item in candidates %}
                <tr>
                    <td><input type="checkbox" name="selected_symbols" value="{{ item.name }}" checked></td>
                    <td><b>{{ item.name }}</b></td>
                    <td>{{ item.ai_desc if item.ai_desc else '-' }}</td>
                    <td>
                        {% if item.importance == 'High' or item.importance == '高' %}
                            <span class="badge-high">{{ item.importance }}</span>
                        {% else %}
                            <span class="badge-low">{{ item.importance }}</span>
                        {% endif %}
                    </td>
                    <td><small>{{ item.oid }}</small></td>
                </tr>
            {% endfor %}
            </tbody>
        </table>
        <br>
        <button type="submit">{{ txt.btn_generate }}</button>
        <a href="/?lang={{ lang }}"><button type="button" class="back-btn">{{ txt.btn_back }}</button></a>
    </form>
{% endblock %}
"""

HTML_RESULT = HTML_BASE + """
{% block content %}
    <h2>{{ txt.step3_title }}</h2>
    <p>{{ txt.step3_desc }}</p>
    <textarea readonly>{{ yaml_content }}</textarea>
    <br><br>
    <a href="/download/{{ filename }}" download>
        <button>{{ txt.btn_download }}</button>
    </a>
    <a href="/?lang={{ lang }}">
        <button type="button" class="back-btn">{{ txt.btn_home }}</button>
    </a>
{% endblock %}
"""

# ---------------------------------------------------------
# 3. ヘルパー関数 (MIB解析 & AI)
# ---------------------------------------------------------

def parse_mib_to_json(mib_path, output_dir):
    """pysmiを使ってMIBをJSONに変換"""
    mib_dir = os.path.dirname(mib_path)
    mib_filename = os.path.basename(mib_path)
    mib_name = os.path.splitext(mib_filename)[0]

    mibSearcher = StubSearcher(mib_dir)
    mibParser = SmiStarParser()
    mibWriter = PyFileWriter(output_dir)
    mibCompiler = MibCompiler(mibParser, JsonCodeGen(), mibWriter)
    mibCompiler.addSources(FileReader(mib_dir))
    
    # 依存関係エラーが出ても一旦無視して解析を試みる
    try:
        results = mibCompiler.compile(mib_name)
    except Exception as e:
        print(f"Compile Warning: {e}")
        # 強制的にJSONパスを確認
        pass

    json_file = os.path.join(output_dir, mib_name + '.json')
    if os.path.exists(json_file):
        return json_file, mib_name
    return None, None

def extract_candidates(json_path):
    """JSONからOID候補リストを抽出"""
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    candidates = []
    for symbol, info in sorted(data.items()):
        if isinstance(info, dict) and 'oid' in info and 'nodetype' in info:
            if info['nodetype'] in ['scalar', 'column']:
                candidates.append({
                    'name': symbol,
                    'oid': info['oid'],
                    'nodetype': info['nodetype']
                })
    return candidates

def get_ai_descriptions(symbol_list, lang='ja'):
    """Amazon Bedrock (Claude 3 Haiku) を呼び出して解説を生成"""
    if not symbol_list:
        return {}

    try:
        bedrock = boto3.client(service_name='bedrock-runtime', region_name='ap-northeast-1')
        
        # OID名リストを文字列化 (長すぎるとエラーになるため上位30個程度に制限推奨だが、今回はそのまま)
        target_symbols = symbol_list[:50] 
        symbols_str = "\n".join(target_symbols)
        
        lang_instruction = "Japanese" if lang == 'ja' else "English"
        
        prompt = f"""
        You are a network monitoring expert.
        Explain the following SNMP OID symbols in {lang_instruction}.
        Also determine the importance (High/Low) for monitoring.
        
        Return ONLY valid JSON format mapping the symbol to description and importance.
        Do not include any markdown formatting or explanation outside the JSON.
        
        Example format:
        {{
            "oid_name": {{ "desc": "Explanation here", "importance": "High" }}
        }}
        
        Symbols:
        {symbols_str}
        """

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        })

        response = bedrock.invoke_model(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',
            body=body
        )
        
        response_body = json.loads(response.get('body').read())
        ai_result_text = response_body['content'][0]['text']
        
        # JSON部分だけを抽出する簡易ロジック
        start = ai_result_text.find('{')
        end = ai_result_text.rfind('}') + 1
        if start != -1 and end != -1:
            json_str = ai_result_text[start:end]
            return json.loads(json_str)
        return {}

    except Exception as e:
        print(f"AI Error: {e}")
        return {}

def generate_yaml_structure(json_path, mib_name, selected_symbols):
    with open(json_path, 'r') as f:
        data = json.load(f)

    metrics = []
    for symbol in selected_symbols:
        if symbol in data:
            metrics.append({
                'MIB': mib_name,
                'symbol': {
                    'OID': data[symbol]['oid'],
                    'name': symbol
                }
            })

    return {'metrics': metrics, 'sysobjectid': '1.3.6.1.4.1.CHANGE_THIS'}

# ---------------------------------------------------------
# 4. ルーティング
# ---------------------------------------------------------

@app.route('/', methods=['GET'])
def index():
    lang = request.args.get('lang', 'ja')
    return render_template_string(HTML_UPLOAD, txt=TRANSLATIONS.get(lang, TRANSLATIONS['ja']), lang=lang)

@app.route('/parse', methods=['POST'])
@newrelic.agent.background_task(name="parse_mib_task", group="MIB_Processing")
def parse():
    lang = request.args.get('lang', 'ja')
    newrelic.agent.add_custom_parameter('user_language', lang)

    if 'mib_file' not in request.files: return 'No file', 400
    file = request.files['mib_file']
    if file.filename == '': return 'No file selected', 400

    if file:
        newrelic.agent.add_custom_parameter('mib_filename', file.filename)
        
        # Lambdaの一時領域に保存
        mib_path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(mib_path)

        # MIB解析
        with newrelic.agent.FunctionTrace(name='parse_mib_logic'):
            json_path, mib_name = parse_mib_to_json(mib_path, OUTPUT_FOLDER)
        
        if json_path and os.path.exists(json_path):
            candidates_raw = extract_candidates(json_path)
            newrelic.agent.add_custom_parameter('oid_candidate_count', len(candidates_raw))
            
            # AI解説生成 (Bedrock)
            symbols = [c['name'] for c in candidates_raw]
            
            start_time = time.time()
            with newrelic.agent.FunctionTrace(name='bedrock_ai_generation'):
                ai_data = get_ai_descriptions(symbols, lang=lang)
            duration = time.time() - start_time
            newrelic.agent.add_custom_parameter('ai_duration_sec', duration)

            # データマージ
            candidates = []
            for c in candidates_raw:
                c_name = c['name']
                ai_info = ai_data.get(c_name, {"desc": "", "importance": "-"})
                c['ai_desc'] = ai_info.get('desc', '')
                c['importance'] = ai_info.get('importance', '-')
                candidates.append(c)

            return render_template_string(HTML_SELECT, 
                                          txt=TRANSLATIONS.get(lang, TRANSLATIONS['ja']), 
                                          lang=lang,
                                          candidates=candidates, 
                                          mib_name=mib_name, 
                                          json_path=json_path)
        else:
            return "Failed to parse MIB file. Please check if it has dependencies."

@app.route('/generate', methods=['POST'])
def generate():
    lang = request.args.get('lang', 'ja')
    selected_symbols = request.form.getlist('selected_symbols')
    json_path = request.form.get('json_path')
    mib_name = request.form.get('mib_name')

    if not json_path or not os.path.exists(json_path):
        return "Session expired or file not found."

    profile_data = generate_yaml_structure(json_path, mib_name, selected_symbols)
    yaml_content = yaml.dump(profile_data, sort_keys=False, default_flow_style=False)

    output_filename = f"{mib_name}_profile.yaml"
    output_path = os.path.join(OUTPUT_FOLDER, output_filename)
    with open(output_path, 'w') as f:
        f.write(yaml_content)

    return render_template_string(HTML_RESULT, 
                                  txt=TRANSLATIONS.get(lang, TRANSLATIONS['ja']), 
                                  lang=lang,
                                  yaml_content=yaml_content, 
                                  filename=output_filename)

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(OUTPUT_FOLDER, filename), as_attachment=True)

if __name__ == '__main__':
    # ローカル実行用
    app.run(host='0.0.0.0', port=8080, debug=True)