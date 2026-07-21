import { describe, it, expect } from 'vitest';
import { PcmProcessor } from './pcm';

describe('PcmProcessor', () => {
  it('should clip and scale Float32 to Int16 correctly', () => {
    const processor = new PcmProcessor(16000);
    // Values: > 1 (should clip to 1), < -1 (should clip to -1), 0, 0.5, -0.5
    const input = new Float32Array([1.5, -1.5, 0, 0.5, -0.5]);
    
    // Process input. We need 320 samples to trigger a chunk, so we'll just flush to get these 5 samples.
    processor.process([input]);
    const result = processor.flush();
    
    expect(result).not.toBeNull();
    const view = new DataView(result as ArrayBuffer);
    
    expect(view.getInt16(0, true)).toBe(0x7fff); // 1.5 clamped to 1 -> 32767
    expect(view.getInt16(2, true)).toBe(-0x8000); // -1.5 clamped to -1 -> -32768
    expect(view.getInt16(4, true)).toBe(0); // 0
    expect(view.getInt16(6, true)).toBe(Math.round(0.5 * 0x7fff)); // 0.5
    expect(view.getInt16(8, true)).toBe(Math.round(-0.5 * 0x8000)); // -0.5
  });

  it('should explicitly output little-endian byte order', () => {
    const processor = new PcmProcessor(16000);
    const input = new Float32Array([16383 / 0x7fff]); // Exactly 16383 = 0x3FFF
    
    processor.process([input]);
    const result = processor.flush();
    
    expect(result).not.toBeNull();
    const bytes = new Uint8Array(result as ArrayBuffer);
    
    // Little endian: least significant byte first (0xFF), most significant byte second (0x3F)
    expect(bytes[0]).toBe(0xff);
    expect(bytes[1]).toBe(0x3f);
  });

  it('should pass through one channel (mono)', () => {
    const processor = new PcmProcessor(16000);
    const input = new Float32Array([0.1, 0.2, 0.3]);
    
    processor.process([input]);
    const result = processor.flush();
    
    const view = new DataView(result as ArrayBuffer);
    expect(view.getInt16(0, true)).toBe(Math.round(0.1 * 0x7fff));
    expect(view.getInt16(2, true)).toBe(Math.round(0.2 * 0x7fff));
    expect(view.getInt16(4, true)).toBe(Math.round(0.3 * 0x7fff));
  });

  it('should average stereo to mono', () => {
    const processor = new PcmProcessor(16000);
    const left = new Float32Array([0.2, 0.4]);
    const right = new Float32Array([0.4, 0.6]);
    
    processor.process([left, right]);
    const result = processor.flush();
    
    const view = new DataView(result as ArrayBuffer);
    // (0.2 + 0.4) / 2 = 0.3
    expect(view.getInt16(0, true)).toBe(Math.round(0.3 * 0x7fff));
    // (0.4 + 0.6) / 2 = 0.5
    expect(view.getInt16(2, true)).toBe(Math.round(0.5 * 0x7fff));
  });

  it('should downsample 48000 to 16000', () => {
    const processor = new PcmProcessor(48000);
    const input = new Float32Array(48);
    for (let i = 0; i < 48; i++) input[i] = i * 0.01; // 0, 0.01, 0.02...
    
    processor.process([input]);
    const result = processor.flush();
    
    expect(result).not.toBeNull();
    const view = new DataView(result as ArrayBuffer);
    const samples = (result as ArrayBuffer).byteLength / 2;
    expect(samples).toBe(16);
    
    // 48000 / 16000 = 3
    // index 0 -> 0 * 3 = 0 -> 0 * 0.01 = 0
    // index 1 -> 1 * 3 = 3 -> 3 * 0.01 = 0.03
    // index 2 -> 2 * 3 = 6 -> 6 * 0.01 = 0.06
    expect(view.getInt16(0, true)).toBe(0);
    expect(view.getInt16(2, true)).toBe(Math.round(0.03 * 0x7fff));
    expect(view.getInt16(4, true)).toBe(Math.round(0.06 * 0x7fff));
  });

  it('should downsample 44100 to 16000', () => {
    const processor = new PcmProcessor(44100);
    const input = new Float32Array(441); // Should produce 160 samples
    
    processor.process([input]);
    const result = processor.flush();
    
    expect(result).not.toBeNull();
    const samples = (result as ArrayBuffer).byteLength / 2;
    expect(samples).toBe(160);
  });

  it('should aggregate chunks to exact 640 bytes (~20ms) and preserve remainder', () => {
    const processor = new PcmProcessor(16000);
    // Give it 1700 samples (100 more than five chunks)
    const input = new Float32Array(1700);
    
    const chunks = processor.process([input]);
    
    expect(chunks.length).toBe(5);
    expect(chunks[0].byteLength).toBe(640); // 320 samples * 2 bytes
    
    // Flush should return the remaining 100 samples
    const remainder = processor.flush();
    expect(remainder).not.toBeNull();
    expect((remainder as ArrayBuffer).byteLength).toBe(200); // 100 samples * 2 bytes
  });

  it('should not emit WAV headers or container bytes', () => {
    const processor = new PcmProcessor(16000);
    const input = new Float32Array(320);
    const chunks = processor.process([input]);
    
    expect(chunks.length).toBe(1);
    const buffer = chunks[0];
    
    // Pure PCM chunk for 320 samples is exactly 640 bytes.
    // If it had a WAV header it would be 684.
    expect(buffer.byteLength).toBe(640);
    
    const bytes = new Uint8Array(buffer);
    // Verify it doesn't start with 'RIFF'
    const isRiff = bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46;
    expect(isRiff).toBe(false);
  });
});
