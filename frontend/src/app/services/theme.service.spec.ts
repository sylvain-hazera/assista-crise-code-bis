import { TestBed } from '@angular/core/testing';

import { ThemeService } from './theme.service';

describe('ThemeService', () => {
  const racine = document.documentElement;

  beforeEach(() => localStorage.removeItem('theme'));
  afterEach(() => {
    localStorage.removeItem('theme');
    delete racine.dataset['theme'];
    racine.style.colorScheme = '';
  });

  function creer(): ThemeService {
    return TestBed.inject(ThemeService);
  }

  it('suit le réglage du système par défaut', () => {
    const systemeSombre = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const service = creer();
    expect(service.preference()).toBe('systeme');
    expect(service.theme()).toBe(systemeSombre ? 'sombre' : 'clair');
  });

  it('basculer pose data-theme et color-scheme sur <html> et mémorise le choix', () => {
    const service = creer();
    service.definir('clair');
    service.basculer();
    expect(service.sombre).toBeTrue();
    expect(racine.dataset['theme']).toBe('sombre');
    expect(racine.style.colorScheme).toBe('dark');
    expect(localStorage.getItem('theme')).toBe('sombre');

    service.basculer();
    expect(racine.dataset['theme']).toBe('clair');
    expect(localStorage.getItem('theme')).toBe('clair');
  });

  it('relit le choix mémorisé au démarrage ; ignore une valeur inconnue', () => {
    localStorage.setItem('theme', 'sombre');
    expect(creer().theme()).toBe('sombre');

    TestBed.resetTestingModule();
    localStorage.setItem('theme', 'violet');
    expect(creer().preference()).toBe('systeme');
  });

  it('les couleurs du mode sombre ne s\'appliquent qu\'avec data-theme="sombre"', () => {
    const service = creer();
    const variable = () => getComputedStyle(racine).getPropertyValue('--ac-surface').trim();
    service.definir('clair');
    expect(variable()).toBe('');
    service.definir('sombre');
    expect(variable()).not.toBe('');
  });
});
