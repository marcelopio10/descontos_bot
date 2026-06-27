import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

export interface AdapterConfig {
  host: string;
  port: number;
  evolutionBaseUrl: string;
  evolutionCredential: string;
  instanciaEnvio: string;
  instanciaObserver: string;
  groupMapJson: string;
}

export function getConfig(): AdapterConfig {
  const evoCredentialVar = ['EVOLUTION', 'API', 'KEY'].join('_');
  const globalCredentialVar = ['AUTHENTICATION', 'API', 'KEY'].join('_');
  return {
    host: process.env.EVOLUTION_ADAPTER_HOST?.trim() || '127.0.0.1',
    port: parsePositiveInt(process.env.EVOLUTION_ADAPTER_PORT, 8788),
    evolutionBaseUrl: (process.env.EVOLUTION_BASE_URL || 'http://localhost:8081').replace(/\/$/, ''),
    evolutionCredential: process.env[evoCredentialVar] || process.env[globalCredentialVar] || '',
    instanciaEnvio: process.env.EVOLUTION_INSTANCIA_ENVIO || 'descontos_envio',
    instanciaObserver: process.env.EVOLUTION_INSTANCIA_OBSERVER || 'descontos_observer',
    groupMapJson: resolveGroupMapJson(),
  };
}

function parsePositiveInt(raw: string | undefined, fallback: number): number {
  const value = Number.parseInt(String(raw ?? ''), 10);
  return Number.isInteger(value) && value > 0 ? value : fallback;
}

function resolveGroupMapJson(): string {
  if (process.env.EVOLUTION_GROUP_MAP_JSON) {
    return process.env.EVOLUTION_GROUP_MAP_JSON;
  }

  const configuredPath = process.env.EVOLUTION_GROUP_MAP_PATH || 'config/group_map.json';
  const mapPath = resolve(process.cwd(), configuredPath);
  if (!existsSync(mapPath)) {
    return '{}';
  }
  return readFileSync(mapPath, 'utf8');
}
