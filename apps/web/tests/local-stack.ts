import { spawn, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import next from "next";

const loopback = "127.0.0.1";

async function checkHealth(url: string, instanceId: string, api: ChildProcess) {
  for (let attempt = 0; attempt < 200 && api.exitCode === null && api.signalCode === null; attempt++) {
    const response = await fetch(url, { signal: AbortSignal.timeout(1000) }).catch(() => undefined);
    if (response) {
      if (response.headers.get("TradeLang-Instance") !== instanceId) {
        await response.body?.cancel();
        throw new Error(`Unexpected TradeLang instance at ${url}`);
      }
      await response.body?.cancel();
      if (response.ok) return;
    }
    await delay(50);
  }
  throw new Error(`Test instance did not become healthy at ${url}`);
}

export default async function startLocalStack() {
  const web = resolve(__dirname, "..");
  const temporary = mkdtempSync(join(realpathSync(tmpdir()), "tradelang-web-test-"));
  const library = join(temporary, "library");
  const readyFile = join(temporary, "ready.json");
  let app: ReturnType<typeof next> | undefined;
  let handler: ReturnType<ReturnType<typeof next>["getRequestHandler"]> | undefined;
  let api: ChildProcess | undefined;
  let apiClosed: Promise<unknown> | undefined;
  const server = createServer((request, response) => {
    if (!handler) {
      response.writeHead(503).end();
      return;
    }
    void handler(request, response).catch((error: Error) => response.destroy(error));
  });

  async function stop() {
    try {
      const closed = new Promise<void>((done) => server.close(() => done()));
      server.closeAllConnections();
      await closed;
      await app?.close();
    } finally {
      if (api && api.exitCode === null && api.signalCode === null) {
        api.kill("SIGTERM");
        const force = setTimeout(() => api?.kill("SIGKILL"), 8000);
        try {
          await apiClosed;
        } finally {
          clearTimeout(force);
        }
      }
      rmSync(temporary, { recursive: true, force: true });
    }
  }

  try {
    server.listen({ host: loopback, port: 0 });
    await once(server, "listening");
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("Test frontend has no TCP endpoint");
    const origin = `http://${loopback}:${address.port}`;
    api = spawn("tradelang-local", [
      "--data-root", library,
      "--api-port", "0",
      "--web-port", String(address.port),
      "--ready-file", readyFile,
    ], { cwd: resolve(web, "../.."), stdio: "inherit" });
    let launchError: Error | undefined;
    api.once("error", (error) => { launchError = error; });
    apiClosed = new Promise((done) => api!.once("close", done));
    const deadline = Date.now() + 20_000;
    while (!existsSync(readyFile) && !launchError && api.exitCode === null &&
      api.signalCode === null && Date.now() < deadline) {
      await delay(50);
    }
    if (launchError) throw launchError;
    if (!existsSync(readyFile)) throw new Error("Test supervisor did not publish readiness");
    const ready = JSON.parse(readFileSync(readyFile, "utf8"));
    const apiURL = new URL(ready.url);
    if (ready.pid !== api.pid || ready.data_root !== library || typeof ready.instance_id !== "string" ||
      apiURL.protocol !== "http:" || apiURL.hostname !== loopback || !apiURL.port ||
      apiURL.origin !== ready.url) {
      throw new Error("Test supervisor published mismatched readiness");
    }
    await checkHealth(`${apiURL.origin}/health`, ready.instance_id, api);

    process.env.TRADELANG_API_PORT = apiURL.port;
    process.env.TRADELANG_WEB_PORT = String(address.port);
    app = next({ dev: false, dir: web, hostname: loopback, port: address.port });
    await app.prepare();
    handler = app.getRequestHandler();
    await checkHealth(`${origin}/api/health`, ready.instance_id, api);
    process.env.TRADELANG_TEST_ORIGIN = origin;
    process.env.TRADELANG_TEST_LIBRARY = library;
    return stop;
  } catch (error) {
    await stop();
    throw error;
  }
}
