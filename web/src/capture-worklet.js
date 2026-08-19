// Runs on the audio thread. It must stay cheap for the same reason the
// PortAudio callback in humm2melody/audio.py stays cheap: anything slow here
// causes dropouts, and this thread cannot be allowed to do YIN.
//
// Its whole job is to regroup the 128-sample quanta WebAudio delivers into the
// 512-sample hops the analyser expects, and hand them on.

const HOP = 512; // matches HOP_SIZE in humm2melody/audio.py

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.block = new Float32Array(HOP);
    this.filled = 0;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true; // no input yet; stay alive

    for (let i = 0; i < channel.length; i++) {
      this.block[this.filled++] = channel[i];
      if (this.filled === HOP) {
        // Copy, then transfer the copy: `this.block` is reused immediately.
        const out = this.block.slice();
        this.port.postMessage(out, [out.buffer]);
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor("capture", CaptureProcessor);
