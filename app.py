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
from pysmi.parser import SmiStarParser
from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler

app = Flask(__name__)
CORS(app)

# Lambda環境設定 (一時作業領域)
UPLOAD_FOLDER = '/tmp/uploads'
OUTPUT_FOLDER = '/tmp/outputs'

# 起動ごとにディレクトリをリセット
if os.path.exists(UPLOAD_FOLDER): shutil.rmtree(UPLOAD_FOLDER)
if os.path.exists(OUTPUT_FOLDER): shutil.rmtree(OUTPUT_FOLDER)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# AWS クライアント設定
dynamodb = boto3.resource('dynamodb')
cache_table = dynamodb.Table(os.environ.get('CACHE_TABLE_NAME', 'KentikProfileCache'))
bedrock_client = boto3.client('bedrock-runtime', region_name='ap-northeast-1')

# ---------------------------------------------------------
# ヘルパー関数: DynamoDB からのお手本取得
# ---------------------------------------------------------

def get_all_cached_paths():
    """DynamoDBからキャッシュ済みのパス一覧を高速に取得する"""
    try:
        # path属性のみを取得してメモリ負荷を軽減
        resp = cache_table.scan(ProjectionExpression="#p", ExpressionAttributeNames={"#p": "path"})
        return [item['path'] for item in resp.get('Items', [])]
    except Exception as e:
        print(f"DynamoDB Scan Error: {e}", file=sys.stderr)
        return []

def get_content_from_cache(path):
    """DynamoDBから指定されたパスのYAML内容を取得する"""
    try:
        resp = cache_table.get_item(Key={'path': path})
        return resp.get('Item', {}).get('content', '')
    except Exception as e:
        print(f"DynamoDB GetItem Error: {e}", file=sys.stderr)
        return ""

def select_reference_local(mib_name, file_list):
    """MIB名からキーワード一致で最適なお手本パスを判定する(AIを使わず高速化)"""
    default_ref = "profiles/kentik_snmp/cisco/cisco-asa.yml"
    if not file_list:
        return default_ref

    keywords = mib_name.lower().replace('-', ' ').replace('_', ' ').split()
    keywords = [k for k in keywords if k not in ['mib', 'common', 'types', 'v2']]

    best_match = None
    max_score = 0

    for path in file_list:
        score = 0
        path_lower = path.lower()
        for k in keywords:
            if k in path_lower:
                score += 1
        
        if score > max_score:
            max_score = score
            best_match = path
        elif score == max_score and score > 0:
            if len(path) < len(best_match):
                best_match = path
    
    return best_match if best_match else default_ref

# ---------------------------------------------------------
# MIB 解析ロジック (既存機能)
# ---------------------------------------------------------

class CustomJsonWriter:
    def __init__(self, path):
        self._path = path
        self._suffix = '.json'
    def setOptions(self, **kwargs): return self
    def saveData(self, mibName, data, **kwargs): return self._write_json(mibName, data)
    def put_data(self, mibName, data, **kwargs): return self._write_json(mibName, data)
    def _write_json(self, mibName, data):
        file_path = os.path.join(self._path, mibName + self._suffix)
        with open(file_path, 'w') as f:
            if isinstance(data, str): f.write(data)
            else: json.dump(data, f, indent=4)
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
        mibCompiler.addSources(file_reader, web_reader)
        mibCompiler.compile(assumed_mib_name)

        expected_json = os.path.join(output_dir, assumed_mib_name + '.json')
        if os.path.exists(expected_json):
            return expected_json, assumed_mib_name
        
        json_files = [f for f in os.listdir(output_dir) if f.endswith('.json')]
        if json_files:
            return os.path.join(output_dir, json_files[0]), os.path.splitext(json_files[0])[0]
        return None, None
    except Exception as e:
        print(f"MIB Parse Error: {e}", file=sys.stderr)
        return None, None

def extract_oid_info(json_path):
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
        metrics, traps = [], []
        for symbol, info in sorted(data.items()):
            if isinstance(info, dict) and 'oid' in info:
                nodetype = info.get('nodetype', '')
                if nodetype in ['scalar', 'column']:
                    metrics.append({'name': symbol, 'oid': info['oid'], 'description': info.get('description', '')})
                elif nodetype in ['notification', 'trap']:
                    traps.append({'name': symbol, 'oid': info['oid'], 'description': info.get('description', '')})
        return metrics, traps
    except Exception as e:
        return [], []

