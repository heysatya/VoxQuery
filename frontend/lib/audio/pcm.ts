export class PcmProcessor {
  private buffer: Float32Array;
  private bufferLength: number;
  private sampleRate: number;
  
  private readonly targetSampleRate = 16000;
  private readonly targetChunkSize = 1600; // 100ms at 16kHz

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

  public process(inputs: Float32Array[]): ArrayBuffer[] {
    if (inputs.length === 0 || inputs[0].length === 0) return [];
    
    const mono = this.mixToMono(inputs);
    const downsampled = this.downsample(mono, this.sampleRate, this.targetSampleRate);
    
    const newBuffer = new Float32Array(this.bufferLength + downsampled.length);
    newBuffer.set(this.buffer.subarray(0, this.bufferLength), 0);
    newBuffer.set(downsampled, this.bufferLength);
    this.buffer = newBuffer;
    this.bufferLength = newBuffer.length;
    
    const chunks: ArrayBuffer[] = [];
    
    while (this.bufferLength >= this.targetChunkSize) {
      const chunkSamples = this.buffer.subarray(0, this.targetChunkSize);
      const buffer = new ArrayBuffer(this.targetChunkSize * 2);
      const view = new DataView(buffer);
      
      for (let i = 0; i < chunkSamples.length; i++) {
        const s = Math.max(-1, Math.min(1, chunkSamples[i]));
        const int16 = Math.round(s < 0 ? s * 0x8000 : s * 0x7fff);
        view.setInt16(i * 2, int16, true);
      }
      
      chunks.push(buffer);
      
      const remainder = this.buffer.subarray(this.targetChunkSize);
      const nextBuffer = new Float32Array(remainder.length + this.targetChunkSize * 4);
      nextBuffer.set(remainder, 0);
      this.buffer = nextBuffer;
      this.bufferLength = remainder.length;
    }
    
    return chunks;
  }

  public flush(): ArrayBuffer | null {
    if (this.bufferLength === 0) return null;
    
    const chunkSamples = this.buffer.subarray(0, this.bufferLength);
    const buffer = new ArrayBuffer(this.bufferLength * 2);
    const view = new DataView(buffer);
    
    for (let i = 0; i < chunkSamples.length; i++) {
      const s = Math.max(-1, Math.min(1, chunkSamples[i]));
      const int16 = Math.round(s < 0 ? s * 0x8000 : s * 0x7fff);
      view.setInt16(i * 2, int16, true);
    }
    
    this.bufferLength = 0;
    this.buffer = new Float32Array(0);
    return buffer;
  }
}
