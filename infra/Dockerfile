FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md /app/
COPY autonaparnik /app/autonaparnik
COPY prompts /app/prompts
COPY data /app/data
RUN pip install --no-cache-dir .
ENV MCP_LISTEN_HOST=0.0.0.0
ENV MCP_LISTEN_PORT=8765
EXPOSE 8765
CMD ["python", "-m", "autonaparnik.mcp_server"]
