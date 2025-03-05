FROM python:alpine

WORKDIR /app

RUN apk add --no-cache py3-pip tini git
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY main.py .

ENTRYPOINT ["tini", "--", "gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "main:app"]
