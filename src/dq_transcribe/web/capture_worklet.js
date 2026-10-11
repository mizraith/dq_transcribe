/**
 * Audio worklet for dq_transcribe: forwards microphone audio to the page in
 * fixed-size chunks so the page can measure loudness and cut clips.
 *
 * This file is a string.Template: the config placeholder below is replaced by
 * dq_transcribe.server.render_script, so never use a literal dollar sign here.
 */
"use strict";

const CONFIG = ${config};

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(CONFIG.chunkSize);
    this.filled = 0;
  }

  /** Collect input samples and post a copy of the buffer each time it fills. */
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) {
      return true;
    }
    for (let index = 0; index < channel.length; index += 1) {
      this.buffer[this.filled] = channel[index];
      this.filled += 1;
      if (this.filled === this.buffer.length) {
        this.port.postMessage(this.buffer.slice(0));
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor(CONFIG.processorName, CaptureProcessor);
