import "@testing-library/jest-dom/vitest";

window.scrollTo = () => {};

// ── Canvas mock ────────────────────────────────────────────────────────────
// jsdom does not implement HTMLCanvasElement.getContext.
// VoiceVisualizer only calls getContext when `analyser` is non-null AND
// state === "recording". In unit tests the analyser is always null so the
// canvas branch is never reached — but jsdom still emits a "Not implemented"
// warning for the canvas element being in the DOM. Return a minimal no-op
// context so tests remain silent.

// eslint-disable-next-line @typescript-eslint/no-explicit-any
(HTMLCanvasElement.prototype as any).getContext = function () {
  return {
    clearRect: () => {},
    save: () => {},
    restore: () => {},
    translate: () => {},
    scale: () => {},
    beginPath: () => {},
    arc: () => {},
    fill: () => {},
    fillRect: () => {},
    fillText: () => {},
    createRadialGradient: () => ({
      addColorStop: () => {},
    }),
    createLinearGradient: () => ({
      addColorStop: () => {},
    }),
    measureText: () => ({ width: 0 }),
    drawImage: () => {},
    strokeRect: () => {},
    stroke: () => {},
    setLineDash: () => {},
    putImageData: () => {},
    getImageData: () => ({ data: new Uint8ClampedArray(0) }),
    canvas: this,
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    font: "",
    textAlign: "start",
    textBaseline: "alphabetic",
    globalAlpha: 1,
    globalCompositeOperation: "source-over",
  };
};

// ── Navigation mock ────────────────────────────────────────────────────────
// jsdom does not implement full navigation (e.g. anchor href click for CSV
// download). The CSV download test creates a Blob URL and calls a.click().
// jsdom throws "Not implemented: navigation (except hash changes)".
// Override HTMLAnchorElement.click so download-triggered navigations are
// silently absorbed in tests.
const _origAnchorClick = HTMLAnchorElement.prototype.click;
HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
  // If the anchor carries a download attribute, this is a file download
  // trigger — silently absorb it in jsdom.
  if (this.hasAttribute("download")) {
    return;
  }
  _origAnchorClick.call(this);
};
