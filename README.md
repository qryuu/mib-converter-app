# MIB Converter App

<p align="center">
  <img src="https://img.shields.io/badge/Backend-Python%20%7C%20Flask-blue" alt="Backend">
  <img src="https://img.shields.io/badge/Infrastructure-AWS%20SAM%20%7C%20Lambda-orange" alt="Infrastructure">
  <img src="https://img.shields.io/badge/AI-AWS%20Bedrock-purple" alt="AI">
  <img src="https://img.shields.io/badge/Monitoring-New%20Relic-brightgreen" alt="Monitoring">
</p>

## 概要 (Description)

`mib-converter-app` is a web application that allows you to easily upload SNMP MIB files and generate monitoring profile YAML compatible with New Relic KTraslate.

It integrates with AWS Bedrock (Anthropic Claude 3 Haiku) to automatically suggest descriptions and monitoring importance for each OID (Object Identifier) in the MIB. This significantly streamlines the complex, manual process of creating monitoring profiles.

<details>
<summary>日本語の説明</summary>

`mib-converter-app` は、SNMP MIBファイルをアップロードし、New Relic KTraslateで利用可能な監視プロファイルYAMLを簡単に生成するためのWebアプリケーションです。

AWS Bedrock (Claude 3 Haiku) と連携し、MIBに含まれる各OID（Object Identifier）の解説や監視の重要度を自動で提案する機能を備えています。これにより、これまで手作業で行っていた複雑なプロファイル作成作業を大幅に効率化します。

</details>

## ✨ 主な機能 (Key Features)

*   **MIB File Upload and Parsing**: Utilizes `pysmi` to parse MIB files and convert them to JSON format.
    *   **MIBファイルのアップロードと解析**: `pysmi` を利用してMIBファイルを解析し、JSON形式に変換します。
*   **Automatic OID Extraction**: Automatically extracts and lists metrics (Scalar, Column) and trap (Notification) information from the parsed results.
    *   **OIDの自動抽出**: 解析結果からメトリクス（Scalar, Column）とトラップ（Notification）の情報を自動で抽出・一覧表示します。
*   **AI-Powered Descriptions**: Leverages AWS Bedrock to automatically generate overviews and monitoring importance for the extracted OIDs in either Japanese or English.
    *   **AIによる解説生成**: AWS Bedrockを利用して、抽出したOIDの概要や監視における重要度を日本語または英語で自動生成します。
*   **Profile YAML Generation**: Dynamically generates a New Relic SNMP profile (in YAML format) based on user-selected metrics and traps.
    *   **プロファイルYAMLの生成**: ユーザーが選択したメトリクスとトラップに基づいて、New RelicのSNMPプロファイル（YAML形式）を動的に生成します。
*   **Preview and Download**: Allows you to preview the content of the generated YAML on-screen and download it directly.
    *   **プレビューとダウンロード**: 生成されたYAMLの内容を画面で確認し、そのままダウンロードできます。
*   **Serverless Architecture**: Built on AWS Lambda and API Gateway, making it scalable and easy to maintain.
    *   **サーバーレスアーキテクチャ**: AWS LambdaとAPI Gatewayで構築されており、スケーラブルかつメンテナンス性に優れています。
*   **In-depth Monitoring**: Deeply integrated with New Relic for detailed visibility into application performance, logs, and AI usage.
    *   **詳細な監視**: New Relicと深く統合されており、アプリケーションのパフォーマンス、ログ、AIの利用状況まで詳細に可視化できます。

## 🛠️ 技術スタック (Tech Stack)

*   **Backend**: Python 3.12, Flask, pysmi, Boto3
*   **Frontend**: JavaScript, Axios (*Note: This repository contains the backend code only*)
*   **Infrastructure**: AWS SAM, AWS Lambda, Amazon API Gateway, Amazon S3
*   **AI**: Amazon Bedrock (Anthropic Claude 3 Haiku)
*   **Monitoring**: New Relic (APM, Logs, AI Monitoring)

## 🚀 デプロイ手順 (Deployment)

This application can be easily deployed using the AWS SAM (Serverless Application Model).

### 前提条件 (Prerequisites)

*   AWS CLI installed and configured.
*   AWS SAM CLI installed.
*   Python 3.12 installed.
*   A valid New Relic account and the following information:
    *   `NewRelicAccountId`
    *   `NewRelicLicenseKey` (Ingest-License key)

### デプロイコマンド (Deployment Commands)

1.  **Build the application.**
    This command installs dependencies and creates a deployment package.
    
    ```bash
    sam build
    ```

2.  **Deploy the application.**
    The `--guided` option allows you to configure the stack name, region, and parameters interactively.

    ```bash
    sam deploy --guided
    ```

    During deployment, you will be prompted for the following parameters:

    *   `NewRelicAccountId`: Enter your New Relic account ID.
    *   `NewRelicLicenseKey`: Enter your New Relic license key (Ingest-License key).

    Once the deployment is complete, the `ApiUrl` will be displayed in the Outputs. This is your application's endpoint.

## 🤝 コントリビューション (Contributing)

Contributions to this project are welcome! Please submit bug reports and pull requests via GitHub Issues and Pull Requests.

<details>
<summary>日本語</summary>

このプロジェクトへのコントリビューションを歓迎します！バグ報告や機能改善の提案は、GitHubのIssuesやPull Requestsからお願いします。

</details>

## 📜 ライセンス (License)

This project is licensed under the MIT License.

<details>
<summary>日本語</summary>

このプロジェクトは、MIT License のもとで公開されています。

</details>