def get_ai_descriptions(symbol_list, lang='ja'):
    if not symbol_list: return {}
    try:
        target_symbols = symbol_list[:30]
        lang_instruction = "Japanese" if lang == 'ja' else "English"
        prompt = f"Explain the following SNMP OID symbols in {lang_instruction}. Return ONLY valid JSON: {{ 'name': {{ 'desc': '...', 'importance': 'High' }} }}\nSymbols: {chr(10).join(target_symbols)}"
        
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}]
        })
        response = bedrock_client.invoke_model(modelId='anthropic.claude-3-haiku-20240307-v1:0', body=body)
        ai_res = json.loads(response.get('body').read())['content'][0]['text']
        return json.loads(ai_res[ai_res.find('{'):ai_res.rfind('}')+1])
    except: return {}

# ---------------------------------------------------------
# YAML 生成ロジック (AI連携)
# ---------------------------------------------------------

def generate_profile_yaml_with_ai(mib_name, metrics, traps, reference_content):
    """お手本をプロンプトに含めて高品質なYAMLを生成する"""
    prompt = f"""
    Create a valid Kentik SNMP Profile (YAML) for MIB "{mib_name}".
    [REFERENCE STYLE]
    {reference_content[:3000]}
    [REQUIREMENTS]
    Metrics: {json.dumps(metrics)}
    Traps: {json.dumps(traps)}
    Output ONLY valid YAML. No markdown.
    """
    try:
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31", "max_tokens": 4000,
            "messages": [{"role": "user", "content": prompt}]
        })
        response = bedrock_client.invoke_model(modelId="anthropic.claude-3-haiku-20240307-v1:0", body=body)
        return json.loads(response['body'].read())['content'][0]['text']
    except Exception as e:
        return f"# Error: {str(e)}"

# ---------------------------------------------------------
# API エンドポイント
# ---------------------------------------------------------

@app.route('/health', methods=['GET'])
def health(): return jsonify({"status": "ok"})

@app.route('/parse', methods=['POST'])
def parse():
    try:
        if 'mib_file' not in request.files: return jsonify({"error": "No file"}), 400
        file = request.files['mib_file']
        mib_path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(mib_path)

        json_path, mib_name = parse_mib_to_json(mib_path, OUTPUT_FOLDER)
        if not json_path: return jsonify({"error": "Parse failed"}), 500

        metrics_raw, traps_raw = extract_oid_info(json_path)
        ai_data = get_ai_descriptions([m['name'] for m in metrics_raw], lang=request.form.get('lang', 'ja'))
        
        for m in metrics_raw:
            info = ai_data.get(m['name'], {})
            m.update({'ai_desc': info.get('desc', ''), 'importance': info.get('importance', '-')})
            
        return jsonify({"status": "success", "mib_name": mib_name, "metrics": metrics_raw, "traps": traps_raw})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.json
        mib_name = data.get('mib_name', 'Unknown_MIB')
        
        # 1. キャッシュからお手本を検索 (GitHubへの外部通信なし)
        all_paths = get_all_cached_paths()
        ref_path = select_reference_local(mib_name, all_paths)
        ref_content = get_content_from_cache(ref_path)
        
        # 2. 生成実行
        yaml_content = generate_profile_yaml_with_ai(mib_name, data['metrics'], data['traps'], ref_content)

        output_filename = f"{mib_name}_profile.yaml"
        with open(os.path.join(OUTPUT_FOLDER, output_filename), 'w') as f:
            f.write(yaml_content)

        return jsonify({
            "status": "success",
            "yaml_preview": yaml_content,
            "download_url": f"/download/{output_filename}",
            "reference_used": ref_path
        })
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(OUTPUT_FOLDER, filename), as_attachment=True)

# ---------------------------------------------------------
# Lambda Handler
# ---------------------------------------------------------
wsgi_handler = make_lambda_handler(app)
def lambda_handler(event, context):
    return wsgi_handler(event, context)