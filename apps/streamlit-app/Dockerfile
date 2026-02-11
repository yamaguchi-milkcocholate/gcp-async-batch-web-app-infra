# Streamlit アプリケーション用 Dockerfile
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

# ポート公開
EXPOSE 8501

# ヘルスチェック
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# エントリーポイント
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
