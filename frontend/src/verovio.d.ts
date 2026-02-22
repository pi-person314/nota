declare module 'verovio/wasm' {
  const createVerovioModule: () => Promise<any>
  export default createVerovioModule
}

declare module 'verovio/esm' {
  export class VerovioToolkit {
    constructor(module: any)
    loadData(data: string): boolean
    renderToSVG(page?: number): string
    getPageCount(): number
    setOptions(options: Record<string, unknown>): void
    getOptions(): Record<string, unknown>
  }
}
