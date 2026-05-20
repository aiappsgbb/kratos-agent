FROM python:3.11-slim

WORKDIR /app

# ── Layer 1: System deps + Node.js 20 (for Copilot CLI + MCP servers) ──
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Layer 2: Global npm packages (Copilot CLI + Faker MCP) ──
RUN npm install -g @github/copilot@latest faker-mcp-server@latest \
    && rm -rf /root/.npm /tmp/*

# ── Layer 2b: In-repo mock MCP servers (Salesforce, etc.) ──
COPY mocks/ /opt/mocks/
RUN cd /opt/mocks \
    && npm install --workspaces \
    && npm run build --workspaces --if-present \
    && npm install -g ./packages/* \
    && rm -rf /root/.npm /tmp/*

# ── Layer 3: Playwright Chromium for PDF rendering ──
RUN npx -y playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* /tmp/*

# ── Layer 4: Python dependencies ──
COPY src/hosted-agent/pyproject.toml /app/hosted-agent/
RUN pip install --no-cache-dir /app/hosted-agent/

# ── Layer 5: Backend app modules (reused by the hosted agent) ──
COPY src/backend/app/ /app/backend/app/

# ── Layer 6: Hosted agent entry point ──
COPY src/hosted-agent/main.py /app/hosted-agent/

# ── Layer 7: Use-case manifests (skills, system prompts) ──
COPY use-cases/ /app/use-cases/

WORKDIR /app/hosted-agent

EXPOSE 8088

ENV GIT_PYTHON_REFRESH=quiet
ENV PYTHONPATH=/app

CMD ["python", "main.py"]
