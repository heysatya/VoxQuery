/**
 * Executive PDF Briefing Report Exporter (PRD Feature 7).
 *
 * Configures the viewport page layouts, styling rules, and header sections
 * for a board-ready PDF print briefing.
 */

export function triggerPdfExport(
  title: string = "VoxQuery Executive Briefing Report",
  summary: string = "",
  kpis: { label: string; value: string; insight: string }[] = []
): void {
  if (typeof window === "undefined") return;

  const styleId = "print-pdf-styling-rules";
  let styleEl = document.getElementById(styleId) as HTMLStyleElement | null;
  if (!styleEl) {
    styleEl = document.createElement("style");
    styleEl.id = styleId;
    styleEl.innerHTML = `
      @media print {
        body {
          background: #ffffff !important;
          color: #000000 !important;
          font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
          font-size: 12pt !important;
        }
        header, footer, nav, button, select, .no-print {
          display: none !important;
        }
        .print-only {
          display: block !important;
        }
        .briefing-report-container {
          width: 100% !important;
          margin: 0 !important;
          padding: 20mm !important;
          page-break-after: always;
        }
        h1 {
          font-size: 24pt !important;
          margin-bottom: 5mm !important;
          border-bottom: 2px solid #333333 !important;
          padding-bottom: 2mm !important;
        }
        h2 {
          font-size: 16pt !important;
          margin-top: 10mm !important;
          margin-bottom: 3mm !important;
        }
        .kpi-table {
          width: 100% !important;
          border-collapse: collapse !important;
          margin-top: 5mm !important;
        }
        .kpi-table th, .kpi-table td {
          border: 1px solid #cccccc !important;
          padding: 3mm !important;
          text-align: left !important;
        }
        .kpi-table th {
          background-color: #f2f2f2 !important;
        }
      }
    `;
    document.head.appendChild(styleEl);
  }

  // Trigger default print engine which saves to PDF
  window.print();
}
