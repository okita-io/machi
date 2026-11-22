/** Classic script loaded into an AudioWorklet via a blob URL. Forwards mono float blocks. */
export const PCM_WORKLET_NAME = "machi-pcm";

export const PCM_WORKLET_SOURCE = `
class MachiPcmProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel && channel.length > 0) {
      this.port.postMessage(channel.slice(0));
    }
    return true;
  }
}
registerProcessor("${PCM_WORKLET_NAME}", MachiPcmProcessor);
`;
