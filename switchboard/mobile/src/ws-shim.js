// Stands in for the Node `ws` package in the phone build: wraps the browser
// WebSocket with the small part of ws's API the providers use.
class WS {
  constructor(url) {
    this.sock = new WebSocket(url);
    this.handlers = {};
    for (const ev of ['open', 'message', 'close', 'error']) {
      this.sock.addEventListener(ev, e => {
        const arg = ev === 'message' ? e.data : ev === 'close' ? e.code : e;
        for (const fn of this.handlers[ev] || []) fn(arg);
      });
    }
  }

  on(ev, fn) {
    (this.handlers[ev] ||= []).push(fn);
    return this;
  }

  send(data) {
    this.sock.send(data);
  }

  close(code) {
    // Browsers only accept 1000 or 3000-4999.
    const ok = code === 1000 || (code >= 3000 && code <= 4999);
    try {
      this.sock.close(ok ? code : 1000);
    } catch {}
  }

  get readyState() {
    return this.sock.readyState;
  }
}

WS.OPEN = 1;

module.exports = WS;
