// A from-scratch implementation of the openWakeWord inference pipeline on top
// of onnxruntime-web. openWakeWord (https://github.com/dscripka/openWakeWord)
// detects a wake phrase with three chained ONNX models rather than one
// end-to-end network:
//
//   raw audio -> melspectrogram model -> embedding model -> keyword model -> score
//
// Each stage consumes a sliding window of the previous stage's output and
// advances by a stride smaller than that window, so the three buffers below
// (samples, mel frames, embeddings) all trail behind real time by a small,
// fixed amount. None of this needs a server or an account — the three
// `.onnx` files are plain static assets loaded from the public directory.
import * as ort from 'onnxruntime-web/wasm'
import ortWasmBinaryUrl from 'onnxruntime-web/ort-wasm-simd-threaded.wasm?url'
import ortWasmModuleUrl from 'onnxruntime-web/ort-wasm-simd-threaded.mjs?url'

// Self-host the wasm runtime instead of letting onnxruntime-web reach for a
// CDN. Threading is disabled — a single worker-free wasm instance is plenty
// fast for a model this small (a few ms per 80ms audio chunk), and skipping
// threads means we don't need the page to be crossOriginIsolated.
ort.env.wasm.numThreads = 1
ort.env.wasm.wasmPaths = { wasm: ortWasmBinaryUrl, mjs: ortWasmModuleUrl }

// Reference values from the openWakeWord models themselves (see
// https://github.com/dscripka/openWakeWord). These are the fallback used
// when a model's own metadata doesn't pin the dimension down (e.g. it's
// reported as a symbolic/dynamic axis) — actual values are read from each
// session at load time wherever the model exposes them, below.
const SAMPLES_PER_CHUNK = 1280 // 80ms of 16kHz audio
const DEFAULT_MEL_BINS = 32
const DEFAULT_EMBEDDING_WINDOW = 76 // mel frames consumed per embedding
const EMBEDDING_STRIDE = 8 // mel frames dropped after each embedding
const DEFAULT_EMBEDDING_SIZE = 96
const DEFAULT_KEYWORD_WINDOW = 16 // embeddings consumed per keyword score
const REFRACTORY_MS = 2000 // minimum gap between two detections

// How often, at most, the peak score is reported while diagnostics are on.
const DEBUG_REPORT_MS = 1000

// Diagnostics are opt-in per browser rather than build-time, so a
// deployed instance can be investigated without rebuilding it: run
// localStorage.setItem('nota-wakeword-debug', '1') in the console and
// reload. Without the peak score there is no way to tell a wake-word
// model that scores just under the threshold (tune it) from one that
// never responds to the phrase at all (retrain it).
function debugEnabled(): boolean {
  try {
    return localStorage.getItem('nota-wakeword-debug') === '1'
  } catch {
    return false
  }
}

export interface WakeWordEngineConfig {
  melspectrogramModelPath: string
  embeddingModelPath: string
  keywordModelPath: string
  // Detection threshold in (0, 1]; the keyword model's sigmoid score must
  // meet or exceed this to count as a wake.
  threshold: number
}

// Reads a numeric dimension out of an ONNX shape descriptor, where each
// entry is either a fixed number or a symbolic name (e.g. "batch_size") for
// a dynamic axis. Falls back to `fallback` when the axis isn't fixed so a
// model built with dynamic shapes doesn't crash the pipeline.
function fixedDim(shape: readonly (number | string)[] | undefined, index: number, fallback: number): number {
  const value = shape?.[index]
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback
}

// Implements the `PvEngine` shape that `@picovoice/web-voice-processor`
// expects from anything passed to `WebVoiceProcessor.subscribe`. Defining
// only `onmessage` (and not `postMessage`) matters: WebVoiceProcessor awaits
// `onmessage` before delivering the next frame, which is what serializes our
// (async, onnxruntime-backed) processing against the incoming audio stream.
// A `postMessage`-shaped engine would instead be fired-and-forgotten, and
// frames could pile up faster than we can run inference on them.
export class WakeWordEngine {
  private readonly melSession: ort.InferenceSession
  private readonly embeddingSession: ort.InferenceSession
  private readonly keywordSession: ort.InferenceSession

