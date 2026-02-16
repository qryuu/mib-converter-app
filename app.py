import re
import os
import json
import yaml
import time
import boto3
import traceback
import sys
import shutil
import requests
import base64

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from apig_wsgi import make_lambda_handler

# pysmi 関連
from pysmi.reader import FileReader, HttpReader
from pysmi.searcher import StubSearcher
from pysmi.parser import SmiStarParser
from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler

app = Flask(__name__)
CORS(app)

# Lambda環境設定
UPLOAD_FOLDER = '/tmp/uploads'
OUTPUT_FOLDER = '/tmp/outputs'

if os.path.exists(UPLOAD_FOLDER): shutil.rmtree(UPLOAD_FOLDER)
if os.path.exists(OUTPUT_FOLDER): shutil.rmtree(OUTPUT_FOLDER)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# AWS クライアント
dynamodb = boto3.resource('dynamodb')
cache_table = dynamodb.Table(os.environ.get('CACHE_TABLE_NAME', 'KentikProfileCache'))
bedrock_client = boto3.client('bedrock-runtime', region_name='ap-northeast-1')

# --- DynamoDB Helpers ---

def get_all_cached_paths():
    try:
        resp = cache_table.scan(ProjectionExpression="#p", ExpressionAttributeNames={"#p": "path"})
        return [item['path'] for item in resp.get('Items', [])]
    except Exception as e:
        print(f"DynamoDB Scan Error: {e}", file=sys.stderr)
        return []

def get_content_from_cache(path):
    try:
        resp = cache_table.get_item(Key={'path': path})
        return resp.get('Item', {}).get('content', '')
    except Exception as e:
        print(f"DynamoDB GetItem Error: {e}", file=sys.stderr)
        return ""

def select_reference_local(mib_name, file_list):
    default_ref = "profiles/kentik_snmp/cisco/cisco-asa.yml"
    if not file_list: return default_ref
    keywords = mib_name.lower().replace('-', ' ').replace('_', ' ').split()
    keywords = [k for k in keywords if k not in ['mib', 'common', 'types', 'v2']]
    best_match, max_score = None, 0
    for path in file_list:
        score = sum(1 for k in keywords if k in path.lower())
        if score > max_score:
            max_score, best_match = score, path
        elif score == max_score and score > 0:
            if best_match is None or len(path) < len(best_match):
                best_match = path
    return best_match if best_match else default_ref

# --- MIB Processing ---

class CustomJsonWriter:
    def __init__(self, path): self._path = path
    def setOptions(self, **kwargs): return self
    def saveData(self, mibName, data, **kwargs): return self._write_json(mibName, data)
    def put_data(self, mibName, data, **kwargs): return self._write_json(mibName, data)
    def _write_json(self, mibName, data):
        file_path = os.path.join(self._path, mibName + '.json')
        with open(file_path, 'w') as f:
            if isinstance(data, str): f.write(data)
            else: json.dump(data, f, indent=4)
        return mibName

def parse_mib_to_json(mib_path, output_dir):
    try:
        mib_dir, mib_filename = os.path.dirname(mib_path), os.path.basename(mib_path)
        mib_name = os.path.splitext(mib_filename)[0]
        compiler = MibCompiler(SmiStarParser(), JsonCodeGen(), CustomJsonWriter(output_dir))
        compiler.addSources(FileReader(mib_dir), HttpReader('https://mibs.pysnmp.com/asn1/'))
        compiler.compile(mib_name)
        json_path = os.path.join(output_dir, mib_name + '.json')
        if os.path.exists(json_path): return json_path, mib_name
        files = [f for f in os.listdir(output_dir) if f.endswith('.json')]
        return (os.path.join(output_dir, files[0]), os.path.splitext(files[0])[0]) if files else (None, None)
    except: return None, None

def extract_oid_info(json_path):
    try:
        with open(json_path, 'r') as f: data = json.load(f)
        metrics, traps = [], []
        for symbol, info in sorted(data.items()):
            if isinstance(info, dict) and 'oid' in info:
                item = {'name': symbol, 'oid': info['oid'], 'description': info.get('description', '')}
                if info.get('nodetype') in ['scalar', 'column']: metrics.append(item)
                elif info.get('nodetype') in ['notification', 'trap']: traps.append(item)
        return metrics, traps
    except: return [], []

def get_ai_descriptions(symbol_list, lang='ja'):
    if not symbol_list: return {}
    try:
        lang_str = "Japanese" if lang == 'ja' else "English"
        prompt = f"Explain these SNMP OIDs in {lang_str}. Return ONLY JSON: {{'name': {{'desc': '...', 'importance': 'High'}}}}\nSymbols: {', '.join(symbol_list[:30])}"
        body = json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 2000, "messages": [{"role": "user", "content": prompt}]})
        res = bedrock_client.invoke_model(modelId='anthropic.claude-3-haiku-20240307-v1:0', body=body)
        text = json.loads(res.get('body').read())['content'][0]['text']
        return json.loads(text[text.find('{'):text.rfind('}')+1])
    except: return {}

