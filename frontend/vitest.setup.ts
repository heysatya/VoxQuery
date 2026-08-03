import "@testing-library/jest-dom/vitest";

window.scrollTo = () => {};

// ── Canvas mock ────────────────────────────────────────────────────────────
// jsdom does not implement HTMLCanvasElement.getContext.
// VoiceVisualizer only calls getContext when `analyser` is non-null AND
// state === "recording". In unit tests the analyser is always null so the
// canvas branch is never reached — but jsdom still emits a "Not implemented"
// warning for the canvas element being in the DOM. Return a minimal no-op
// context so tests remain silent.

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
    moveTo: () => {},
    lineTo: () => {},
    setTransform: () => {},
    canvas: this,
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    lineCap: "butt",
    font: "",
    textAlign: "start",
    textBaseline: "alphabetic",
    globalAlpha: 1,
    globalCompositeOperation: "source-over",
  };
};

// ── IntersectionObserver mock ─────────────────────────────────────────────
// jsdom does not implement IntersectionObserver. framer-motion's
// `whileInView` (used throughout the marketing landing page for
// scroll-triggered reveals) relies on it. Provide a minimal no-op stub so
// components mount without crashing; entries never fire in tests, which is
// fine since tests assert on final DOM content, not the reveal animation.
class IntersectionObserverMock {
  readonly root: Element | null = null;
  readonly rootMargin: string = "";
  readonly thresholds: ReadonlyArray<number> = [];
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}
(globalThis as any).IntersectionObserver = IntersectionObserverMock;

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
