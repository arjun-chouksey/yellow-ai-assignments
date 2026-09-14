FROM python:3.13.7-slim
WORKDIR /app
COPY app/ /app/
RUN useradd --uid 10001 --create-home app && mkdir /data && chown app:app /data
USER app
CMD ["python", "server.py"]
