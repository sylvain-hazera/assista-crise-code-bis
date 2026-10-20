import { Injectable, signal } from '@angular/core';

/** Choix de l'utilisateur ; `systeme` suit le réglage clair/sombre du navigateur. */
export type PreferenceTheme = 'clair' | 'sombre' | 'systeme';
export type Theme = 'clair' | 'sombre';

const CLE_STOCKAGE = 'theme';

/** Mode sombre : pose `data-theme` sur <html>, les couleurs sont des variables CSS
 * (styles.scss, « Thème »). Préférence locale (localStorage), par défaut celle du système. */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly requeteSysteme = window.matchMedia?.('(prefers-color-scheme: dark)');

  readonly preference = signal<PreferenceTheme>(this.lirePreference());
  /** Thème réellement affiché. */
  readonly theme = signal<Theme>('clair');

  constructor() {
    // Le réglage du système peut changer pendant la session (passage auto au mode nuit).
    this.requeteSysteme?.addEventListener?.('change', () => this.appliquer());
    this.appliquer();
  }

  get sombre(): boolean {
    return this.theme() === 'sombre';
  }

  definir(preference: PreferenceTheme): void {
    this.preference.set(preference);
    try {
      localStorage.setItem(CLE_STOCKAGE, preference);
    } catch {
      // localStorage indisponible : le choix vaut pour la session seulement.
    }
    this.appliquer();
  }

  /** Bouton des en-têtes : passe explicitement à l'autre thème. */
  basculer(): void {
    this.definir(this.sombre ? 'clair' : 'sombre');
  }

  private appliquer(): void {
    const preference = this.preference();
    const theme: Theme = preference === 'systeme'
      ? (this.requeteSysteme?.matches ? 'sombre' : 'clair')
      : preference;
    this.theme.set(theme);
    const racine = document.documentElement;
    racine.dataset['theme'] = theme;
    // Barres de défilement, champs natifs et fond par défaut du navigateur suivent aussi.
    racine.style.colorScheme = theme === 'sombre' ? 'dark' : 'light';
  }

  private lirePreference(): PreferenceTheme {
    try {
      const valeur = localStorage.getItem(CLE_STOCKAGE);
      if (valeur === 'clair' || valeur === 'sombre' || valeur === 'systeme') return valeur;
    } catch {
    }
    return 'systeme';
  }
}
