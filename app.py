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

# 毎回クリーンにする
if os.path.exists(UPLOAD_FOLDER): shutil.rmtree(UPLOAD_FOLDER)
if os.path.exists(OUTPUT_FOLDER): shutil.rmtree(OUTPUT_FOLDER)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# AWS Clients
secrets_client = boto3.client('secretsmanager')
bedrock_client = boto3.client('bedrock-runtime', region_name='ap-northeast-1')

# --- GitHub Integration Helper ---
CACHED_GITHUB_TOKEN = None

def get_github_token():
    """Secrets Managerからトークンを取得してキャッシュ"""
    global CACHED_GITHUB_TOKEN
    if CACHED_GITHUB_TOKEN:
        return CACHED_GITHUB_TOKEN
    
    secret_id = os.environ.get('GITHUB_SECRET_ID', 'prod/github/token')
    try:
        resp = secrets_client.get_secret_value(SecretId=secret_id)
        if 'SecretString' in resp:
            secret = json.loads(resp['SecretString'])
            token = secret.get('GITHUB_TOKEN')
            CACHED_GITHUB_TOKEN = token
            return token
    except Exception as e:
        print(f"Secret Error: {e}", file=sys.stderr)
    return None

def get_kentik_file_list():
    """GitHub上のKentikプロファイル一覧(.yml)を取得"""
    token = get_github_token()
    if not token:
        print("GitHub Token not available.", file=sys.stderr)
        return []

    url = "https://api.github.com/repos/kentik/snmp-profiles/git/trees/main?recursive=1"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            tree = resp.json().get('tree', [])
            file_list = [
                item['path'] for item in tree 
                if item['path'].startswith('profiles/kentik_snmp/') and item['path'].endswith('.yml')
            ]
            return file_list
        else:
            print(f"GitHub API Error: {resp.status_code} {resp.text}", file=sys.stderr)
    except Exception as e:
        print(f"GitHub Request Exception: {e}", file=sys.stderr)
    return []

def get_file_content(path):
    """指定パスのファイル内容を取得してデコード"""
    token = get_github_token()
    url = f"https://api.github.com/repos/kentik/snmp-profiles/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            content = base64.b64decode(data['content']).decode('utf-8')
            return content
    except Exception as e:
        print(f"Content Fetch Error: {e}", file=sys.stderr)
    return ""

def select_reference_with_ai(mib_name, file_list):
    """MIB名に最適なファイルをAIに選ばせる"""
    keywords = mib_name.lower().replace('-', ' ').split()
    candidates = [f for f in file_list if any(k in f.lower() for k in keywords)]
    
    if len(candidates) < 5:
        candidates = file_list[:50]

    prompt = f"""
    You are an assistant finding a reference configuration file.
    User's MIB Name: "{mib_name}"
    
    Candidate Files:
    {json.dumps(candidates)}
    
    Select the ONE most relevant file path from the list.
    If exact match not found, return "profiles/kentik_snmp/cisco/cisco-asa.yml".
    Return ONLY the file path string.
    """

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 200,
        "messages": [{"role": "user", "content": prompt}]
    })

    try:
        response = bedrock_client.invoke_model(
            modelId="anthropic.claude-3-haiku-20240307-v1:0",
            body=body
        )
        result = json.loads(response['body'].read())
        selected = result['content'][0]['text'].strip()
        if any(selected in f for f in file_list):
            return selected
    except Exception as e:
        print(f"AI Selection Error: {e}", file=sys.stderr)
    
    return "profiles/kentik_snmp/cisco/cisco-asa.yml"

# --- Existing Logic (MIB Parsing) ---

class CustomJsonWriter:
    def __init__(self, path):
        self._path = path
        self._suffix = '.json'
    
    def setOptions(self, **kwargs):
        if 'suffix' in kwargs:
            self._suffix = kwargs['suffix']
        return self

    def saveData(self, mibName, data, **kwargs):
        return self._write_json(mibName, data)

    def put_data(self, mibName, data, **kwargs):
        return self._write_json(mibName, data)

    def _write_json(self, mibName, data):
        file_path = os.path.join(self._path, mibName + self._suffix)
        try:
            with open(file_path, 'w') as f:
                if isinstance(data, str):
                    f.write(data)
                else:
                    json.dump(data, f, indent=4)
        except Exception as e:
            print(f"DEBUG: Failed to save JSON {file_path}: {e}", file=sys.stderr)
            raise e
        return mibName

