FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Python 의존성
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 코드 복사
COPY . .

# Streamlit 설정
RUN mkdir -p /root/.streamlit
RUN echo '[server]\nheadless = true\nport = 8501\naddress = "0.0.0.0"\nenableCORS = false\nenableXsrfProtection = false\n' > /root/.streamlit/config.toml

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app.py"]
