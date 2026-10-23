/**
 * MockRelayTransport — an in-browser stand-in for Direct Line + the Agent relay.
 *
 * It behaves like the real relay from the widget's point of view: echoes user activities, sends
 * informative/streaming typing updates, Adaptive Card attachments bound from the template
 * catalogue, suggested actions, and navigate / handoff events. Use it for demos, UI tests and
 * design reviews; it never leaves the browser and uses illustrative data only.
 */
import type { Activity, CardAction } from '../types';
import { Emitter, type ConnectionStatus, type Transport } from '../core/transport';
import { ADAPTIVE_CARD_CONTENT_TYPE } from '../cards/renderer';
import { expandTemplate } from './templating';
import { DISTANCES, DOCTORS, MEMBERS, SERVICES, SLOTS } from './data';

import benefitCoverage from '../../templates/benefit-coverage@1.json';
import serviceOptions from '../../templates/service-options@1.json';
import providerResults from '../../templates/provider-results@1.json';
import availabilitySlots from '../../templates/availability-slots@1.json';
import bookingReview from '../../templates/booking-review@1.json';
import referralReview from '../../templates/referral-review@1.json';
import confirmation from '../../templates/confirmation@1.json';

const TEMPLATES: Record<string, unknown> = {
  'benefit-coverage@1': benefitCoverage,
  'service-options@1': serviceOptions,
  'provider-results@1': providerResults,
  'availability-slots@1': availabilitySlots,
  'booking-review@1': bookingReview,
  'referral-review@1': referralReview,
  'confirmation@1': confirmation,
};

export interface MockRelayOptions {
  /** 1 = realistic pacing, 0 = instant (tests). Default 1. */
  speed?: number;
  /** Test hook: reject this many posts of user messages (event activities are not counted). */
  failMessagePosts?: number;
  /** Test hook: reject connect() this many times. Share one counter across factory calls via the same object. */
  failConnects?: { remaining: number };
  /** Test hook: delay connect() by this many ms (for race tests). */
  connectDelayMs?: number;
}

interface ReplyPlan {
  informative?: string;
  lead?: string;
  chip?: string;
  breadcrumb?: string;
  card?: { templateId: string; data: Record<string, unknown> };
  follow?: string;
  suggestions?: CardAction[];
  events?: Array<{ name: string; value: unknown }>;
}

interface RelayState {
  portal: 'member' | 'provider';
  memberRef?: string;
  zip: string;
  distance: string;
  serviceRef: string;
  providerRef?: string;
  slotRef?: string;
}

const chip = (title: string, recommended = false): CardAction => ({
  type: 'imBack',
  title,
  value: title,
  channelData: recommended ? { recommended: true } : undefined,
});

const BOT = { id: 'care-assistant', name: 'Care assistant', role: 'bot' as const };

export class MockRelayTransport implements Transport {
  private readonly activities = new Emitter<[Activity]>();
  private readonly statuses = new Emitter<[ConnectionStatus, string | undefined]>();
  private readonly speed: number;
  private convId: string | undefined;
  private user = '';
  private seq = 0;
  private ended = false;
  private queue: Promise<void> = Promise.resolve();
  private state: RelayState = { portal: 'member', zip: '10012', distance: '5', serviceRef: 'svc_focused_skin_exam' };

  private failMessagePosts: number;

  constructor(private readonly options: MockRelayOptions = {}) {
    this.speed = options.speed ?? 1;
    this.failMessagePosts = options.failMessagePosts ?? 0;
  }

  get conversationId(): string | undefined {
    return this.convId;
  }

  get userId(): string {
    return this.user;
  }

  onActivity(listener: (activity: Activity) => void): () => void {
    return this.activities.on(listener);
  }

  onStatus(listener: (status: ConnectionStatus, detail?: string) => void): () => void {
    return this.statuses.on(listener);
  }

  async connect({ userId }: { userId: string }): Promise<void> {
    this.user = userId;
    this.statuses.emit('connecting', undefined);
    await this.wait(150);
    if (this.options.connectDelayMs) await new Promise((resolve) => setTimeout(resolve, this.options.connectDelayMs));
    if (this.options.failConnects && this.options.failConnects.remaining > 0) {
      this.options.failConnects.remaining -= 1;
      throw new Error('mock: connect failed');
    }
    this.convId = `mock-${Math.random().toString(36).slice(2, 10)}`;
    this.statuses.emit('online', undefined);
  }

