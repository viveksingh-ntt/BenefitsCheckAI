FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --uid 10001 --no-create-home appuser
USER 10001
EXPOSE 8103
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8103", "--proxy-headers"]
