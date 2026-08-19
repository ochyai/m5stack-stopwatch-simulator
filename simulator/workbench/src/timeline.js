function logSignature(entry) {
  return JSON.stringify([
    entry?.time ?? entry?.timestamp ?? null,
    entry?.kind ?? entry?.type ?? null,
    entry?.message ?? entry?.line ?? entry?.event ?? null,
    entry?.detail ?? null,
    entry?.sequence ?? null,
  ]);
}

export function nativeLogKeys(log) {
  const occurrences = new Map();
  return (Array.isArray(log) ? log : []).map((entry) => {
    const signature = logSignature(entry);
    const occurrence = occurrences.get(signature) ?? 0;
    occurrences.set(signature, occurrence + 1);
    return `${signature}\u0000${occurrence}`;
  });
}

export function createNativeLogWatermark(snapshot) {
  const log = Array.isArray(snapshot?.log) ? snapshot.log : [];
  return {
    firmware: String(snapshot?.firmware?.id ?? ""),
    revision: Number(snapshot?.revision) || 0,
    signatures: log.map(logSignature),
  };
}

export function nativeLogsAfterWatermark(snapshot, watermark) {
  const log = Array.isArray(snapshot?.log) ? snapshot.log : [];
  if (!watermark) return log;

  const sameGeneration = watermark.firmware === String(snapshot?.firmware?.id ?? "")
    && (Number(snapshot?.revision) || 0) >= watermark.revision;
  if (!sameGeneration) return log;

  const previous = Array.isArray(watermark.signatures) ? watermark.signatures : [];
  const current = log.map(logSignature);
  let overlap = Math.min(previous.length, current.length);

  while (overlap > 0) {
    const previousOffset = previous.length - overlap;
    let matches = true;
    for (let index = 0; index < overlap; index += 1) {
      if (previous[previousOffset + index] !== current[index]) {
        matches = false;
        break;
      }
    }
    if (matches) break;
    overlap -= 1;
  }

  return log.slice(overlap);
}

export function latestOrderedEvents(events, limit = 7) {
  const boundedLimit = Math.max(0, Math.trunc(Number(limit) || 0));
  if (boundedLimit === 0) return [];
  return [...(Array.isArray(events) ? events : [])]
    .sort((left, right) => (Number(left?.order) || 0) - (Number(right?.order) || 0))
    .slice(-boundedLimit);
}
