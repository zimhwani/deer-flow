FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot source
COPY . /app/trading_bot/

# Data directory for logs and state
RUN mkdir -p /app/data

ENV TRADING_DATA_DIR=/app/data
ENV TRADING_LOG_LEVEL=INFO

CMD ["python", "-m", "trading_bot"]
