declare module 'verovio/wasm' {
  type VerovioModule = Record<string, unknown>
  const createVerovioModule: () => Promise<VerovioModule>
  export default createVerovioModule
}

declare module 'verovio/esm' {
  export class VerovioToolkit {
    constructor(module: Record<string, unknown>)
    loadData(data: string): boolean
    loadZipDataBuffer(data: ArrayBuffer): boolean
    renderToSVG(page?: number): string
    getPageCount(): number
    setOptions(options: Record<string, unknown>): void
    getOptions(): Record<string, unknown>
  }
}
