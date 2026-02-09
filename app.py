import os
import json
import yaml
import time
import boto3
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS # フロントエンドからのアクセスを許可

# --- New Relic 初期化 ---
import newrelic.agent
try:
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
# CORSを有効化 (全てのオリジンからのアクセスを許可)
CORS(app)

# New RelicでFlaskアプリ全体をラップ
app.wsgi_app = newrelic.agent.WSGIApplicationWrapper(app.wsgi_app)

# Lambda環境対応
UPLOAD_FOLDER = '/tmp/uploads'
OUTPUT_FOLDER = '/tmp/outputs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ---------------------------------------------------------
# ヘルパー関数 (ロジック)
# ---------------------------------------------------------

def parse_mib_to_json(mib_path, output_dir):
    """MIBファイルを解析してJSONファイルを生成"""
    mib_dir = os.path.dirname(mib_path)
    mib_filename = os.path.basename(mib_path)
    mib_name = os.path.splitext(mib_filename)[0]

    mibSearcher = StubSearcher(mib_dir)
    mibParser = SmiStarParser()
    mibWriter = PyFileWriter(output_dir)
    mibCompiler = MibCompiler(mibParser, JsonCodeGen(), mibWriter)
    mibCompiler.addSources(FileReader(mib_dir))
    
    try:
        # 依存関係エラーが出ても解析できる部分だけ出力させる
        mibCompiler.compile(mib_name)
    except Exception as e:
        print(f"Compile Warning: {e}")

    json_file = os.path.join(output_dir, mib_name + '.json')
    if os.path.exists(json_file):
        return json_file, mib_name
    return None, None

def extract_oid_info(json_path):
    """JSONからMetrics候補とTrap候補を抽出"""
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    metrics = []
    traps = []

    for symbol, info in sorted(data.items()):
        if isinstance(info, dict) and 'oid' in info:
            nodetype = info.get('nodetype', '')
            description = info.get('description', '') # MIBのコメントを取得

            # Metrics候補 (scalar, column)
            if nodetype in ['scalar', 'column']:
                metrics.append({
                    'name': symbol,
                    'oid': info['oid'],
                    'nodetype': nodetype,
                    'description': description
                })
            
            # Trap候補 (notification, trap)
            # notification: SNMPv2/v3, trap: SNMPv1
            elif nodetype in ['notification', 'trap']:
                traps.append({
                    'name': symbol,
                    'oid': info['oid'],
                    'nodetype': nodetype,
                    'description': description # ここにデフォルトのコメントが入る
                })

    return metrics, traps

def get_ai_descriptions(symbol_list, lang='ja'):
    """Bedrockで解説を生成 (変更なし)"""
    if not symbol_list: return {}
    try:
        bedrock = boto3.client(service_name='bedrock-runtime', region_name='ap-northeast-1')
        # タイムアウト回避のため件数を絞る
        target_symbols = symbol_list[:30]
        symbols_str = "\n".join(target_symbols)
        lang_instruction = "Japanese" if lang == 'ja' else "English"
        
        prompt = f"""
        You are a network monitoring expert.
        Explain the following SNMP OID symbols in {lang_instruction}.
        Also determine the importance (High/Low) for monitoring.
        Return ONLY valid JSON format.
        {{ "oid_name": {{ "desc": "Explanation", "importance": "High" }} }}
        Symbols: {symbols_str}
        """

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}]
        })

        response = bedrock.invoke_model(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',
            body=body
        )
        response_body = json.loads(response.get('body').read())
        ai_result_text = response_body['content'][0]['text']
        
        start = ai_result_text.find('{')
        end = ai_result_text.rfind('}') + 1
        if start != -1 and end != -1:
            return json.loads(ai_result_text[start:end])
        return {}
    except Exception as e:
        print(f"AI Error: {e}")
        return {}

