export function resolveDestination(destination: string, groupMapJson: string): string {
  const target = destination.trim();
  if (target.endsWith("@g.us")) return target;

  let groupMap: Record<string, string> = {};
  try {
    const parsed = JSON.parse(groupMapJson || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      groupMap = parsed as Record<string, string>;
    }
  } catch {
    groupMap = {};
  }

  const mapped = groupMap[target];
  if (!mapped || !mapped.endsWith("@g.us")) {
    throw new Error(`Grupo "${target}" não mapeado para JID.`);
  }
  return mapped;
}
