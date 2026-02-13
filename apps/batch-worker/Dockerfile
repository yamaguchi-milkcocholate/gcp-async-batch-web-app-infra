# バッチワーカー用 Dockerfile
FROM python:3.12-slim

# 作業ディレクトリ設定
WORKDIR /app

# システムパッケージ更新と必要なツールインストール
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# uv インストール
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# 依存関係ファイルをコピー
COPY pyproject.toml ./

# 依存関係インストール（uv使用）
RUN uv pip install --system -r pyproject.toml

# アプリケーションコードをコピー
COPY . .

# エントリーポイント（gunicorn でFlaskアプリを起動）
# Cloud Runの環境変数 PORT (デフォルト8080) でリッスン
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 1800 worker:app
