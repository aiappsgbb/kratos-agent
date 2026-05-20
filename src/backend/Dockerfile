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

EXPOSE 8000

ENV GIT_PYTHON_REFRESH=quiet

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
