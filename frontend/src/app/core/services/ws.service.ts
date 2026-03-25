import { Injectable, OnDestroy } from '@angular/core';

/**
 * Manages WebSocket connections through proxy-relative paths (/ws/...).
 * The Angular dev proxy upgrades ws:// connections to the backend service.
 * Components must never construct WebSocket URLs directly.
 */
@Injectable({ providedIn: 'root' })
export class WsService implements OnDestroy {
  private readonly basePath = '/ws';
  private readonly sockets = new Map<string, WebSocket>();

  connect(path: string): WebSocket {
    const existing = this.sockets.get(path);
    if (existing && existing.readyState < WebSocket.CLOSING) {
      return existing;
    }
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${location.host}${this.basePath}${path}`;
    const socket = new WebSocket(url);
    this.sockets.set(path, socket);
    return socket;
  }

  disconnect(path: string): void {
    const socket = this.sockets.get(path);
    if (socket) {
      socket.close();
      this.sockets.delete(path);
    }
  }

  ngOnDestroy(): void {
    this.sockets.forEach((socket) => socket.close());
    this.sockets.clear();
  }
}
