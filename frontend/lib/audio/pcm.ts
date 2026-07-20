export class PcmProcessor {
  private buffer: Float32Array;
  private bufferLength: number;
  private sampleRate: number;
  
  private readonly targetSampleRate = 16000;
  private readonly targetChunkSize = 320; // 20ms at 16kHz

  constructor(sourceSampleRate: number) {
    this.sampleRate = sourceSampleRate;
    this.buffer = new Float32Array(this.targetChunkSize * 4);
    this.bufferLength = 0;
  }

  private downsample(input: Float32Array, inputRate: number, outputRate: number): Float32Array {
    if (inputRate === outputRate) {
      return input;
    }
    const ratio = inputRate / outputRate;
    const outputLength = Math.round(input.length / ratio);
    const result = new Float32Array(outputLength);
    
    for (let i = 0; i < outputLength; i++) {
      const position = i * ratio;
      const index = Math.floor(position);
      const fraction = position - index;
      
      if (index + 1 < input.length) {
        result[i] = input[index] * (1 - fraction) + input[index + 1] * fraction;
      } else {
        result[i] = input[index];
      }
    }
    return result;
  }

  private mixToMono(inputs: Float32Array[]): Float32Array {
    if (inputs.length === 0) return new Float32Array(0);
    if (inputs.length === 1) return inputs[0];
    
    const length = inputs[0].length;
    const result = new Float32Array(length);
    for (let i = 0; i < length; i++) {
      let sum = 0;
      for (let ch = 0; ch < inputs.length; ch++) {
        sum += inputs[ch][i];
      }
      result[i] = sum / inputs.length;
    }
    return result;
  }

  private appendSamples(samples: Float32Array): void {
    const requiredLength = this.bufferLength + samples.length;
    if (requiredLength > this.buffer.length) {
      const nextCapacity = Math.max(requiredLength, this.buffer.length * 2);
      const nextBuffer = new Float32Array(nextCapacity);
      nextBuffer.set(this.buffer.subarray(0, this.bufferLength), 0);
      this.buffer = nextBuffer;
    }

    this.buffer.set(samples, this.bufferLength);
    this.bufferLength = requiredLength;
  }

  private toPcmChunk(samples: Float32Array): ArrayBuffer {
    const buffer = new ArrayBuffer(samples.length * 2);
    const view = new DataView(buffer);

    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      const int16 = Math.round(s < 0 ? s * 0x8000 : s * 0x7fff);
      view.setInt16(i * 2, int16, true);
    }

    return buffer;
  }

  public process(inputs: Float32Array[]): ArrayBuffer[] {
    if (inputs.length === 0 || inputs[0].length === 0) return [];
    
    const mono = this.mixToMono(inputs);
    const downsampled = this.downsample(mono, this.sampleRate, this.targetSampleRate);
    this.appendSamples(downsampled);
    
    const chunks: ArrayBuffer[] = [];
    
    while (this.bufferLength >= this.targetChunkSize) {
      const chunkSamples = this.buffer.subarray(0, this.targetChunkSize);
      chunks.push(this.toPcmChunk(chunkSamples));

      this.buffer.copyWithin(0, this.targetChunkSize, this.bufferLength);
      this.bufferLength -= this.targetChunkSize;
    }
    
    return chunks;
  }

  public flush(): ArrayBuffer | null {
    if (this.bufferLength === 0) return null;
    
    const chunkSamples = this.buffer.subarray(0, this.bufferLength);
    const buffer = this.toPcmChunk(chunkSamples);
    
    this.bufferLength = 0;
    return buffer;
  }
}
