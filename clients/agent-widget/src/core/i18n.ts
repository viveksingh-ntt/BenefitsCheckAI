export interface Strings {
  title: string;
  tagline: string;
  placeholder: string;
  disclaimer: string;
  support: string;
  launcher: string;
  close: string;
  send: string;
  attach: string;
  nextSteps: string;
  member: string;
  provider: string;
  yourPlan: string;
  selectedMember: string;
  idEnding: string;
  illustrative: string;
  today: string;
  working: string;
  sending: string;
  failed: string;
  retry: string;
  reconnecting: string;
  offline: string;
  sessionExpired: string;
  helpful: string;
  notHelpful: string;
  thanks: string;
  cardSubmitted: string;
  newMessage: string;
  required: string;
  fileTooLarge: string;
  remove: string;
}

const enUS: Strings = {
  title: 'Care assistant',
  tagline: 'AI-powered · Here to help',
  placeholder: 'Ask a question or add a detail…',
  disclaimer: 'AI can make mistakes. Review before confirming.',
  support: 'Get support',
  launcher: 'Open care assistant',
  close: 'Close assistant',
  send: 'Send',
  attach: 'Attach a file',
  nextSteps: 'Next steps',
  member: 'Member',
  provider: 'Provider',
  yourPlan: 'Your plan',
  selectedMember: 'Selected member',
  idEnding: 'ID ending',
  illustrative: 'Illustrative data',
  today: 'Today',
  working: 'Working on it…',
  sending: 'Sending…',
  failed: 'Not sent.',
  retry: 'Retry',
  reconnecting: 'Reconnecting…',
  offline: 'Can’t reach the assistant right now.',
  sessionExpired: 'Your session expired. Refresh the page to continue.',
  helpful: 'Helpful',
  notHelpful: 'Not helpful',
  thanks: 'Thanks for the feedback',
  cardSubmitted: 'Submitted',
  newMessage: 'New message from the assistant',
  required: 'This field is required.',
  fileTooLarge: 'Files must be 10 MB or smaller.',
  remove: 'Remove',
};

const esUS: Strings = {
  title: 'Asistente de cuidado',
  tagline: 'Con IA · Aquí para ayudar',
  placeholder: 'Haga una pregunta o agregue un detalle…',
  disclaimer: 'La IA puede cometer errores. Revise antes de confirmar.',
  support: 'Obtener ayuda',
  launcher: 'Abrir asistente de cuidado',
  close: 'Cerrar asistente',
  send: 'Enviar',
  attach: 'Adjuntar un archivo',
  nextSteps: 'Próximos pasos',
  member: 'Miembro',
  provider: 'Proveedor',
  yourPlan: 'Su plan',
  selectedMember: 'Miembro seleccionado',
  idEnding: 'ID que termina en',
  illustrative: 'Datos ilustrativos',
  today: 'Hoy',
  working: 'Trabajando…',
  sending: 'Enviando…',
  failed: 'No enviado.',
  retry: 'Reintentar',
  reconnecting: 'Reconectando…',
  offline: 'No podemos conectar con el asistente ahora.',
  sessionExpired: 'Su sesión venció. Actualice la página para continuar.',
  helpful: 'Útil',
  notHelpful: 'No útil',
  thanks: 'Gracias por sus comentarios',
  cardSubmitted: 'Enviado',
  newMessage: 'Nuevo mensaje del asistente',
  required: 'Este campo es obligatorio.',
  fileTooLarge: 'Los archivos deben pesar 10 MB o menos.',
  remove: 'Quitar',
};

const bundles: Record<string, Strings> = { 'en-us': enUS, en: enUS, 'es-us': esUS, es: esUS };

export function stringsFor(locale: string | undefined): Strings {
  const key = (locale ?? 'en-US').toLowerCase();
  return bundles[key] ?? bundles[key.split('-')[0]] ?? enUS;
}
