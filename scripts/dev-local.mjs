#!/usr/bin/env node
// Run the whole Kratos stack locally without Docker:
//   Azurite (blob) -> hosted agent (Copilot SDK + AG-UI, :8088) -> backend (:8000)
//   -> Next.js frontend with the CopilotKit runtime route (:3000)
//
//   node scripts/dev-local.mjs           live model (COPILOT_GITHUB_TOKEN from .env.local)
//   node scripts/dev-local.mjs --mock    deterministic offline model (aimock, :5567)
//
// Prerequisites (once): see README "Run locally without Docker".
import { spawn } from "node:child_process";
import { chmodSync, cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const mock = process.argv.includes("--mock");
const win = process.platform === "win32";
const venvBin = path.join(root, "src/backend/.venv", win ? "Scripts" : "bin");
const python = path.join(venvBin, win ? "python.exe" : "python");
const npx = win ? "npx.cmd" : "npx";
// Persisted state. Live mode shares the folders docker-compose / run-local use,
// so existing conversations and seeded skills carry over; mock mode is separate.
const data = mock ? path.join(root, ".local", "mock") : path.join(root, ".local");
// Throwaway working folders, recreated on every start.
const scratch = path.join(data, "dev-local");

const PORTS = { azurite: 10000, hosted: 8088, backend: 8000, web: 3000, model: 5567 };
const AZURITE_CONNECTION =
  // Azurite's published, well-known development account key (not a secret).
  "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;" +
  `BlobEndpoint=http://127.0.0.1:${PORTS.azurite}/devstoreaccount1;`;

function readEnvFile(file) {
  if (!existsSync(file)) return {};
  const out = {};
  for (const line of readFileSync(file, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
    if (m && !line.trim().startsWith("#")) out[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
  return out;
}

// Put every in-repo mock MCP server on PATH under the command its package
// declares (personas' .mcp.json files call them by name, as in the container).
// npm workspaces do not reliably link every package's bin, so link them here.
function linkMockServers(binDir) {
  rmSync(binDir, { recursive: true, force: true });
  mkdirSync(binDir, { recursive: true });
  const packages = path.join(root, "mocks", "packages");
  const linked = [];
  for (const name of existsSync(packages) ? readdirSync(packages) : []) {
    const manifest = path.join(packages, name, "package.json");
    if (!existsSync(manifest)) continue;
    const bins = JSON.parse(readFileSync(manifest, "utf8")).bin ?? {};
    for (const [command, rel] of Object.entries(typeof bins === "string" ? { [name]: bins } : bins)) {
      const target = path.join(packages, name, rel);
      if (!existsSync(target)) continue;
      if (win) {
        writeFileSync(path.join(binDir, `${command}.cmd`), `@node "${target}" %*\r\n`);
      } else {
        chmodSync(target, 0o755);
        symlinkSync(target, path.join(binDir, command));
      }
      linked.push(command);
    }
  }
  return linked;
}

function portFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer().once("error", () => resolve(false));
    server.once("listening", () => server.close(() => resolve(true))).listen(port, "127.0.0.1");
  });
}

function waitForPort(port, label, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const socket = net.connect(port, "127.0.0.1");
      socket.once("connect", () => {
        socket.destroy();
        resolve();
      });
      socket.once("error", () => {
        socket.destroy();
        if (Date.now() > deadline) reject(new Error(`${label} did not open port ${port}`));
        else setTimeout(attempt, 500);
      });
    };
    attempt();
  });
}

async function waitFor(url, label, timeoutMs = 180_000, init = undefined) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, init);
      if (res.status < 500) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`${label} did not become ready at ${url}`);
}

const children = [];
function run(name, cmd, args, opts) {
  const child = spawn(cmd, args, { ...opts, stdio: ["ignore", "pipe", "pipe"], shell: win });
  const prefix = `[${name}]`.padEnd(10);
  for (const stream of [child.stdout, child.stderr]) {
    let buf = "";
    stream.on("data", (chunk) => {
      buf += chunk;
      const lines = buf.split(/\r?\n/);
      buf = lines.pop();
      for (const line of lines) if (line.trim()) process.stdout.write(`${prefix} ${line}\n`);
    });
  }
  child.on("exit", (code) => {
    if (!shuttingDown) {
      console.error(`${prefix} exited with code ${code}; stopping the stack.`);
      shutdown(1);
    }
  });
  children.push(child);
  return child;
}

let shuttingDown = false;
function shutdown(code = 0) {
  shuttingDown = true;
  for (const child of children) if (child.exitCode === null) child.kill("SIGTERM");
  setTimeout(() => process.exit(code), 1500).unref();
}
process.once("SIGINT", () => shutdown(0));
process.once("SIGTERM", () => shutdown(0));