  private readonly melInputName: string
  private readonly melOutputName: string
  private readonly embeddingInputName: string
  private readonly embeddingOutputName: string
  private readonly keywordInputName: string
  private readonly keywordOutputName: string

  private readonly melBins: number
  private readonly embeddingWindow: number
  private readonly embeddingSize: number
  private readonly keywordWindow: number
  private readonly threshold: number
  private readonly onDetect: () => void

  // Samples still waiting to fill out a full 80ms chunk.
  private pendingSamples: number[] = []
  // Rolling buffer of mel frames (each `melBins` floats) awaiting an
  // embedding pass.
  private melFrames: Float32Array[] = []
  // Rolling buffer of embeddings (each `embeddingSize` floats) awaiting a
  // keyword pass.
  private embeddings: Float32Array[] = []
  private lastDetectionAt = 0
  private readonly debug = debugEnabled()
  private peakScore = 0
  private lastDebugReportAt = 0

  private constructor(
    melSession: ort.InferenceSession,
    embeddingSession: ort.InferenceSession,
    keywordSession: ort.InferenceSession,
    threshold: number,
    onDetect: () => void,
  ) {
    this.melSession = melSession
    this.embeddingSession = embeddingSession
    this.keywordSession = keywordSession
    this.threshold = threshold
    this.onDetect = onDetect

    this.melInputName = melSession.inputNames[0]
    this.melOutputName = melSession.outputNames[0]
    this.embeddingInputName = embeddingSession.inputNames[0]
    this.embeddingOutputName = embeddingSession.outputNames[0]
    this.keywordInputName = keywordSession.inputNames[0]
    this.keywordOutputName = keywordSession.outputNames[0]

    // The embedding model's input is shaped [batch, window, bins, 1] and the
    // keyword model's is [batch, window, embeddingSize] — pull the window
    // and feature sizes from whichever model reports them concretely rather
    // than assuming the openWakeWord reference values always hold.
    const embeddingInputShape = embeddingSession.inputMetadata[0]?.isTensor
      ? embeddingSession.inputMetadata[0].shape
      : undefined
    this.embeddingWindow = fixedDim(embeddingInputShape, 1, DEFAULT_EMBEDDING_WINDOW)
    this.melBins = fixedDim(embeddingInputShape, 2, DEFAULT_MEL_BINS)

    const keywordInputShape = keywordSession.inputMetadata[0]?.isTensor
      ? keywordSession.inputMetadata[0].shape
      : undefined
    this.keywordWindow = fixedDim(keywordInputShape, 1, DEFAULT_KEYWORD_WINDOW)
    this.embeddingSize = fixedDim(keywordInputShape, 2, DEFAULT_EMBEDDING_SIZE)
  }

  static async create(config: WakeWordEngineConfig, onDetect: () => void): Promise<WakeWordEngine> {
    const [melSession, embeddingSession, keywordSession] = await Promise.all([
      ort.InferenceSession.create(config.melspectrogramModelPath),
      ort.InferenceSession.create(config.embeddingModelPath),
      ort.InferenceSession.create(config.keywordModelPath),
    ])
    return new WakeWordEngine(melSession, embeddingSession, keywordSession, config.threshold, onDetect)
  }

  // Clears every buffer and the refractory timer. Called each time listening
  // (re)starts so audio processed before the mic was armed — or before a
  // previous detection's refractory window — can't contribute to a new one.
  reset(): void {
    this.pendingSamples = []
    this.melFrames = []
    this.embeddings = []
    this.lastDetectionAt = 0
  }

  async release(): Promise<void> {
    await Promise.all([this.melSession.release(), this.embeddingSession.release(), this.keywordSession.release()])
  }

