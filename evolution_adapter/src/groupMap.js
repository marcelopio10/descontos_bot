import { existsSync, readFileSync } from 'node:fs';

export function loadGroupMap(config) {
  let rawMap = {};
  if (config.groupMapJson) {
    rawMap = JSON.parse(config.groupMapJson);
  } else if (existsSync(config.groupMapPath)) {
    rawMap = JSON.parse(readFileSync(config.groupMapPath, 'utf-8'));
  }

  const byName = new Map();
  const byJid = new Map();

  for (const [name, value] of Object.entries(rawMap)) {
    const item = normalizeGroupEntry(name, value);
    if (!item) continue;
    byName.set(name, item);
    byJid.set(item.jid, item);
  }

  return {
    resolve(target) {
      if (typeof target !== 'string' || !target.trim()) {
        throw new Error('Destino inválido');
      }
      const trimmed = target.trim();
      if (trimmed.endsWith('@g.us')) return trimmed;
      const item = byName.get(trimmed);
      if (!item) throw new Error(`Grupo "${trimmed}" não encontrado no mapa Evolution`);
      return item.jid;
    },
    subjectFor(jid) {
      return byJid.get(jid)?.subject || jid;
    },
    listAllowed(allowedJids) {
      const allowed = new Set(allowedJids);
      return Array.from(allowed)
        .filter((jid) => byJid.has(jid))
        .map((jid) => ({ jid, subject: byJid.get(jid).subject }));
    },
  };
}

function normalizeGroupEntry(name, value) {
  if (typeof value === 'string' && value.endsWith('@g.us')) {
    return { jid: value, subject: name };
  }
  if (value && typeof value === 'object' && typeof value.jid === 'string' && value.jid.endsWith('@g.us')) {
    return { jid: value.jid, subject: typeof value.subject === 'string' ? value.subject : name };
  }
  return null;
}