def parse_mib_to_json(mib_path, output_dir):
    try:
        mib_dir = os.path.dirname(mib_path)
        mib_filename = os.path.basename(mib_path)
        assumed_mib_name = os.path.splitext(mib_filename)[0]

        mibParser = SmiStarParser()
        mibWriter = CustomJsonWriter(output_dir)
        mibCompiler = MibCompiler(mibParser, JsonCodeGen(), mibWriter)
        
        web_reader = HttpReader('https://mibs.pysnmp.com/asn1/')
        file_reader = FileReader(mib_dir)

        if hasattr(mibCompiler, 'add_sources'):
            mibCompiler.add_sources(file_reader, web_reader)
        else:
            mibCompiler.addSources(file_reader, web_reader)

        mibCompiler.compile(assumed_mib_name)

        expected_json = os.path.join(output_dir, assumed_mib_name + '.json')
        if os.path.exists(expected_json):
            return expected_json, assumed_mib_name
        
        json_files = [f for f in os.listdir(output_dir) if f.endswith('.json')]
        target_json = None
        standard_mibs = ['SNMPv2-SMI', 'RFC1213-MIB', 'SNMPv2-TC', 'RFC-1212', 'RFC-1215', 'RFC1155-SMI', 'SNMPv2-CONF']
        
        for f in json_files:
            base_name = os.path.splitext(f)[0]
            if base_name not in standard_mibs:
                target_json = f
                break
        
        if target_json:
            return os.path.join(output_dir, target_json), os.path.splitext(target_json)[0]
        
        if json_files:
            return os.path.join(output_dir, json_files[0]), os.path.splitext(json_files[0])[0]

        return None, None

    except Exception as e:
        print(f"MIB Parse Error: {e}", file=sys.stderr)
        traceback.print_exc()
        return None, None

def extract_oid_info(json_path):
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
        if isinstance(data, str):
            data = json.loads(data)
            
        metrics = []
        traps = []

        if not isinstance(data, dict):
            return [], []

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
    except Exception as e:
        print(f"Extract OID Error: {e}", file=sys.stderr)
        return [], []

def get_ai_descriptions(symbol_list, lang='ja'):
    if not symbol_list: return {}
    try:
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

        response = bedrock_client.invoke_model(
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

def generate_profile_yaml_with_ai(mib_name, metrics, traps, reference_content):
    """
    お手本を参考に、Bedrockを使ってYAMLを生成する
    """
    prompt = f"""
    You are an expert in Kentik SNMP Profiles.
    Create a valid YAML profile for the MIB "{mib_name}".
    
    [REFERENCE STYLE - FOLLOW THIS STRUCTURE]
    {reference_content[:4000]} 
    (NOTE: Do not copy the OIDs from the reference. Mimic the structure: 'table' grouping logic, 'symbols' vs 'metric_tags'.)

    [USER REQUIREMENTS]
    Metrics: {json.dumps(metrics, indent=2)}
    Traps: {json.dumps(traps, indent=2)}
    
    [OUTPUT INSTRUCTIONS]
    1. Output ONLY valid YAML. No markdown blocks.
    2. Group metrics sharing the same OID prefix into 'table' blocks.
    3. Use 'symbols' for numeric values, 'metric_tags' for string values.
    """

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}]
    })

    try:
        response = bedrock_client.invoke_model(
            modelId="anthropic.claude-3-haiku-20240307-v1:0",
            body=body
        )
        return json.loads(response['body'].read())['content'][0]['text']
    except Exception as e:
        print(f"YAML Gen Error: {e}", file=sys.stderr)
        return f"# Error generating YAML: {str(e)}"

# --- API Endpoints ---

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
                
                metrics_list = []
                if metrics_raw:
                    symbols = [m['name'] for m in metrics_raw]
                    ai_data = get_ai_descriptions(symbols, lang=lang)
                    for m in metrics_raw:
                        ai_info = ai_data.get(m['name'], {})
                        m['ai_desc'] = ai_info.get('desc', '')
                        m['importance'] = ai_info.get('importance', '-')
                        metrics_list.append(m)
                
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
                return jsonify({"error": "Failed to parse MIB file."}), 500

    except Exception as e:
        print(f"Exception in /parse: {e}", file=sys.stderr)
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400

        mib_name = data.get('mib_name', 'Unknown_MIB')
        metrics = data.get('metrics', [])
        traps = data.get('traps', [])

        # 1. GitHubからファイル一覧を取得
        all_files = get_kentik_file_list()
        
        # 2. AIにお手本を選ばせる
        ref_path = "None"
        ref_content = ""
        
        if all_files:
            ref_path = select_reference_with_ai(mib_name, all_files)
            print(f"Selected Reference: {ref_path}", file=sys.stderr)
            # 3. お手本を取得
            ref_content = get_file_content(ref_path)
        
        # 4. 生成実行 (お手本ありAI生成)
        yaml_content = generate_profile_yaml_with_ai(mib_name, metrics, traps, ref_content)

        # ファイル保存
        output_filename = f"{mib_name}_profile.yaml"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        with open(output_path, 'w') as f:
            f.write(yaml_content)

        return jsonify({
            "status": "success",
            "download_url": f"/download/{output_filename}",
            "yaml_preview": yaml_content,
            "reference_used": ref_path
        })

    except Exception as e:
        print(f"Exception in /generate: {e}", file=sys.stderr)
        return jsonify({"error": str(e)}), 500

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(OUTPUT_FOLDER, filename), as_attachment=True)

wsgi_handler = make_lambda_handler(app)

def lambda_handler(event, context):
    return wsgi_handler(event, context)