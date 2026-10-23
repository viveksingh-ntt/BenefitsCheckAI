import type { Activity, Attachment, CardAction, RelayChannelData, StreamInfoEntity } from '../types';

export interface UserItem {
  kind: 'user';
  /** Stable render key (the client id for messages sent from this widget). */
  id: string;
  clientId?: string;
  /** Id the service assigned, once known. */
  serverId?: string;
  text?: string;
  attachmentNames?: string[];
  status: 'sending' | 'sent' | 'failed';
  timestamp: number;
  rev: number;
}

export interface BotItem {
  kind: 'bot';
  /** Stable render key (a streamed message keeps its stream key after the final activity arrives). */
  id: string;
  /** The service's activity id (use for replyToId / feedback). Undefined for local messages. */
  activityId?: string;
  text?: string;
  textFormat?: 'markdown' | 'plain' | 'xml';
  attachments: Attachment[];
  resultChip?: RelayChannelData['resultChip'];
  templateId?: string;
  streaming: boolean;
  timestamp: number;
  replyToId?: string;
  feedback?: 'up' | 'down';
  rev: number;
}

export type ChatItem = UserItem | BotItem;

export interface ConversationState {
  items: ChatItem[];
  suggestions: CardAction[];
  /** Agent is working: typing dots, optionally with informative text. */
  progress: { active: boolean; text?: string };
  breadcrumb?: string;
}

type Listener = (state: ConversationState) => void;

const getStreamInfo = (activity: Activity): StreamInfoEntity | undefined =>
  activity.entities?.find((e): e is StreamInfoEntity => e.type === 'streaminfo');

const toTime = (iso?: string): number => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(t) ? t : Date.now();
};

/**
 * Turns the raw activity stream into render-ready chat items.
 * Handles: user echo de-duplication, Agents SDK streaming (informative / streaming / final),
 * suggested actions, result chips and breadcrumb updates.
 */
export class ConversationStore {
  private state: ConversationState = { items: [], suggestions: [], progress: { active: false } };
  private listeners = new Set<Listener>();
  private revCounter = 0;
  /** streamId → item id */
  private streams = new Map<string, string>();

  constructor(private readonly isSelf: (activity: Activity) => boolean) {}

