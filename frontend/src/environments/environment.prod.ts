export const environment = {
  production: true,
  apiUrl: '/api',
  // Element Web, servi sur son sous-domaine (proxy/nginx.conf, chat.assista-crise.fr).
  elementWebUrl: 'https://chat.assista-crise.fr',
  // Grafana, servi par le proxy (/grafana/) : affiché dans /admin/monitoring.
  grafanaUrl: '/grafana',
};
