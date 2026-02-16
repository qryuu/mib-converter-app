# MIB Converter App

<p align="center">
  <img src="https://img.shields.io/badge/Frontend-React%20%7C%20Vite-61DAFB" alt="Frontend">
  <img src="https://img.shields.io/badge/Backend-Python%20%7C%20Flask-blue" alt="Backend">
  <img src="https://img.shields.io/badge/Infrastructure-AWS%20SAM%20%7C%20Lambda-orange" alt="Infrastructure">
  <img src="https://img.shields.io/badge/Database-DynamoDB-4053D6" alt="Database">
  <img src="https://img.shields.io/badge/AI-AWS%20Bedrock-purple" alt="AI">
  <img src="https://img.shields.io/badge/Monitoring-New%20Relic-brightgreen" alt="Monitoring">
</p>

## 概要 (Description)

`mib-converter-app` is a modern web application that allows you to easily upload SNMP MIB files and generate high-quality monitoring profile YAMLs compatible with **New Relic KTranslate**.

It integrates with **AWS Bedrock (Anthropic Claude 3 Haiku)** to automatically analyze OIDs. The system now features a **React-based frontend** for interactive editing and a **DynamoDB-backed caching layer** for high-performance reference lookups.

<details>
<summary>日本語の説明</summary>

`mib-converter-app` は、SNMP MIBファイルをアップロードし、**New Relic KTranslate** で利用可能な高品質な監視プロファイルYAMLを簡単に生成するためのWebアプリケーションです。

**AWS Bedrock (Claude 3 Haiku)** と連携し、OIDの自動解析を行います。**Reactベースのフロントエンド**によるインタラクティブな編集機能や、**DynamoDBによるキャッシュ層**を備え、高速かつ柔軟なプロファイル作成を実現します。

</details>



## ✨ 主な機能 (Key Features)

* **Interactive React UI**: A modern, responsive UI built with React and Vite. Supports real-time editing of Trap messages and toggle switches for configuration.
    * **インタラクティブなReact UI**: ReactとViteで構築されたモダンなUI。Trapメッセージのリアルタイム編集や、設定のトグル切り替えが可能です。
* **Intelligent MIB Parsing**: Utilizes `pysmi` to parse MIB files and extract Metrics (Scalar/Table) and Traps automatically.
    * **インテリジェントなMIB解析**: `pysmi` を利用してMIBを解析し、メトリクス（Scalar/Table）とTrapを自動抽出します。
* **AI-Powered Descriptions & Structure**: AWS Bedrock generates descriptions and enforces strict Kentik-compliant YAML structures (separating Symbols and Metric Tags).
    * **AIによる解説と構造化**: AWS Bedrockが解説文を生成するだけでなく、Kentik仕様に準拠した厳密なYAML構造（SymbolsとMetric Tagsの分離）を自動で構築します。
* **Customizable Trap Messages**: Users can edit Trap descriptions manually in the UI. If left empty, AI automatically generates an English description based on the OID name.
    * **Trapメッセージの編集**: UI上でTrapの説明文を手動編集できます。空欄の場合は、OID名に基づいてAIが自動的に英語の説明を生成します。
* **Multi-Language YAML Generation**: A toggle switch allows users to choose whether the generated YAML descriptions should be in **Japanese** or **English**.
    * **多言語YAML生成**: 生成されるYAML内の説明文を「日本語」にするか「英語」にするか、トグルスイッチで簡単に選択できます。
* **High-Performance Caching**: Background Lambda functions sync reference profiles from GitHub to **DynamoDB**, ensuring fast generation without API rate limits.
    * **高性能キャッシュ**: バックグラウンドのLambda関数がGitHub上の参照プロファイルを**DynamoDB**に同期。APIレート制限を回避し、高速な生成を実現します。
* **Full Observability**: Integrated with New Relic for APM, Logs, and AI Monitoring.
    * **完全な可観測性**: New Relicと統合され、APM、ログ、AIのトークン使用量などを監視できます。

## 🛠️ 技術スタック (Tech Stack)

* **Frontend**: React 19, Vite, Axios
* **Backend**: Python 3.12, Flask, pysmi, Boto3
* **Infrastructure**: AWS SAM, AWS Lambda, Amazon API Gateway, **Amazon DynamoDB**, **Amazon EventBridge (Scheduler)**
* **AI**: Amazon Bedrock (Anthropic Claude 3 Haiku)
* **Monitoring**: New Relic (APM, Logs, AI Monitoring)

## 🚀 デプロイ手順 (Deployment)

This application is deployed using AWS SAM.

### 前提条件 (Prerequisites)

1.  AWS CLI & SAM CLI installed.
2.  Python 3.12 & Node.js installed.
3.  **New Relic Account**:
    * `NewRelicAccountId`
    * `NewRelicLicenseKey` (Ingest-License key)
4.  **AWS Secrets Manager** (For Background Sync):
    * Create a secret named `prod/github/token` containing your GitHub Token key: `{"GITHUB_TOKEN": "your_token_here"}`.
    * *This is required for the `SyncFunction` to fetch reference profiles.*

### デプロイコマンド (Deployment Commands)

1.  **Build the application.**
    ```bash
    sam build
    ```

2.  **Deploy the application.**
    ```bash
    sam deploy --guided
    ```

    **Parameters:**
    * `NewRelicAccountId`: Your New Relic Account ID.
    * `NewRelicLicenseKey`: Your New Relic License Key.

3.  **Frontend Deployment (Amplify/S3):**
    * Navigate to the frontend directory.
    * Run `npm install` and `npm run build`.
    * Deploy the `dist` folder to your hosting service (AWS Amplify, S3, etc.).

## 🔄 バックグラウンド同期について (Background Sync)

This app uses a `SyncFunction` triggered every hour by EventBridge. It fetches official Kentik SNMP profiles from GitHub and caches them in DynamoDB.
* **Effect**: Ensures the AI has access to the latest "Reference" styles without hitting GitHub API limits during user requests.

本アプリは EventBridge により1時間ごとに起動する `SyncFunction` を備えています。公式の Kentik SNMP プロファイルを GitHub から取得し、DynamoDB にキャッシュします。
* **効果**: ユーザーリクエスト時に GitHub API 制限に引っかかることなく、AI が最新の「お手本」を参照できるようになります。

## 🤝 コントリビューション (Contributing)

Contributions are welcome! Please submit issues or pull requests.

## 📜 ライセンス (License)

This project is licensed under the MIT License.