  // `PvEngine` entry point: WebVoiceProcessor calls this with a
  // `{command: 'process', inputFrame}` payload for every downsampled audio
  // frame (Int16Array PCM at 16kHz, 512 samples by default).
  onmessage = async (event: MessageEvent<{ command?: string; inputFrame?: Int16Array }>): Promise<void> => {
    if (event.data?.command !== 'process' || !event.data.inputFrame) return

    for (let i = 0; i < event.data.inputFrame.length; i++) {
      this.pendingSamples.push(event.data.inputFrame[i])
    }

    while (this.pendingSamples.length >= SAMPLES_PER_CHUNK) {
      const chunk = this.pendingSamples.splice(0, SAMPLES_PER_CHUNK)
      await this.processChunk(chunk)
    }
  }

  private async processChunk(chunk: number[]): Promise<void> {
    // openWakeWord's melspectrogram model is trained on raw int16-range
    // samples, not samples normalized to [-1, 1] — only the dtype changes
    // to float32, not the scale.
    const input = new ort.Tensor('float32', Float32Array.from(chunk), [1, SAMPLES_PER_CHUNK])
    const result = await this.melSession.run({ [this.melInputName]: input })
    const output = result[this.melOutputName]
    const data = output.data as Float32Array
    const dims = output.dims
    const bins = dims[dims.length - 1]
    const frames = dims[dims.length - 2]

    for (let f = 0; f < frames; f++) {
      const frame = new Float32Array(bins)
      for (let b = 0; b < bins; b++) {
        // openWakeWord's fixed rescaling of the raw melspectrogram output
        // into the range the embedding model was trained on.
        frame[b] = data[f * bins + b] / 10 + 2
      }
      this.melFrames.push(frame)
    }

    while (this.melFrames.length >= this.embeddingWindow) {
      await this.runEmbedding()
    }
  }

  private async runEmbedding(): Promise<void> {
    const window = this.melFrames.slice(0, this.embeddingWindow)
    const flat = new Float32Array(this.embeddingWindow * this.melBins)
    window.forEach((frame, i) => flat.set(frame, i * this.melBins))

    const input = new ort.Tensor('float32', flat, [1, this.embeddingWindow, this.melBins, 1])
    const result = await this.embeddingSession.run({ [this.embeddingInputName]: input })
    const embedding = Float32Array.from(result[this.embeddingOutputName].data as Float32Array)
    this.embeddings.push(embedding)

    this.melFrames.splice(0, EMBEDDING_STRIDE)

    while (this.embeddings.length >= this.keywordWindow) {
      await this.runKeyword()
    }
  }

  private async runKeyword(): Promise<void> {
    const window = this.embeddings.slice(0, this.keywordWindow)
    const flat = new Float32Array(this.keywordWindow * this.embeddingSize)
    window.forEach((embedding, i) => flat.set(embedding, i * this.embeddingSize))

    const input = new ort.Tensor('float32', flat, [1, this.keywordWindow, this.embeddingSize])
    const result = await this.keywordSession.run({ [this.keywordInputName]: input })
    const score = (result[this.keywordOutputName].data as Float32Array)[0]

    // Stride 1: the keyword model re-scores on every new embedding once the
    // window first fills, so only the oldest embedding is dropped.
    this.embeddings.shift()

    const now = Date.now()

    if (this.debug) {
      this.peakScore = Math.max(this.peakScore, score)
      if (now - this.lastDebugReportAt >= DEBUG_REPORT_MS) {
        this.lastDebugReportAt = now
        console.info(
          `[nota wake word] peak score ${this.peakScore.toFixed(3)} (fires at ${this.threshold})`,
        )
        this.peakScore = 0
      }
    }

    if (score >= this.threshold && now - this.lastDetectionAt >= REFRACTORY_MS) {
      this.lastDetectionAt = now
      this.onDetect()
    }
  }
}
