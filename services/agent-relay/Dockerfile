FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=3978
WORKDIR /srv
COPY requirements.txt requirements-host.txt ./
RUN pip install --no-cache-dir -r requirements-host.txt
COPY relay ./relay
COPY templates ./templates
COPY host_m365.py dev_server.py ./
RUN useradd --uid 10001 --no-create-home appuser
USER 10001
EXPOSE 3978
# /api/messages requires a Bot Service JWT; use a TCP probe on 3978 for health.
CMD ["python", "host_m365.py"]
