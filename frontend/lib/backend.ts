import { BACKEND_WS, type ClientMessage, type ServerMessage } from "./contract";

type Handler = (msg: ServerMessage) => void;

/** Typed WebSocket client with auto-reconnect. Messages sent while disconnected are dropped
 *  (frames are disposable; the next one will follow shortly). */
export class BackendClient {
  private ws: WebSocket | null = null;
  private handlers = new Set<Handler>();
  private closed = false;
  private retryMs = 500;
  onConnection?: (connected: boolean) => void;

  constructor(private url = BACKEND_WS) {}

  connect() {
    this.closed = false;
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onopen = () => {
      this.retryMs = 500;
      this.onConnection?.(true);
    };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data) as ServerMessage;
      this.handlers.forEach((h) => h(msg));
    };
    ws.onclose = () => {
      this.onConnection?.(false);
      if (this.closed) return;
      setTimeout(() => this.connect(), this.retryMs);
      this.retryMs = Math.min(this.retryMs * 2, 5000);
    };
  }

  get connected() {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  send(msg: ClientMessage) {
    if (this.connected) this.ws!.send(JSON.stringify(msg));
  }

  subscribe(h: Handler) {
    this.handlers.add(h);
    return () => {
      this.handlers.delete(h);
    };
  }

  close() {
    this.closed = true;
    this.ws?.close();
  }
}
