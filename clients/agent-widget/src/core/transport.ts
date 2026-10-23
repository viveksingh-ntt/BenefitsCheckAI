import type { Activity } from '../types';

export type ConnectionStatus =
  | 'idle'
  | 'connecting'
  | 'online'
  | 'reconnecting'
  | 'expiredToken'
  | 'failed'
  | 'ended';

/**
 * A bidirectional activity channel between the widget and the Agent relay.
 * The default implementation is Direct Line; tests and demos inject a mock.
 */
export interface Transport {
  readonly conversationId: string | undefined;
  /** The user id activities are posted as (may be dictated by the token). */
  readonly userId?: string;
  /** Open (or resume) the conversation. Resolves when activities can be posted. */
  connect(options: { userId: string; resumeConversationId?: string }): Promise<void>;
  /** Post an activity; resolves with the id the service assigned. */
  post(activity: Activity): Promise<string>;
  /** Upload a file with an activity (Direct Line /upload). Optional. */
  upload?(file: File, activity: Activity): Promise<string>;
  onActivity(listener: (activity: Activity) => void): () => void;
  onStatus(listener: (status: ConnectionStatus, detail?: string) => void): () => void;
  /** Close the connection. The transport cannot be reused. */
  end(): void;
}

/** Tiny typed emitter shared by transports. */
export class Emitter<T extends unknown[]> {
  private listeners = new Set<(...args: T) => void>();

  on(listener: (...args: T) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit(...args: T): void {
    for (const listener of [...this.listeners]) {
      try {
        listener(...args);
      } catch (err) {
        // A faulty listener must never break the transport loop.
        console.error('[agent-widget] listener error', err);
      }
    }
  }

  clear(): void {
    this.listeners.clear();
  }
}