  async post(activity: Activity): Promise<string> {
    if (this.ended) throw new Error('Conversation ended');
    if (activity.type === 'message' && this.failMessagePosts > 0) {
      this.failMessagePosts -= 1;
      throw new Error('mock: post failed');
    }
    const id = this.nextId();
    const echoed: Activity = { ...activity, id, timestamp: new Date().toISOString(), from: { ...activity.from, id: this.user } };
    void this.wait(40).then(() => this.emit(echoed));
    this.queue = this.queue.then(() => this.handle(echoed)).catch((err) => console.error('[mock-relay]', err));
    return id;
  }

  async upload(file: File, activity: Activity): Promise<string> {
    const id = await this.post({ ...activity, attachments: [{ contentType: file.type || 'application/octet-stream', name: file.name }] });
    return id;
  }

  end(): void {
    this.ended = true;
    this.statuses.emit('ended', undefined);
    this.activities.clear();
    this.statuses.clear();
  }

  // ================================================================ routing

  private async handle(activity: Activity): Promise<void> {
    if (activity.type === 'event') return this.handleEvent(activity);
    const value = activity.value as Record<string, unknown> | undefined;
    const action = value?.action as { verb?: string; data?: Record<string, unknown> } | undefined;
    if (action?.verb) return this.handleVerb(action.verb, action.data ?? {});
    if (activity.text) return this.handleText(activity.text, (value?.params as Record<string, unknown>) ?? {});
    if (value) return this.handleVerb(String(value.verb ?? 'submit'), value);
  }

  private async handleEvent(activity: Activity): Promise<void> {
    const value = (activity.value ?? {}) as Record<string, unknown>;
    switch (activity.name) {
      case 'context': {
        const member = value.member as { ref?: string } | undefined;
        this.state.portal = value.portal === 'provider' ? 'provider' : 'member';
        this.state.memberRef = member?.ref;
        return;
      }
      case 'startJourney': {
        const params = (value.params ?? {}) as Record<string, unknown>;
        this.applyParams(params);
        const journey = String(value.journeyId ?? '');
        if (journey === 'benefit-check') return this.reply(this.benefitPlan());
        if (journey === 'service-search') return this.reply(this.servicePlan());
        if (journey === 'doctor-search') return this.reply(this.doctorPlan());
        return this.reply({ lead: this.helpText(), suggestions: this.defaultChips() });
      }
      case 'handoffRequest':
        return this.reply({
          informative: 'Creating a hand-off ticket…',
          lead: 'I’ve asked a care specialist to follow up. They’ll see this conversation, so you won’t need to repeat yourself. Typical response time is under 10 minutes during business hours (illustrative).',
          chip: 'Hand-off ticket HO-2741 created',
          events: [{ name: 'handoff', value: { reason: 'user_request', ticketRef: 'HO-2741' } }],
        });
      default:
        return;
    }
  }

  private async handleVerb(verb: string, data: Record<string, unknown>): Promise<void> {
    this.applyParams(data);
    switch (verb) {
      case 'service.find':
        return this.reply(this.servicePlan());
      case 'providers.search':
      case 'providers.back':
        return this.reply(this.doctorPlan());
      case 'appointment.availability':
        return this.reply(this.availabilityPlan());
      case 'appointment.review':
        return this.reply(this.bookingReviewPlan());
      case 'appointment.confirm':
        return this.reply(this.bookingConfirmedPlan());
      case 'referral.review':
        return this.reply(this.referralReviewPlan());
      case 'referral.submit':
        return this.reply(this.referralSubmittedPlan());
      case 'plan.details':
        return this.reply({ events: [{ name: 'navigate', value: { route: '/plan/benefits/dermatology' } }], lead: 'Opening your plan’s dermatology benefits in the portal.' });
      case 'service.details':
        return this.reply({ events: [{ name: 'navigate', value: { route: `/care/services/${this.state.serviceRef}` } }], lead: 'Opening the service details page.' });
      case 'provider.view': {
        const doc = this.doctor();
        return this.reply({ events: [{ name: 'navigate', value: { route: `/providers/${doc.ref}` } }], lead: `Opening ${doc.name}’s profile.` });
      }
      default:
        return this.reply({ lead: this.helpText(), suggestions: this.defaultChips() });
    }
  }

