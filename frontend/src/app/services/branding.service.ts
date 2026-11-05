import { Injectable, effect, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject } from 'rxjs';
import { environment } from '../../environments/environment';
import { ThemeService } from './theme.service';
import { ajusterPourFond, texteLisibleSur } from './contraste';

export interface Branding {
  nom_affichage: string;
  logo_url: string | null;
  couleur_primaire: string;
  couleur_secondaire: string;
  police_titre: string;
  police_texte: string;
  reserve_active: boolean;
}

const BRANDING_ASSISTA_CRISE: Branding = {
  nom_affichage: 'Assista-Crise',
  logo_url: null,
  couleur_primaire: '#2563eb',
  couleur_secondaire: '#1d4ed8',
  police_titre: '',
  police_texte: '',
  reserve_active: false,
};

// Polices alternatives auto-hébergées DANS CE PROJET (voir src/fonts.scss, même raisonnement
// CNIL que Roboto) -- jamais un chargement depuis Google Fonts au runtime, même pour une
// institution marque blanche : une police demandée par son branding (ex: "Quicksand") doit
// déjà être connue ici (et son @font-face déjà présent dans fonts.scss) ou elle est ignorée,
// pas récupérée dynamiquement depuis un CDN tiers.
const POLICES_AUTOHEBERGEES = new Set(['Quicksand', 'Open Sans', 'Roboto']);

/** Fond de référence sur lequel le texte de marque est posé, par thème. En sombre c'est
 * --ac-surface (la carte, #1c1f26) et non --ac-bg (#101216) : c'est le plus clair des deux,
 * donc le cas le plus défavorable pour un texte clair -- viser celui-là couvre les deux. */
const FOND_PAR_THEME: Record<'clair' | 'sombre', string> = {
  clair: '#ffffff',
  sombre: '#1c1f26',
};

/** Résout et applique le branding (marque blanche) de l'institution dont le sous-domaine
 * correspond au Host visité -- voir core/branding.py côté backend. Appelé une fois au
 * démarrage de l'app (voir AppComponent.ngOnInit), le résultat est ensuite consommé par
 * header/footer (logo, nom) via `branding$`, et les couleurs/polices sont posées directement
 * sur `:root` (voir styles.scss, --brand-*) -- pas besoin que chaque composant les relise.
 *
 * CONTRASTE : une institution choisit sa couleur pour un fond blanc ; rien ne garantit
 * qu'elle reste lisible en mode sombre, ni que du blanc passe dessus. On ne valide donc pas
 * les brandings à la main, on dérive deux variables sûres à chaque changement de thème :
 *   --brand-primary-lisible / --brand-secondary-lisible  -> textes, icônes, bordures fines
 *   --brand-on-primary / --brand-on-secondary            -> texte posé SUR l'aplat de marque
 * Les aplats gardent --brand-primary brut : c'est la couleur de la marque, on n'y touche pas. */
@Injectable({ providedIn: 'root' })
export class BrandingService {
  private url = `${environment.apiUrl}/branding/`;
  private brandingSubject = new BehaviorSubject<Branding>(BRANDING_ASSISTA_CRISE);
  branding$ = this.brandingSubject.asObservable();

  private theme = inject(ThemeService);

  constructor(private http: HttpClient) {
    // Le thème peut changer à tout moment (bouton, ou réglage système en cours de session) :
    // les couleurs dérivées doivent suivre, sinon le texte de marque devient illisible dès
    // la première bascule. L'effect couvre aussi la pose initiale.
    effect(() => {
      this.appliquerCouleurs(this.brandingSubject.value, this.theme.theme());
    });
  }

  charger(): void {
    this.http.get<Branding>(this.url).subscribe({
      next: (branding) => {
        this.brandingSubject.next(branding);
        this.appliquer(branding);
      },
      error: () => {
        // Silencieux : retombe sur les valeurs Assista-Crise déjà posées par défaut (voir
        // BRANDING_ASSISTA_CRISE/styles.scss) -- un souci réseau/API ne doit jamais empêcher
        // l'app de s'afficher, juste avec le branding par défaut.
      },
    });
  }

  get valeurActuelle(): Branding {
    return this.brandingSubject.value;
  }

  /** Couleurs brutes + couleurs dérivées pour le thème donné. Séparée d'`appliquer` parce
   * qu'elle est rejouée à chaque bascule de thème, alors que polices/titre/favicon ne le
   * sont pas. */
  private appliquerCouleurs(branding: Branding, theme: 'clair' | 'sombre'): void {
    const racine = document.documentElement.style;
    const fond = FOND_PAR_THEME[theme] ?? FOND_PAR_THEME.clair;

    racine.setProperty('--brand-primary', branding.couleur_primaire);
    racine.setProperty('--brand-secondary', branding.couleur_secondaire);

    racine.setProperty('--brand-primary-lisible', ajusterPourFond(branding.couleur_primaire, fond));
    racine.setProperty('--brand-secondary-lisible', ajusterPourFond(branding.couleur_secondaire, fond));

    racine.setProperty('--brand-on-primary', texteLisibleSur(branding.couleur_primaire));
    racine.setProperty('--brand-on-secondary', texteLisibleSur(branding.couleur_secondaire));
  }

  private appliquer(branding: Branding): void {
    const racine = document.documentElement.style;
    this.appliquerCouleurs(branding, this.theme.theme());

    const policeTitre = POLICES_AUTOHEBERGEES.has(branding.police_titre) ? branding.police_titre : '';
    const policeTexte = POLICES_AUTOHEBERGEES.has(branding.police_texte) ? branding.police_texte : '';
    if (policeTitre) racine.setProperty('--brand-font-title', `'${policeTitre}', Roboto, "Helvetica Neue", sans-serif`);
    if (policeTexte) racine.setProperty('--brand-font-text', `'${policeTexte}', Roboto, "Helvetica Neue", sans-serif`);

    if (branding.nom_affichage !== BRANDING_ASSISTA_CRISE.nom_affichage) {
      document.title = branding.nom_affichage;
      const favicon = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
      if (favicon && branding.logo_url) favicon.href = branding.logo_url;
    }
  }
}
