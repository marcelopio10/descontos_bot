import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { loadEnvFromNearestFile } from "./env.js";

const OBSERVER_ENV_KEYS = [
  "WA_OBSERVER_ENABLED",
  "WA_OBSERVER_GROUP_JIDS",
  "WA_OBSERVER_LOOKBACK_HOURS",
  "WA_OBSERVER_MAX_MESSAGES_PER_GROUP",
  "WA_OBSERVER_SENDER_HASH_SALT",
];

let tempRoot: string;

beforeEach(() => {
  tempRoot = mkdtempSync(join(tmpdir(), "wa-env-test-"));
  for (const key of OBSERVER_ENV_KEYS) {
    delete process.env[key];
  }
});

afterEach(() => {
  rmSync(tempRoot, { recursive: true, force: true });
  for (const key of OBSERVER_ENV_KEYS) {
    delete process.env[key];
  }
});

describe("loadEnvFromNearestFile", () => {
  it("carrega WA_OBSERVER_* do .env na raiz do repo quando o serviço roda em wa_service", () => {
    const serviceDir = join(tempRoot, "wa_service");
    mkdirSync(serviceDir);
    writeFileSync(
      join(tempRoot, ".env"),
      [
        "WA_OBSERVER_ENABLED=true",
        "WA_OBSERVER_GROUP_JIDS=120363000000000001@g.us,120363000000000002@g.us",
        "WA_OBSERVER_LOOKBACK_HOURS=24",
        "WA_OBSERVER_MAX_MESSAGES_PER_GROUP=300",
        "WA_OBSERVER_SENDER_HASH_SALT=local-secret",
      ].join("\n"),
      "utf8"
    );
    expect(loadEnvFromNearestFile(serviceDir)).toEqual(join(tempRoot, ".env"));
    expect(process.env.WA_OBSERVER_ENABLED).toBe("true");
    expect(process.env.WA_OBSERVER_GROUP_JIDS).toBe(
      "120363000000000001@g.us,120363000000000002@g.us"
    );
    expect(process.env.WA_OBSERVER_SENDER_HASH_SALT).toBe("local-secret");
  });

  it("não sobrescreve variável já definida no ambiente do processo", () => {
    const serviceDir = join(tempRoot, "wa_service");
    mkdirSync(serviceDir);
    writeFileSync(join(tempRoot, ".env"), "WA_OBSERVER_ENABLED=true\n", "utf8");
    process.env.WA_OBSERVER_ENABLED = "false";
    loadEnvFromNearestFile(serviceDir);

    expect(process.env.WA_OBSERVER_ENABLED).toBe("false");
  });
});