  private async handleText(raw: string, params: Record<string, unknown>): Promise<void> {
    this.applyParams(params);
    const text = raw.toLowerCase();
    const zip = text.match(/\b(\d{5})\b/);
    if (zip) this.state.zip = zip[1];
    const miles = text.match(/within (\d+) miles?/);
    if (miles) this.state.distance = miles[1];
    if (/plan details/.test(text)) return this.handleVerb('plan.details', {});

    if (/hand.?off|human|agent|support|call me/.test(text)) {
      return this.handleEvent({ type: 'event', name: 'handoffRequest', from: { id: this.user } });
    }
    if (/referral rule|need a referral|referral required/.test(text)) {
      return this.reply({
        lead: `On ${this.member().plan}, you need a referral from your primary care doctor before seeing a dermatologist. Referrals usually last 90 days and cover the visits listed on them. Your PCP on file is ${this.member().pcp}.`,
        chip: 'Plan rules checked',
        suggestions: [chip('Find dermatologists', true), chip('Compare copays')],
      });
    }
    if (/compare copay|copays|ask about copay|copay/.test(text)) {
      return this.reply({
        lead: 'Estimated 2026 office copays on your plan:\n\n- **Specialist (dermatology):** $40\n- **Primary care:** $20\n- **Urgent care:** $50\n\nBiopsies or procedures during the visit may cost extra.',
        chip: 'Plan cost shares reviewed',
        suggestions: [chip('Find dermatologists', true), chip('Check referral rules')],
      });
    }
    if (/compare location|location|how far|nearest/.test(text)) {
      const lines = DOCTORS.map((d) => `- **${d.name}**, ${d.practice}: ${d.address}, ${d.miles} miles away`).join('\n');
      return this.reply({ lead: `Both offices are close to ${this.state.zip}:\n\n${lines}`, suggestions: [chip('Find doctors', true), chip('Check benefits')] });
    }
    if (/^view dr|view doctor/.test(text)) return this.handleVerb('provider.view', {});
    if (/availability|appointment|book/.test(text)) return this.reply(this.availabilityPlan());
    if (/covered|coverage|cover|benefit|cost|pay for/.test(text)) return this.reply(this.benefitPlan());
    if (/doctor|dermatologist|provider|in-network|in network/.test(text)) return this.reply(this.doctorPlan());
    if (/skin exam|mole|service|find this/.test(text)) return this.reply(this.servicePlan());
    return this.reply({ lead: this.helpText(), suggestions: this.defaultChips() });
  }

  private applyParams(params: Record<string, unknown>): void {
    if (typeof params.zip === 'string' && /^\d{5}$/.test(params.zip)) this.state.zip = params.zip;
    if (typeof params.distance === 'string') this.state.distance = params.distance;
    if (typeof params.radiusMiles === 'number') this.state.distance = String(params.radiusMiles);
    if (typeof params.serviceRef === 'string' && SERVICES.some((s) => s.ref === params.serviceRef)) this.state.serviceRef = params.serviceRef;
    if (params.serviceCode === 'derm-skin-exam') this.state.serviceRef = 'svc_focused_skin_exam';
    if (typeof params.providerRef === 'string' && DOCTORS.some((d) => d.ref === params.providerRef)) this.state.providerRef = params.providerRef;
    if (typeof params.slotRef === 'string' && SLOTS.some((s) => s.ref === params.slotRef)) this.state.slotRef = params.slotRef;
  }

  // ================================================================ plans (one per prototype screen)

  private member() {
    return MEMBERS[this.state.memberRef ?? ''] ?? { name: 'the member', firstName: 'the member', plan: 'Harbor HMO', planRef: 'pln_harbor_hmo_2026', pcp: 'your primary care doctor' };
  }

  private service() {
    return SERVICES.find((s) => s.ref === this.state.serviceRef) ?? SERVICES[0];
  }

  private doctor() {
    return DOCTORS.find((d) => d.ref === this.state.providerRef) ?? DOCTORS[0];
  }

  private isProvider(): boolean {
    return this.state.portal === 'provider';
  }

