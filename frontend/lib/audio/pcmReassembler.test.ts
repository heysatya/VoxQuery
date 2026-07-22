import { describe, it, expect } from "vitest";
import { PcmChunkReassembler } from "./pcmReassembler";

function int16ToBytes(samples: number[]): ArrayBuffer {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  samples.forEach((s, i) => view.setInt16(i * 2, s, true));
  return buffer;
}

describe("PcmChunkReassembler", () => {
  it("passes through a single even-length chunk unchanged", () => {
    const reassembler = new PcmChunkReassembler();
    const chunk = int16ToBytes([100, -200, 300]);
    const result = reassembler.push(chunk);
    expect(Array.from(result)).toEqual([100, -200, 300]);
    expect(reassembler.hasPendingByte()).toBe(false);
  });

  it("carries over a trailing odd byte instead of dropping it", () => {
    const reassembler = new PcmChunkReassembler();
    // 5 bytes: 2 complete samples + 1 leftover byte (low byte of a 3rd sample)
    const fullBuffer = int16ToBytes([1000, 2000, 3000]);
    const chunk1 = fullBuffer.slice(0, 5); // splits mid-sample
    const chunk2 = fullBuffer.slice(5); // remaining 1 byte

    const result1 = reassembler.push(chunk1);
    expect(Array.from(result1)).toEqual([1000, 2000]);
    expect(reassembler.hasPendingByte()).toBe(true);

    const result2 = reassembler.push(chunk2);
    expect(Array.from(result2)).toEqual([3000]);
    expect(reassembler.hasPendingByte()).toBe(false);
  });

  it("reconstructs the exact original sample sequence across many arbitrarily-sized chunks", () => {
    // Simulates the real-world case: an upstream HTTP stream chunked with no
    // awareness of 16-bit sample boundaries, split at odd byte offsets.
    const originalSamples = [111, -222, 333, -444, 555, -666, 777, -888, 999];
    const fullBuffer = int16ToBytes(originalSamples);
    const chunkSizes = [3, 5, 1, 4, 2, 3]; // deliberately misaligned, sums to 18 bytes = 9 samples

    const reassembler = new PcmChunkReassembler();
    const reconstructed: number[] = [];
    let offset = 0;
    for (const size of chunkSizes) {
      const chunk = fullBuffer.slice(offset, offset + size);
      offset += size;
      reconstructed.push(...Array.from(reassembler.push(chunk)));
    }

    expect(reconstructed).toEqual(originalSamples);
    expect(reassembler.hasPendingByte()).toBe(false);
  });

  it("returns an empty array for an empty chunk", () => {
    const reassembler = new PcmChunkReassembler();
    const result = reassembler.push(new ArrayBuffer(0));
    expect(result.length).toBe(0);
  });

  it("returns an empty array when a chunk is entirely a single carried-over byte", () => {
    const reassembler = new PcmChunkReassembler();
    const fullBuffer = int16ToBytes([42]);
    reassembler.push(fullBuffer.slice(0, 1)); // 1 byte in, nothing complete yet
    expect(reassembler.hasPendingByte()).toBe(true);
    const result = reassembler.push(new ArrayBuffer(0));
    expect(result.length).toBe(0);
    expect(reassembler.hasPendingByte()).toBe(true); // still pending, untouched by the empty push
  });

  it("reset() clears any pending carry-over byte", () => {
    const reassembler = new PcmChunkReassembler();
    const fullBuffer = int16ToBytes([1, 2]);
    reassembler.push(fullBuffer.slice(0, 3)); // 1 complete sample + 1 pending byte
    expect(reassembler.hasPendingByte()).toBe(true);

    reassembler.reset();
    expect(reassembler.hasPendingByte()).toBe(false);

    // A fresh push after reset should not incorrectly prepend the old byte
    const result = reassembler.push(int16ToBytes([999]));
    expect(Array.from(result)).toEqual([999]);
  });
});