async function main() {
  if (!existsSync(python)) {
    throw new Error(`Python venv not found at ${python}. See README "Run locally without Docker".`);
  }
  const fileEnv = readEnvFile(path.join(root, ".env.local"));
  const token = process.env.COPILOT_GITHUB_TOKEN || fileEnv.COPILOT_GITHUB_TOKEN || "";
  if (!mock && !token) throw new Error("Live mode needs COPILOT_GITHUB_TOKEN (env or .env.local), or use --mock.");

  const wanted = mock ? Object.entries(PORTS) : Object.entries(PORTS).filter(([k]) => k !== "model");
  for (const [name, port] of wanted) {
    if (!(await portFree(port))) throw new Error(`Port ${port} (${name}) is already in use.`);
  }

  // Like the containers, each Python service runs from a working folder that
  // holds its own copy of use-cases/: blob seeding reads ./use-cases, blob sync
  // writes into it, and APM installs and the skill registry rewrite files in it.
  // Copies keep all of that out of the repo's tracked use-cases/.
  const workDir = (name) => {
    const dir = path.join(scratch, name);
    rmSync(dir, { recursive: true, force: true });
    cpSync(path.join(root, "use-cases"), path.join(dir, "use-cases"), { recursive: true });
    return dir;
  };
  const hostedDir = workDir("hosted-agent");
  const backendDir = workDir("backend");

  const mocksBin = path.join(scratch, "bin");
  const linked = linkMockServers(mocksBin);
  if (!linked.length) console.warn("No mock MCP servers found; build them first (see README).");
  const pathSep = win ? ";" : ":";
  const base = {
    ...process.env,
    LOCAL_MODE: "true",
    ENVIRONMENT: "development",
    APM_ENABLED: "true",
    BLOB_STORAGE_CONNECTION_STRING: AZURITE_CONNECTION,
    BLOB_SKILLS_CONTAINER: "skills",
    PATH: [venvBin, mocksBin, process.env.PATH].join(pathSep),
  };
  const model = mock
    ? { OPENAI_BASE_URL: `http://127.0.0.1:${PORTS.model}/v1`, OPENAI_API_KEY: "mock-not-a-secret", OPENAI_CHAT_MODEL_ID: "gpt-4o" }
    : { COPILOT_GITHUB_TOKEN: token, GITHUB_TOKEN: token };

  mkdirSync(path.join(data, "azurite"), { recursive: true });
  // An isolated COPILOT_HOME keeps the developer's own Copilot config (MCP
  // servers, instructions) out of the agent, as in the container.
  const copilotHome = path.join(scratch, "copilot-home");
  mkdirSync(copilotHome, { recursive: true });

  if (mock) {
    run("model", process.execPath, [path.join(root, "src/frontend/e2e/mock-model.mjs")], {
      cwd: path.join(root, "src/frontend"),
      env: { ...process.env, MOCK_PORT: String(PORTS.model) },
    });
  }
  run("azurite", npx, ["-y", "azurite@3", "--silent", "--loose", "--skipApiVersionCheck", "--location", path.join(data, "azurite"),
    "--blobHost", "127.0.0.1", "--blobPort", String(PORTS.azurite), "--queuePort", "10001", "--tablePort", "10002"], { cwd: root, env: base });
  // The services probe blob once at startup and fall back to local files for
  // good if it is not there, so Azurite must be accepting connections first.
  await waitForPort(PORTS.azurite, "azurite");

  run("hosted", python, [path.join(root, "src/hosted-agent/main.py")], {
    cwd: hostedDir,
    env: { ...base, ...model, APM_USE_CASES_ROOT: path.join(hostedDir, "use-cases"), LOCAL_DATA_DIR: path.join(data, "hosted-agent"), PYTHONPATH: path.join(root, "src/backend"), COPILOT_HOME: copilotHome },
  });
  await waitFor(`http://127.0.0.1:${PORTS.hosted}/invocations`, "hosted agent", 180_000, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: '{"warmup":true}',
  });

  run("backend", python, ["-m", "uvicorn", "app.main:app", "--app-dir", path.join(root, "src/backend"), "--host", "127.0.0.1", "--port", String(PORTS.backend)], {
    cwd: backendDir,
    env: { ...base, APM_USE_CASES_ROOT: path.join(backendDir, "use-cases"), LOCAL_DATA_DIR: path.join(data, "backend"), FOUNDRY_AGENT_INVOCATIONS_ENDPOINT: `http://127.0.0.1:${PORTS.hosted}/invocations` },
  });
  await waitFor(`http://127.0.0.1:${PORTS.backend}/health`, "backend");

  run("web", npx, ["next", "dev", "-H", "127.0.0.1", "-p", String(PORTS.web)], {
    cwd: path.join(root, "src/frontend"),
    env: {
      ...process.env,
      AGENT_BACKEND_URL: `http://127.0.0.1:${PORTS.backend}`,
      KRATOS_API_URL: `http://127.0.0.1:${PORTS.backend}`,
      KRATOS_DEMO_MODE: mock ? "mock" : "",
      COPILOTKIT_TELEMETRY_DISABLED: "true",
      NEXT_TELEMETRY_DISABLED: "1",
    },
  });
  await waitFor(`http://127.0.0.1:${PORTS.web}/config.json`, "frontend");
  console.log(`\nKratos is up (${mock ? "mock model" : "live model"}): http://127.0.0.1:${PORTS.web}\n`);
}

main().catch((err) => {
  console.error(`dev-local: ${err.message}`);
  shutdown(1);
});