# --- YAML Generation ---

def generate_profile_yaml_with_ai(mib_name, metrics, traps, reference_content, yaml_lang='en'):
    target_lang = "Japanese" if yaml_lang == 'ja' else "English"
    
    prompt = f"""
    You are an expert in creating SNMP Profiles for Kentik KTranslate.
    Your task is to generate a YAML profile for MIB "{mib_name}".

    [INPUT DATA]
    Metrics Candidates: {json.dumps(metrics)}
    Traps: {json.dumps(traps)}

    [STRICT OUTPUT RULES]
    1. **Output Structure**: Use the valid Kentik YAML structure.
    2. **Provider**: Set 'provider' to "kentik-{mib_name.lower().replace('mib', '')}".
    3. **Table grouping (CRITICAL)**:
       - Group OIDs that share a common prefix into 'table' blocks.
       - The 'table' OID should be the common parent OID.
       - Inside a 'table', define 'symbols' and 'metric_tags'.
    4. **Symbols vs Tags**:
       - Put NUMERICAL values (Counters, Gauges, Percentages) under 'symbols'.
       - Put STRING values, NAMES, IDs, and INDEXES under 'metric_tags' -> 'column'.
    5. **Descriptions**: Write 'description' in {target_lang}.
    6. **Traps**: Include the traps section exactly as provided.
    7. **Reference**: Use the provided structure as a SYNTAX GUIDE only.
    
    [REFERENCE SYNTAX EXAMPLE]
    metrics:
      - MIB: {mib_name}
        table:
          OID: 1.3.6.1.4.1.XXXX.1.2
          name: someTable
        symbols:
          - OID: 1.3.6.1.4.1.XXXX.1.2.1.4
            name: cpuStatsIdle
            type: gauge
        metric_tags:
          - column:
              OID: 1.3.6.1.4.1.XXXX.1.2.1.1
              name: cpuIndex
              tag: true

    Output ONLY the YAML content within code blocks.
    """
    
    try:
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31", 
            "max_tokens": 4000, 
            "messages": [{"role": "user", "content": prompt}]
        })
        res = bedrock_client.invoke_model(modelId="anthropic.claude-3-haiku-20240307-v1:0", body=body)
        raw_text = json.loads(res['body'].read())['content'][0]['text']

        # ▼▼▼ 追加: 正規表現でYAMLブロックの中身だけを抽出 ▼▼▼
        match = re.search(r'```yaml(.*?)```', raw_text, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # yamlタグがない場合も考慮して汎用的なバッククォート検索
        match_generic = re.search(r'```(.*?)```', raw_text, re.DOTALL)
        if match_generic:
            return match_generic.group(1).strip()

        # マッチしない場合はそのまま返す（万が一Markdownなしで返ってきた場合用）
        return raw_text.strip()
        # ▲▲▲ 追加ここまで ▲▲▲

    except Exception as e: 
        return f"# Error: {str(e)}"

# --- API Endpoints ---

@app.route('/parse', methods=['POST'])
def parse():
    try:
        file = request.files['mib_file']
        mib_path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(mib_path)
        json_path, mib_name = parse_mib_to_json(mib_path, OUTPUT_FOLDER)
        if not json_path: return jsonify({"error": "Parse failed"}), 500
        metrics, traps = extract_oid_info(json_path)
        ai_data = get_ai_descriptions([m['name'] for m in metrics], lang=request.form.get('lang', 'ja'))
        for m in metrics:
            info = ai_data.get(m['name'], {})
            m.update({'ai_desc': info.get('desc', ''), 'importance': info.get('importance', '-')})
        return jsonify({"status": "success", "mib_name": mib_name, "metrics": metrics, "traps": traps})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.json
        all_paths = get_all_cached_paths()
        ref_path = select_reference_local(data.get('mib_name', ''), all_paths)
        ref_content = get_content_from_cache(ref_path)
        yaml_content = generate_profile_yaml_with_ai(data.get('mib_name'), data['metrics'], data['traps'], ref_content, data.get('yaml_lang', 'en'))
        output_filename = f"{data.get('mib_name')}_profile.yaml"
        with open(os.path.join(OUTPUT_FOLDER, output_filename), 'w') as f: f.write(yaml_content)
        return jsonify({"status": "success", "yaml_preview": yaml_content, "download_url": f"/download/{output_filename}", "reference_used": ref_path})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/download/<filename>')
def download_file(filename): return send_file(os.path.join(OUTPUT_FOLDER, filename), as_attachment=True)

wsgi_handler = make_lambda_handler(app)
def lambda_handler(event, context): return wsgi_handler(event, context)