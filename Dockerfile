# SynapseSupply agent for Amazon Bedrock AgentCore Runtime (docs/agentcore.md).
# AgentCore Runtime runs linux/arm64 images:
#   docker buildx build --platform linux/arm64 -t synapsesupply-agent .
# Serves POST /invocations and GET /ping on port 8080 (bedrock-agentcore SDK).
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra agentcore --extra aicore

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    SYNAPSE_PLANNER=auto \
    SYNAPSE_MODEL_PROVIDERS=bedrock,aicore

# Secrets (AI Core client id/secret) come from the runtime's environment or Secrets Manager,
# never from the image: .env is excluded by .dockerignore.
RUN useradd --uid 1000 --create-home agent
USER agent
EXPOSE 8080
CMD ["python", "-m", "synapse.agentcore"]
