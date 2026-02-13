FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

EXPOSE 9090

CMD ["uvicorn", "node_agent.agent:app", "--host", "0.0.0.0", "--port", "9090"]
