import os
import json
import yaml
import time
import boto3
import traceback
import sys
import shutil
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from apig_wsgi import make_lambda_handler

# pysmi 関連
from pysmi.reader import FileReader, HttpReader
from pysmi.searcher import StubSearcher
from pysmi.writer import FileWriter
from pysmi.parser import SmiStarParser
from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler

app = Flask(__name__)
CORS(app)

# Lambda環境設定
UPLOAD_FOLDER = '/tmp/uploads'
OUTPUT_FOLDER = '/tmp/outputs'

# 毎回クリーンにする
if os.path.exists(UPLOAD_FOLDER): shutil.rmtree(UPLOAD_FOLDER)
if os.path.exists(OUTPUT_FOLDER): shutil.rmtree(OUTPUT_FOLDER)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ---------------------------------------------------------
# ロジック関数
# ---------------------------------------------------------

def parse_mib_to_json(mib_path, output_dir):
    try:
        mib_dir = os.path.dirname(mib_path)
        mib_filename = os.path.basename(mib_path)
        assumed_mib_name = os.path.splitext(mib_filename)[0]

        print(f"DEBUG: Starting compilation for {mib_filename}", file=sys.stderr)

        # パーサーの設定
        mibParser = SmiStarParser()
        
        # ▼▼▼ 修正箇所: 拡張子をここで指定する (setOptionsは使わない) ▼▼▼
        mibWriter = FileWriter(output_dir, suffix='.json')
        
        mibCompiler = MibCompiler(mibParser, JsonCodeGen(), mibWriter)
        
        # 依存関係解決のためにWebソースを追加
        web_reader = HttpReader('https://mibs.pysnmp.com/asn1/')
        file_reader = FileReader(mib_dir)

        if hasattr(mibCompiler, 'add_sources'):
            mibCompiler.add_sources(file_reader, web_reader)
        else:
            mibCompiler.addSources(file_reader, web_reader)

        # コンパイル実行
        mibCompiler.compile(assumed_mib_name)

        # ▼▼▼ 生成されたファイルを賢く探す ▼▼▼
        # 1. ファイル名と同じ名前のJSONがあるか？
        expected_json = os.path.join(output_dir, assumed_mib_name + '.json')
        if os.path.exists(expected_json):
            return expected_json, assumed_mib_name
        
        # 2. なければ、フォルダ内にある最新のJSONを探す
        json_files = [f for f in os.listdir(output_dir) if f.endswith('.json')]
        
        target_json = None
        standard_mibs = ['SNMPv2-SMI', 'RFC1213-MIB', 'SNMPv2-TC', 'RFC-1212', 'RFC-1215', 'RFC1155-SMI', 'SNMPv2-CONF']
        
        for f in json_files:
            base_name = os.path.splitext(f)[0]
            if base_name not in standard_mibs:
                target_json = f
                break
        
        if target_json:
            print(f"DEBUG: Found target JSON file: {target_json}", file=sys.stderr)
            return os.path.join(output_dir, target_json), os.path.splitext(target_json)[0]
        
        if json_files:
            print(f"DEBUG: Fallback to first JSON file: {json_files[0]}", file=sys.stderr)
            return os.path.join(output_dir, json_files[0]), os.path.splitext(json_files[0])[0]

        print(f"Error: No JSON file created. Files in output: {os.listdir(output_dir)}", file=sys.stderr)
        return None, None

    except Exception as e:
        print(f"MIB Parse Error: {e}", file=sys.stderr)
        traceback.print_exc()
        return None, None

def extract_oid_info(json_path):
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    metrics = []
    traps = []

    for symbol, info in sorted(data.items()):
        if isinstance(info, dict) and 'oid' in info:
            nodetype = info.get('nodetype', '')
            description = info.get('description', '')

            if nodetype in ['scalar', 'column']:
                metrics.append({
                    'name': symbol,
                    'oid': info['oid'],
                    'nodetype': nodetype,
                    'description': description
                })
            elif nodetype in ['notification', 'trap']:
                traps.append({
                    'name': symbol,
                    'oid': info['oid'],
                    'nodetype': nodetype,
                    'description': description
                })

    return metrics, traps

def get_ai_descriptions(symbol_list, lang='ja'):
    if not symbol_list: return {}
    try:
        bedrock = boto3.client(service_name='bedrock-runtime', region_name='ap-northeast-1')
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
        print(f"AI Error: {e}", file=sys.stderr)
        return {}

def generate_profile_yaml(mib_name, metrics_data, traps_data):
    profile = {
        'extends': [],
        'sysobjectid': '1.3.6.1.4.1.CHANGE_THIS',
        'metrics': [],
        'traps': []
    }
    for m in metrics_data:
        profile['metrics'].append({
            'MIB': mib_name,
            'symbol': {'OID': m['oid'], 'name': m['name']}
        })
    for t in traps_data:
        profile['traps'].append({
            'MIB': mib_name,
            'symbol': {'OID': t['oid'], 'name': t['name']},
            'description': t.get('description', '')
        })
    return profile

# ---------------------------------------------------------
# API エンドポイント
# ---------------------------------------------------------

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

@app.route('/parse', methods=['POST'])
def parse():
    try:
        print("Received /parse request", file=sys.stderr)
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
                
                # MetricsがあればAI解説を試みる
                metrics_list = []
                if metrics_raw:
                    symbols = [m['name'] for m in metrics_raw]
                    ai_data = get_ai_descriptions(symbols, lang=lang)
                    for m in metrics_raw:
                        ai_info = ai_data.get(m['name'], {})
                        m['ai_desc'] = ai_info.get('desc', '')
                        m['importance'] = ai_info.get('importance', '-')
                        metrics_list.append(m)
                
                # Traps
                traps_list = []
                for t in traps_raw:
                    t['user_description'] = t['description']
                    traps_list.append(t)

                return jsonify({
                    "status": "success",
                    "mib_name": mib_name,
                    "metrics": metrics_list,
                    "traps": traps_list
                })
            else:
                return jsonify({"error": "Failed to parse MIB file. Check CloudWatch logs for details."}), 500

    except Exception as e:
        print(f"Exception in /parse: {e}", file=sys.stderr)
        traceback.print_exc()
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400

        mib_name = data.get('mib_name', 'Unknown_MIB')
        selected_metrics = data.get('metrics', [])
        selected_traps = data.get('traps', [])

        profile_data = generate_profile_yaml(mib_name, selected_metrics, selected_traps)
        yaml_content = yaml.dump(profile_data, sort_keys=False, default_flow_style=False, allow_unicode=True)

        output_filename = f"{mib_name}_profile.yaml"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        with open(output_path, 'w') as f:
            f.write(yaml_content)

        return jsonify({
            "status": "success",
            "download_url": f"/download/{output_filename}",
            "yaml_preview": yaml_content
        })
    except Exception as e:
        print(f"Exception in /generate: {e}", file=sys.stderr)
        return jsonify({"error": str(e)}), 500

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(OUTPUT_FOLDER, filename), as_attachment=True)

# ---------------------------------------------------------
# Lambda Handler
# ---------------------------------------------------------
lambda_handler = make_lambda_handler(app)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)