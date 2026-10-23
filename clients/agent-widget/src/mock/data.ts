/** Illustrative data for the mock relay. Matches the Care assistant prototype; not real members or providers. */

export const MEMBERS: Record<string, { name: string; firstName: string; plan: string; planRef: string; pcp: string }> = {
  mbr_7f3a: { name: 'Alex Morgan', firstName: 'Alex', plan: 'Harbor HMO', planRef: 'pln_harbor_hmo_2026', pcp: 'Dr. Priya Raman, Harbor Primary Care' },
  mbr_2c91: { name: 'Jordan Lee', firstName: 'Jordan', plan: 'Harbor PPO', planRef: 'pln_harbor_ppo_2026', pcp: 'Dr. Sam Ortiz, Midtown Family Medicine' },
};

export const SERVICES = [
  {
    ref: 'svc_focused_skin_exam',
    name: 'Focused skin exam',
    description: 'One changing mole or specific skin concern. Offered by SoHo Skin and Union Dermatology.',
  },
  {
    ref: 'svc_comprehensive_skin_exam',
    name: 'Comprehensive skin exam',
    description: 'Multiple concerns or a broader exam when clinically indicated. Offered by SoHo Skin.',
  },
];

export const DOCTORS = [
  {
    ref: 'prv_19',
    initials: 'NP',
    name: 'Dr. Nina Patel',
    lastName: 'Patel',
    specialty: 'Dermatologist',
    practice: 'SoHo Skin',
    services: 'Medical skin exams · Changing mole evaluation',
    network: 'In-network · Accepting new patients',
    address: '210 Spring St',
    miles: 0.6,
    offers: ['svc_focused_skin_exam', 'svc_comprehensive_skin_exam'],
  },
  {
    ref: 'prv_42',
    initials: 'DC',
    name: 'Dr. Daniel Chen',
    lastName: 'Chen',
    specialty: 'Dermatologist',
    practice: 'Union Dermatology',
    services: 'Medical skin exams · Changing mole evaluation',
    network: 'In-network · Accepting new patients',
    address: '30 E 14th St',
    miles: 1.3,
    offers: ['svc_focused_skin_exam'],
  },
];

export const SLOTS = [
  { ref: 'slt_1015_1030', label: 'Thu, Oct 15 · 10:30 AM', detail: 'In person · 30 min' },
  { ref: 'slt_1015_1415', label: 'Thu, Oct 15 · 2:15 PM', detail: 'In person · 30 min' },
  { ref: 'slt_1019_0900', label: 'Mon, Oct 19 · 9:00 AM', detail: 'In person · 30 min' },
];

export const DISTANCES = [
  { title: 'Within 1 mile', value: '1' },
  { title: 'Within 5 miles', value: '5' },
  { title: 'Within 10 miles', value: '10' },
  { title: 'Within 25 miles', value: '25' },
];
