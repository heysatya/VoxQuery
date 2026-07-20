// This file must be valid JS (no TS, no imports) because it's loaded dynamically via addModule()
class PcmAudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // Assuming global sampleRate is available in the AudioWorkletGlobalScope
    this.sampleRate = sampleRate; 
    
    this.targetSampleRate = 16000;
    this.targetChunkSize = 320; // 20ms at 16kHz
    
    this.buffer = new Float32Array(this.targetChunkSize * 4);
    this.bufferLength = 0;

    this.port.onmessage = (event) => {
      if (event.data && event.data.type === 'flush') {
        this.flush();
        this.port.postMessage({ type: 'flushed' });
      }
    };
  }

  downsample(input, inputRate, outputRate) {
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

  mixToMono(inputs) {
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

  appendSamples(samples) {
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

  postPcmChunk(samples) {
    const chunkBuffer = new ArrayBuffer(samples.length * 2);
    const view = new DataView(chunkBuffer);

    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      const int16 = Math.round(s < 0 ? s * 0x8000 : s * 0x7fff);
      view.setInt16(i * 2, int16, true);
    }

    this.port.postMessage(chunkBuffer, [chunkBuffer]);
  }

  flush() {
    if (this.bufferLength === 0) return;

    this.postPcmChunk(this.buffer.subarray(0, this.bufferLength));
    this.bufferLength = 0;
  }

  process(inputs, outputs, parameters) {
    const inputChannels = inputs[0]; // The first input (we only expect one mic stream)
    if (!inputChannels || inputChannels.length === 0 || inputChannels[0].length === 0) {
      return true; // Keep processor alive
    }
    
    const mono = this.mixToMono(inputChannels);
    const downsampled = this.downsample(mono, this.sampleRate, this.targetSampleRate);

    this.appendSamples(downsampled);
    
    // Extract chunks
    while (this.bufferLength >= this.targetChunkSize) {
      const chunkSamples = this.buffer.subarray(0, this.targetChunkSize);
      this.postPcmChunk(chunkSamples);

      this.buffer.copyWithin(0, this.targetChunkSize, this.bufferLength);
      this.bufferLength -= this.targetChunkSize;
    }
    
    return true; // Keep processor alive
  }
}

registerProcessor('pcm-audio-processor', PcmAudioProcessor);
