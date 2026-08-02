/**
 * Shared headline-value extractor for saved findings.
 * Used at pin time (page.tsx), in the workspace card (ExecutiveWorkspace.tsx),
 * and for check-now comparison — all three use this single function so the
 * number is always computed identically.
 */

export function extractHeadline(
  result: { columns?: string[]; rows?: any[][]; semantic_columns?: any[] } | null | undefined
): { value: number | null; label: string | null } {
  if (!result) return { value: null, label: null };
  const semantics = result.semantic_columns ?? [];
  const rows = result.rows ?? [];
  const metricIndex = semantics.findIndex(
    (c) => c.role === "metric" || c.value_type === "number"
  );
  const idx = metricIndex >= 0 ? metricIndex : 1;
  const metricColumn = semantics[idx];
  if (rows.length === 0 || !metricColumn) return { value: null, label: null };
  const raw = rows[0][idx];
  const value = typeof raw === "number" ? raw : Number(raw);
  return {
    value: Number.isFinite(value) ? value : null,
    label: metricColumn.display_name ?? null,
  };
}
