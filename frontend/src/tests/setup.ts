import '@testing-library/jest-dom/vitest'

class MockEventSource {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 2

  readonly url: string
  readyState = MockEventSource.CONNECTING
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null

  constructor(url: string) {
    this.url = url
  }

  close() {
    this.readyState = MockEventSource.CLOSED
  }

  addEventListener() {}
  removeEventListener() {}
  dispatchEvent() {
    return true
  }
}

vi.stubGlobal('EventSource', MockEventSource)