  /** Screen 2 — member benefit check. */
  private benefitPlan(): ReplyPlan {
    const m = this.member();
    return {
      informative: 'Checking plan eligibility and benefits…',
      lead: this.isProvider()
        ? `${m.firstName}’s plan covers a medically necessary skin exam in network. Here’s what to expect.`
        : 'Your plan covers a medically necessary skin exam in network. Here’s what to expect.',
      chip: 'Plan eligibility and benefits reviewed',
      breadcrumb: 'Benefit check',
      card: {
        templateId: 'benefit-coverage@1',
        data: {
          service: { name: 'Medical skin exam', category: 'Dermatology', ref: 'svc_focused_skin_exam' },
          plan: { name: m.plan, year: '2026', ref: m.planRef },
          coverage: { label: 'Covered when medically necessary' },
          facts: [
            { title: 'Network', value: 'In-network dermatologist required' },
            { title: 'Visit cost', value: '$40 specialist copay per visit' },
            { title: 'Deductible', value: 'Does not apply to this office visit' },
            { title: 'Referral', value: 'PCP referral required before visit' },
            { title: 'Prior auth', value: 'Not required for the office exam' },
          ],
          notice:
            'Illustrative estimate, not a payment guarantee. Biopsy, lab work and treatment may cost extra. Cosmetic visits are excluded; final coverage depends on eligibility and claim coding.',
        },
      },
      follow: 'You can find this service next. If you need a referral, contact your primary care doctor.',
      suggestions: [chip('Find dermatologists'), chip('Check referral rules'), chip('Compare copays'), chip('View plan details')],
    };
  }

  /** Screen 3 — member service search. */
  private servicePlan(): ReplyPlan {
    return {
      informative: 'Matching services to your plan…',
      lead: 'A focused skin exam matches your request. Choose an option to find an in-network dermatologist.',
      chip: 'Service options matched to your plan',
      breadcrumb: 'Service search',
      card: {
        templateId: 'service-options@1',
        data: {
          title: 'Medical skin exam options',
          subtitle: `Dermatology · In person · Near ${this.state.zip}`,
          zip: this.state.zip,
          distance: this.state.distance,
          distanceOptions: DISTANCES,
          services: SERVICES,
          selected: this.state.serviceRef,
          notice: 'Covered office exam: estimated $40 copay. PCP referral required. Cosmetic screening is excluded; procedures may cost extra.',
        },
      },
      follow: `${this.service().name} is selected. Find doctors to compare nearby options; nothing is booked.`,
      suggestions: [chip('Check benefits', true), chip('Find doctors', true), chip('Compare locations'), chip('Ask about copay')],
    };
  }

  /** Screens 1 and 4 — doctor search (provider: review referral; member: check availability). */
  private doctorPlan(): ReplyPlan {
    const radius = Number(this.state.distance) || 5;
    const doctors = DOCTORS.filter((d) => d.miles <= radius && d.offers.includes(this.state.serviceRef)).map((d) => ({
      ...d,
      distanceText: `${d.miles} miles away`,
    }));
    const m = this.member();
    const provider = this.isProvider();
    const serviceName = this.service().name.toLowerCase();
    if (!doctors.length) {
      return {
        informative: 'Searching in-network doctors…',
        lead: `I couldn’t find an in-network dermatologist offering a ${serviceName} within ${radius} miles of ${this.state.zip}. Try a wider distance.`,
        breadcrumb: 'Doctor search',
        suggestions: [chip('Find doctors within 10 miles', true), chip('Check benefits')],
      };
    }
    this.state.providerRef = doctors[0].ref;
    const first = doctors[0];
    return {
      informative: provider ? 'Matching the member’s plan network…' : 'Searching in-network doctors…',
      lead: provider
        ? `These doctors match ${m.firstName}’s plan and service. Select one to review a referral or view practice details.`
        : `These dermatologists offer ${serviceName}s. Select a doctor to view details or check availability.`,
      chip: provider ? 'Member network and service matched' : 'Service and plan network matched',
      breadcrumb: 'Doctor search',
      card: {
        templateId: 'provider-results@1',
        data: {
          title: `Doctors for a ${serviceName}`,
          doctors,
          plan: m.plan,
          radius,
          zip: this.state.zip,
          selected: first.ref,
          audience: provider ? 'provider' : 'member',
          serviceRef: this.state.serviceRef,
          notice: 'PCP referral required. Network listing is illustrative; verify with the office. No appointment or referral has been created.',
        },
      },
      follow: provider
        ? `Dr. ${first.lastName} is selected for ${m.firstName}. Review referral prepares details for approval; nothing is sent until you confirm.`
        : `Dr. ${first.lastName} is selected. You’ll review any appointment details before confirming a booking.`,
      suggestions: provider
        ? [chip('Check benefits', true), chip('Compare locations'), chip(`View Dr. ${first.lastName}`)]
        : [chip('Check benefits', true), chip('Find dermatologists'), chip(`View Dr. ${first.lastName}`), chip('Check availability')],
    };
  }

