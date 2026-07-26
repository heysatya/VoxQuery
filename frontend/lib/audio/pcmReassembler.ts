/**
 * Reassembles a stream of arbitrarily-chunked 16-bit PCM bytes (e.g. from a
 * WebSocket relaying an upstream HTTP byte stream, which has no reason to
 * align chunk boundaries to 2-byte sample boundaries) into clean, complete
 * Int16 samples.
 *
 * Why this exists: naively slicing off a trailing odd byte from each chunk
 * (the previous approach) silently corrupts audio whenever a 16-bit sample
 * is split across two chunks — the low byte of that sample is dropped, and
 * the orphaned high byte from the next chunk gets misread as an unrelated
 * sample. Every occurrence injects a garbage sample into the stream, which
 * is audible as a click, pop, or burst of static. This class never drops a
 * byte: any odd trailing byte is carried over and prepended to the next
 * chunk instead.
 */
export class PcmChunkReassembler {
  private carryOver: Uint8Array | null = null;

  /**
   * Feed the next raw chunk. Returns a clean Int16Array containing every
   * complete sample available so far (from this chunk plus any carried-over
   * byte from the previous one). If the chunk ends mid-sample, that trailing
   * byte is held back internally and used to complete the next chunk.
   */
  push(chunk: ArrayBuffer): Int16Array {
    let bytes = new Uint8Array(chunk);

    if (this.carryOver) {
      const combined = new Uint8Array(this.carryOver.length + bytes.length);
      combined.set(this.carryOver, 0);
      combined.set(bytes, this.carryOver.length);
      bytes = combined;
      this.carryOver = null;
    }

    if (bytes.length % 2 !== 0) {
      this.carryOver = bytes.slice(bytes.length - 1);
      bytes = bytes.slice(0, bytes.length - 1);
    }

    if (bytes.length === 0) {
      return new Int16Array(0);
    }

    // Copy into a fresh, aligned buffer: bytes.buffer may have a non-zero
    // byteOffset (from the slice() calls above) or an odd base offset that
    // Int16Array's strict alignment requirements don't tolerate directly.
    const aligned = new Uint8Array(bytes.length);
    aligned.set(bytes);
    return new Int16Array(aligned.buffer);
  }

  /** True if a partial (odd, incomplete) trailing byte is currently held back. */
  hasPendingByte(): boolean {
    return this.carryOver !== null;
  }

  /** Reset state — call when starting a new audio stream (e.g. a new TTS turn). */
  reset(): void {
    this.carryOver = null;
  }
}