def generate_profile_yaml(mib_name, metrics_data, traps_data):
    """
    KTranslate用のProfile YAML構造を生成
    metrics_data: ユーザーが選択したメトリクスのリスト
    traps_data: ユーザーが選択・編集したTrapのリスト
    """
    profile = {
        'extends': [], # 必要に応じて
        'sysobjectid': '1.3.6.1.4.1.CHANGE_THIS', # ユーザーに後で書き換えてもらう想定
        'metrics': [],
        'traps': []
    }

    # Metricsセクションの構築
    for m in metrics_data:
        profile['metrics'].append({
            'MIB': mib_name,
            'symbol': {
                'OID': m['oid'],
                'name': m['name']
            }
        })

    # Trapsセクションの構築 (ここが新機能)
    for t in traps_data:
        profile['traps'].append({
            'MIB': mib_name,
            'symbol': {
                'OID': t['oid'],
                'name': t['name']
            },
            # ユーザーが編集した説明文を入れる
            'description': t.get('user_description', t.get('description', ''))
        })

    return profile

# ---------------------------------------------------------
# API エンドポイント
# ---------------------------------------------------------

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

@app.route('/parse', methods=['POST'])
@newrelic.agent.background_task(name="parse_mib_task", group="MIB_Processing")
def parse():
    """Step 1: MIBを受け取り、解析結果(Metrics/Traps)をJSONで返す"""
    if 'mib_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['mib_file']
    lang = request.form.get('lang', 'ja')

    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if file:
        mib_path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(mib_path)

        json_path, mib_name = parse_mib_to_json(mib_path, OUTPUT_FOLDER)
        
        if json_path and os.path.exists(json_path):
            metrics_raw, traps_raw = extract_oid_info(json_path)
            
            # AI解説 (Metricsのみ対象とします。TrapsはMIBの説明文を使うため)
            symbols = [m['name'] for m in metrics_raw]
            ai_data = get_ai_descriptions(symbols, lang=lang)

            # Metricsデータの整形
            metrics_list = []
            for m in metrics_raw:
                ai_info = ai_data.get(m['name'], {})
                m['ai_desc'] = ai_info.get('desc', '')
                m['importance'] = ai_info.get('importance', '-')
                metrics_list.append(m)

            # Trapsデータの整形
            # descriptionがある場合はそれを使い、なければ空文字
            traps_list = []
            for t in traps_raw:
                # フロントエンドで編集しやすいように構造を整える
                t['user_description'] = t['description'] # 初期値としてMIBのDescriptionを入れる
                traps_list.append(t)

            return jsonify({
                "status": "success",
                "mib_name": mib_name,
                "metrics": metrics_list,
                "traps": traps_list
            })
        else:
            return jsonify({"error": "Failed to parse MIB file"}), 500

@app.route('/generate', methods=['POST'])
def generate():
    """Step 2: 選択されたデータを受け取り、YAML生成URLを返す"""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    mib_name = data.get('mib_name', 'Unknown_MIB')
    selected_metrics = data.get('metrics', [])
    selected_traps = data.get('traps', [])

    # YAML生成
    profile_data = generate_profile_yaml(mib_name, selected_metrics, selected_traps)
    yaml_content = yaml.dump(profile_data, sort_keys=False, default_flow_style=False, allow_unicode=True)

    output_filename = f"{mib_name}_profile.yaml"
    output_path = os.path.join(OUTPUT_FOLDER, output_filename)
    with open(output_path, 'w') as f:
        f.write(yaml_content)

    # ダウンロード用URLを作成 (API Gateway経由でアクセスするため、相対パスで返すか、S3署名付きURLがベストだが、
    # ここでは簡易的にFlaskからファイルを返すエンドポイントを指定)
    # フロントエンド側で /download/{filename} を叩く想定
    
    return jsonify({
        "status": "success",
        "download_url": f"/download/{output_filename}",
        "yaml_preview": yaml_content
    })

@app.route('/download/<filename>')
def download_file(filename):
    """生成されたファイルをダウンロードする"""
    return send_file(os.path.join(OUTPUT_FOLDER, filename), as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)