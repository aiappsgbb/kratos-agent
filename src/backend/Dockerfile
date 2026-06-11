FROM python:3.11-slim

WORKDIR /app

# ── Layer 1: System deps + Node.js 20 (cached unless base image changes) ──
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Layer 2: Global npm packages (pinned for reproducibility) ──
RUN npm install -g @github/copilot@latest faker-mcp-server@latest \
    && rm -rf /root/.npm /tmp/*

# ── Layer 2b: In-repo mock MCP servers (Salesforce, etc.) ──
COPY mocks/ /opt/mocks/
RUN cd /opt/mocks \
    && npm install --workspaces \
    && npm run build --workspaces --if-present \
    && npm install -g ./packages/* \
    && rm -rf /root/.npm /tmp/*

# ── Layer 3: Playwright Chromium + system deps for PDF rendering ──
RUN npx -y playwright install --with-deps chromium\
    && rm -rf /var/lib/apt/lists/* /tmp/*

# ── Layer 4: Python dependencies (cached unless pyproject.toml changes) ──
COPY src/backend/pyproject.toml .
RUN pip install --no-cache-dir .

# ── Layer 5: Application code (changes frequently) ──
COPY src/backend/ .

# ── Layer 6: Use-case manifests (apm.yml, SYSTEM_PROMPT, skills) ──
COPY use-cases/ use-cases/

# ── Layer 7: Repo assets needed by the project-exporter service ──
# The /api/use-cases/{name}/export endpoint assembles a self-contained
# Foundry Hosted Agent ZIP at request time. It needs the live Kratos
# source tree on disk: src/hosted-agent/ (verbatim main.py + Dockerfile +
# pyproject.toml + agent.yaml + agent.manifest.yaml), src/backend/app/
# (full backend app copied verbatim — the existing COPY src/backend/ .
# above flattens it to /app/, but the exporter resolves repo_root=/app
# and walks src/backend/app from there), infra/ (Bicep modules copied
# verbatim into the export), and mocks/ (workspace for bundling any
# local stdio MCP servers a use-case depends on).
COPY src/hosted-agent/ src/hosted-agent/
COPY src/backend/app/ src/backend/app/
COPY infra/ infra/
COPY mocks/ mocks/

EXPOSE 8000

ENV GIT_PYTHON_REFRESH=quiet

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
