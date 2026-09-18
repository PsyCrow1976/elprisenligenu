FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY script/ script/
COPY web/ web/

RUN mkdir -p /var/log/elprisenligenu

ENV JOB_LOG_PATH=/var/log/elprisenligenu/prices.log \
    JOB_INTERVAL_HOURS=12

EXPOSE 8088

CMD ["python", "-m", "web"]