  private availabilityPlan(): ReplyPlan {
    const doc = this.doctor();
    this.state.slotRef = SLOTS[0].ref;
    return {
      informative: `Checking ${doc.practice} availability…`,
      lead: `${doc.name} has these open times for a ${this.service().name.toLowerCase()}. Pick one to review; nothing is booked yet.`,
      chip: 'Live availability checked',
      breadcrumb: 'Appointment',
      card: {
        templateId: 'availability-slots@1',
        data: {
          doctor: { name: doc.name, practice: doc.practice, ref: doc.ref },
          service: this.service().name,
          slots: SLOTS.map((s) => ({ ...s, detail: `${s.detail} · ${doc.address}` })),
          selected: SLOTS[0].ref,
          notice: 'Times are illustrative and can change. Choosing a time does not book it.',
        },
      },
      suggestions: [chip('Compare copays'), chip('Check referral rules')],
    };
  }

  private bookingReviewPlan(): ReplyPlan {
    const doc = this.doctor();
    const slot = SLOTS.find((s) => s.ref === this.state.slotRef) ?? SLOTS[0];
    const m = this.member();
    return {
      lead: 'Here’s your request. Check the details, then confirm.',
      breadcrumb: 'Appointment review',
      card: {
        templateId: 'booking-review@1',
        data: {
          providerRef: doc.ref,
          slotRef: slot.ref,
          facts: [
            { title: 'Patient', value: m.name },
            { title: 'Doctor', value: `${doc.name}, ${doc.practice}` },
            { title: 'When', value: slot.label },
            { title: 'Where', value: `${doc.address} (in person)` },
            { title: 'Visit cost', value: '$40 specialist copay (estimate)' },
            { title: 'Referral', value: 'PCP referral needed before the visit' },
          ],
          notice: 'Nothing is booked until you confirm. You can cancel from Appointments in the portal.',
        },
      },
    };
  }

  private bookingConfirmedPlan(): ReplyPlan {
    const doc = this.doctor();
    const slot = SLOTS.find((s) => s.ref === this.state.slotRef) ?? SLOTS[0];
    return {
      informative: 'Sending your request to the office…',
      lead: `Your request is in. ${doc.practice} will confirm by message within one business day.`,
      chip: 'Appointment request sent',
      breadcrumb: 'Appointment',
      card: {
        templateId: 'confirmation@1',
        data: {
          status: 'Request sent (illustrative)',
          title: `${doc.name} · ${slot.label}`,
          facts: [
            { title: 'Request ref', value: 'APT-58213' },
            { title: 'Location', value: `${doc.practice}, ${doc.address}` },
            { title: 'Before you go', value: 'Ask your PCP for a dermatology referral' },
          ],
          notice: 'Demo only: no real appointment was requested.',
        },
      },
      suggestions: [chip('Check referral rules', true), chip('Compare copays')],
    };
  }

  private referralReviewPlan(): ReplyPlan {
    const doc = this.doctor();
    const m = this.member();
    return {
      informative: 'Preparing the referral…',
      lead: `I’ve drafted the referral for ${m.firstName}. Review it and submit when ready.`,
      breadcrumb: 'Referral review',
      card: {
        templateId: 'referral-review@1',
        data: {
          memberName: m.name,
          providerRef: doc.ref,
          serviceRef: this.state.serviceRef,
          facts: [
            { title: 'Member', value: `${m.name} · ${m.plan}` },
            { title: 'Refer to', value: `${doc.name}, Dermatology, ${doc.practice}` },
            { title: 'Service', value: `${this.service().name} (changing mole evaluation)` },
            { title: 'Visits', value: '1 office visit' },
            { title: 'Valid for', value: '90 days from approval' },
          ],
          notice: 'Nothing is sent until you submit. Submission is logged with your provider ID for audit.',
        },
      },
    };
  }