  get snapshot(): ConversationState {
    return this.state;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  reset(): void {
    this.state = { items: [], suggestions: [], progress: { active: false } };
    this.streams.clear();
    this.notify();
  }

  addLocalUser(clientId: string, text: string | undefined, attachmentNames?: string[]): void {
    this.state.items = [
      ...this.state.items,
      { kind: 'user', id: clientId, clientId, text, attachmentNames, status: 'sending', timestamp: Date.now(), rev: this.nextRev() },
    ];
    this.state.suggestions = [];
    this.notify();
  }

  /** Show a local bot message (e.g. welcome) that never went over the wire. */
  addLocalBot(text: string, suggestions: CardAction[] = []): void {
    this.state.items = [
      ...this.state.items,
      { kind: 'bot', id: `local-${this.nextRev()}`, text, textFormat: 'markdown', attachments: [], streaming: false, timestamp: Date.now(), rev: this.nextRev() },
    ];
    this.state.suggestions = suggestions;
    this.notify();
  }

  markSent(clientId: string, serverId: string): void {
    this.updateUser(clientId, (item) => (item.status === 'sent' && item.serverId ? item : { ...item, serverId: item.serverId ?? serverId, status: 'sent' }));
  }

  markSending(clientId: string): void {
    this.updateUser(clientId, (item) => (item.status === 'sending' ? item : { ...item, status: 'sending' }));
  }

  markFailed(clientId: string): void {
    this.updateUser(clientId, (item) => (item.status === 'failed' ? item : { ...item, status: 'failed' }));
  }

  /** Show the agent as working (used right after the widget posts something the relay will answer). */
  setWorking(): void {
    if (this.state.progress.active) return;
    this.state.progress = { active: true };
    this.notify();
  }

  /** Clear a progress indicator that never got an answer (relay dropped the turn). */
  clearProgress(): void {
    if (!this.state.progress.active) return;
    this.state.progress = { active: false };
    this.notify();
  }

  setFeedback(itemId: string, feedback: 'up' | 'down'): void {
    this.state.items = this.state.items.map((item) =>
      item.kind === 'bot' && item.id === itemId ? { ...item, feedback, rev: this.nextRev() } : item,
    );
    this.notify();
  }

  apply(activity: Activity): void {
    if (this.isSelf(activity)) {
      this.applyEcho(activity);
      return;
    }
    if (activity.type === 'typing') {
      this.applyTyping(activity);
      return;
    }
    if (activity.type === 'message') {
      this.applyBotMessage(activity);
    }
  }

  // -------------------------------------------------------------------------

  private applyEcho(activity: Activity): void {
    const clientId = activity.channelData?.clientActivityId as string | undefined;
    const existing = this.state.items.find(
      (item) => item.kind === 'user' && ((clientId && item.clientId === clientId) || (activity.id && (item.serverId === activity.id || item.id === activity.id))),
    );
    if (existing) {
      if (clientId && activity.id) this.markSent(clientId, activity.id);
      return;
    }
    // Activity from a resumed conversation: show it if it carried visible text.
    if (activity.type === 'message' && activity.text) {
      this.state.items = [
        ...this.state.items,
        { kind: 'user', id: activity.id ?? `u-${this.nextRev()}`, serverId: activity.id, text: activity.text, status: 'sent', timestamp: toTime(activity.timestamp), rev: this.nextRev() },
      ];
      this.notify();
    }
  }

  private applyTyping(activity: Activity): void {
    const info = getStreamInfo(activity);
    if (info?.streamType === 'streaming') {
      const streamId = info.streamId ?? activity.id ?? 'stream';
      const itemId = this.streams.get(streamId);
      if (itemId) {
        this.state.items = this.state.items.map((item) =>
          item.kind === 'bot' && item.id === itemId ? { ...item, text: activity.text ?? item.text, rev: this.nextRev() } : item,
        );
      } else {
        const id = `stream-${streamId}`;
        this.streams.set(streamId, id);
        this.state.items = [
          ...this.state.items,
          { kind: 'bot', id, text: activity.text, textFormat: 'markdown', attachments: [], streaming: true, timestamp: toTime(activity.timestamp), rev: this.nextRev() },
        ];
      }
      this.state.progress = { active: false };
    } else if (info?.streamType === 'informative') {
      this.state.progress = { active: true, text: activity.text };
    } else {
      this.state.progress = { active: true, text: this.state.progress.text };
    }
    this.notify();
  }

  private applyBotMessage(activity: Activity): void {
    const info = getStreamInfo(activity);
    const channelData = activity.channelData ?? {};
    const next: BotItem = {
      kind: 'bot',
      id: activity.id ?? `b-${this.nextRev()}`,
      activityId: activity.id,
      text: activity.text,
      textFormat: activity.textFormat ?? 'markdown',
      attachments: activity.attachments ?? [],
      resultChip: channelData.resultChip,
      templateId: channelData.templateId,
      streaming: false,
      timestamp: toTime(activity.timestamp),
      replyToId: activity.replyToId,
      rev: this.nextRev(),
    };

    const streamId = info?.streamType === 'final' ? (info.streamId ?? undefined) : undefined;
    const streamedItemId = streamId ? this.streams.get(streamId) : undefined;
    if (streamedItemId) {
      this.state.items = this.state.items.map((item) => (item.id === streamedItemId ? { ...next, id: streamedItemId } : item));
      this.streams.delete(streamId!);
    } else if (this.state.items.some((item) => item.id === next.id || (item.kind === 'bot' && next.activityId && item.activityId === next.activityId))) {
      return; // duplicate delivery (reconnect replay)
    } else {
      this.state.items = [...this.state.items, next];
    }

    this.state.progress = { active: false };
    this.state.suggestions = activity.suggestedActions?.actions ?? [];
    if (channelData.breadcrumb) this.state.breadcrumb = channelData.breadcrumb;
    this.notify();
  }

  /** Applies an update to one user item; no-op (no re-render) when the update returns the same item. */
  private updateUser(clientId: string, update: (item: UserItem) => UserItem): void {
    let changed = false;
    this.state.items = this.state.items.map((item) => {
      if (item.kind !== 'user' || item.clientId !== clientId) return item;
      const next = update(item);
      if (next === item) return item;
      changed = true;
      return { ...next, rev: this.nextRev() };
    });
    if (changed) this.notify();
  }

  private nextRev(): number {
    this.revCounter += 1;
    return this.revCounter;
  }

  private notify(): void {
    this.state = { ...this.state };
    for (const listener of [...this.listeners]) listener(this.state);
  }
}
