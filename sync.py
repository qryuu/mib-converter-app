import os
import json
import boto3
import requests
import base64
import time

dynamodb = boto3.resource('dynamodb')
secrets_client = boto3.client('secretsmanager')
table = dynamodb.Table(os.environ['CACHE_TABLE_NAME'])

def get_github_token():
    secret_id = os.environ.get('GITHUB_SECRET_ID')
    resp = secrets_client.get_secret_value(SecretId=secret_id)
    return json.loads(resp['SecretString']).get('GITHUB_TOKEN')

def lambda_handler(event, context):
    token = get_github_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    
    # 1. GitHubから全ファイルパスを取得
    tree_url = "https://api.github.com/repos/kentik/snmp-profiles/git/trees/main?recursive=1"
    resp = requests.get(tree_url, headers=headers, timeout=10)
    all_files = [i['path'] for i in resp.json().get('tree', []) 
                 if i['path'].startswith('profiles/kentik_snmp/') and i['path'].endswith('.yml')]

    # 2. DynamoDBをスキャンして、同期済みのパスを確認
    # (小規模なうちは全件スキャン、数千件超えるならインデックス設計を推奨)
    existing_items = table.scan(ProjectionExpression="#p", ExpressionAttributeNames={"#p": "path"})['Items']
    synced_paths = {item['path'] for item in existing_items}

    # 3. 未同期、または古いファイルを特定 (今回はシンプルに未同期分を優先)
    to_sync = [p for p in all_files if p not in synced_paths][:20] # 1回20件に制限
    
    print(f"Syncing {len(to_sync)} files to DynamoDB...")

    for path in to_sync:
        try:
            content_url = f"https://api.github.com/repos/kentik/snmp-profiles/contents/{path}"
            c_resp = requests.get(content_url, headers=headers, timeout=5)
            if c_resp.status_code == 200:
                raw_content = base64.b64decode(c_resp.json()['content']).decode('utf-8')
                table.put_item(Item={
                    'path': path,
                    'content': raw_content,
                    'last_updated': int(time.time())
                })
        except Exception as e:
            print(f"Failed to sync {path}: {e}")

    return {"status": "partial_sync_complete", "count": len(to_sync)}