  private referralSubmittedPlan(): ReplyPlan {
    const doc = this.doctor();
    const m = this.member();
    return {
      informative: 'Submitting the referral…',
      lead: `Referral submitted. ${doc.practice} and ${m.firstName} will be notified.`,
      chip: 'Referral submitted',
      breadcrumb: 'Referral',
      card: {
        templateId: 'confirmation@1',
        data: {
          status: 'Submitted (illustrative)',
          title: `Referral to ${doc.name}`,
          facts: [
            { title: 'Referral ref', value: 'RF-20261013-0042' },
            { title: 'Member', value: m.name },
            { title: 'Valid until', value: 'Jan 11, 2027' },
          ],
          notice: 'Demo only: no real referral was created.',
        },
      },
      suggestions: [chip('Check benefits'), chip('Compare locations')],
    };
  }

  private helpText(): string {
    return this.isProvider()
      ? 'I can check a member’s benefits, find in-network specialists and prepare referrals for your review. What do you need?'
      : 'I can check what your plan covers, find in-network care near you and help you request an appointment. What would you like to do?';
  }

  private defaultChips(): CardAction[] {
    return [chip('Is a skin exam covered?', true), chip('Find a dermatologist'), chip('Compare copays')];
  }

  // ================================================================ emitting

  private async reply(plan: ReplyPlan): Promise<void> {
    if (plan.informative) {
      this.emit({ type: 'typing', from: BOT, text: plan.informative, entities: [{ type: 'streaminfo', streamType: 'informative', streamSequence: 1 }] });
      await this.wait(700);
    }
    for (const event of plan.events ?? []) this.emit({ type: 'event', from: BOT, name: event.name, value: event.value });

    const hasMore = Boolean(plan.card || plan.follow);
    if (plan.lead) {
      const streamId = this.nextId();
      const words = plan.lead.split(/(\s+)/);
      let text = '';
      let sequence = 1;
      for (let i = 0; i < words.length; i += 6) {
        text += words.slice(i, i + 6).join('');
        sequence += 1;
        this.emit({
          type: 'typing',
          id: i === 0 ? streamId : this.nextId(),
          from: BOT,
          text,
          entities: [{ type: 'streaminfo', streamType: 'streaming', streamId, streamSequence: sequence }],
        });
        await this.wait(45);
      }
      this.emit({
        type: 'message',
        id: this.nextId(),
        from: BOT,
        text: plan.lead,
        textFormat: 'markdown',
        entities: [{ type: 'streaminfo', streamType: 'final', streamId }],
        channelData: { resultChip: plan.chip ? { text: plan.chip, state: 'done' } : undefined, breadcrumb: plan.breadcrumb },
        suggestedActions: hasMore ? undefined : plan.suggestions && { actions: plan.suggestions },
      });
      await this.wait(250);
    }
    if (plan.card) {
      const template = TEMPLATES[plan.card.templateId];
      this.emit({
        type: 'message',
        id: this.nextId(),
        from: BOT,
        attachments: [{ contentType: ADAPTIVE_CARD_CONTENT_TYPE, content: expandTemplate(template, plan.card.data) }],
        channelData: { templateId: plan.card.templateId, breadcrumb: plan.breadcrumb },
        suggestedActions: plan.follow ? undefined : plan.suggestions && { actions: plan.suggestions },
      });
      await this.wait(350);
    }
    if (plan.follow) {
      this.emit({
        type: 'message',
        id: this.nextId(),
        from: BOT,
        text: plan.follow,
        textFormat: 'markdown',
        suggestedActions: plan.suggestions && { actions: plan.suggestions },
      });
    }
  }

  private emit(activity: Activity): void {
    if (this.ended) return;
    this.activities.emit({
      conversation: this.convId ? { id: this.convId } : undefined,
      timestamp: new Date().toISOString(),
      ...activity,
      id: activity.id ?? this.nextId(),
    });
  }

  private nextId(): string {
    this.seq += 1;
    return `${this.convId ?? 'mock'}|${String(this.seq).padStart(7, '0')}`;
  }

  private wait(ms: number): Promise<void> {
    const delay = ms * this.speed;
    return delay > 0 ? new Promise((resolve) => setTimeout(resolve, delay)) : Promise.resolve();
  }
}
