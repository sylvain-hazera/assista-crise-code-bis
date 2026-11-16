import { Component, OnInit } from '@angular/core';
import { MapComponent } from "../../shared/components/common/map/map.component";
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { forkJoin, Observable } from 'rxjs';
import { AuthService } from '../../auth/services/auth.service';
import { BrandingService, Branding } from '../../services/branding.service';
import { CrisisService } from '../../services/crisis.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { Crisis } from '../../shared/models/crisis.model';
import { CentreAccueilPublic } from '../../shared/models/point-operationnel.model';

/** Une crise en cours et les centres ouverts qui en dépendent : l'habitant lit « ce qui se passe
 * ici » puis, juste en dessous, « où je peux aller pour ça ». Le dernier groupe (crise = null)
 * rassemble les centres ouverts qui ne sont rattachés à aucune crise. */
export interface GroupeSituation {
  cle: string;
  crise: Crisis | null;
  titre: string;
  type: string | null;
  localisation: string | null;
  debut: string | null;
  centres: CentreAccueilPublic[];
}

import {
  ScannerMobilisationComponent,
} from '../../shared/components/common/scanner-mobilisation/scanner-mobilisation.component';
import {
  MaMobilisation, VerificationMobilisationService,
} from '../../services/verification-mobilisation.service';

@Component({
  selector: 'app-home',
  standalone: true,
  templateUrl: './home.component.html',
  styleUrls: ['./home.component.scss'],
  imports: [
    CommonModule,
    MapComponent,
    ScannerMobilisationComponent,
  ],
  providers: [
  ]
})
export class HomeComponent implements OnInit {
  /** Le nom affiché suit la marque blanche : un bénévole des Casques Jaunes lit
   * « Réserve Résilience », pas « Assista Crise ».
   *
   * Affecté dans le constructeur et non à la déclaration : avec `useDefineForClassFields`,
   * un initialiseur de champ s'exécute avant l'affectation des propriétés de paramètre, et
   * `this.brandingService` y serait encore indéfini. */
  readonly branding$: Observable<Branding>;

  canDeclareCrisis = false;

  // ══ QR codes de mobilisation, dès l'accueil ════════════════════════════════
  // Demande de Sylvain du 14/11/2026 : lire un QR code dès la page d'accueil, même sans
  // compte, et pour l'intervenant montrer le sien en un geste. Les mêmes deux boutons que
  // sur l'écran d'ouverture de l'application mobile.
  scannerOuvert = false;
  /** Les demandes adressées à la personne connectée. Vide pour un visiteur. */
  mesMobilisations: MaMobilisation[] = [];
  qrOuvert = false;
  /** Celle dont le QR code est montré en grand. */
  mobilisationMontree: MaMobilisation | null = null;

  // ══ Application Android ════════════════════════════════════════════════════
  // Demande de Sylvain du 16/11/2026. L'adresse est fixe : chaque nouvelle version de
  // l'application est déposée sous ce même nom (frontend/public/mobile, avec version.json que
  // l'application lit pour proposer sa mise à jour).
  readonly lienAppliAndroid = '/mobile/reserve-resilience.apk';
  /** Un fichier .apk ne s'installe pas sur un iPhone : inutile de le lui proposer. */
  readonly appliAndroidProposee = !/iPhone|iPad|iPod/i.test(navigator.userAgent);

  // ══ Récapitulatif public, au-dessus de la carte ════════════════════════════
  // Lu par des habitants non connectés, souvent sur téléphone et parfois dans l'urgence : les
  // deux seules questions auxquelles il répond sont « que se passe-t-il près de moi ? » et
  // « où puis-je aller ? ». Les deux endpoints utilisés sont publics (AllowAny) et à champs
  // restreints : CrisisViewSet.list et PointOperationnelViewSet.carte_publique.
  groupes: GroupeSituation[] = [];
  nbCrises = 0;
  nbCentres = 0;
  chargementRecap = true;
  recapIndisponible = false;

  constructor(
    private brandingService: BrandingService,
    private router: Router,
    private authService: AuthService,
    private crisisService: CrisisService,
    private pointService: PointOperationnelService,
    private verificationMobilisation: VerificationMobilisationService,
  ) {
    this.branding$ = this.brandingService.branding$;
  }

  ngOnInit(): void {
    const user = this.authService.getCurrentUser();
    if (user) {
      const allowedRoles = ['ADMIN', 'AUT_LOCALE', 'SECOURS'];
      // Le backend envoie 'type' pas 'userType'
      const userRole = (user as any).type;
      this.canDeclareCrisis = allowedRoles.includes(userRole as string);
    } else {
      this.canDeclareCrisis = false;
    }

    if (user) {
      // Silencieux en cas d'échec : le bouton « Mon QR code » n'apparaît simplement pas, et
      // l'accueil n'a pas à afficher une erreur pour une fonction que la plupart n'ont pas.
      this.verificationMobilisation.mesMobilisations().subscribe({
        next: (demandes) => this.mesMobilisations = demandes,
        error: () => this.mesMobilisations = [],
      });
    }

    this.chargerRecap();
  }

  /** Ouvre le QR code : la demande active la plus récente d'abord, c'est celle qu'on contrôle. */
  montrerMonQr(): void {
    this.mobilisationMontree = this.mesMobilisations.find(m => m.statut === 'ACTIVE')
      ?? this.mesMobilisations[0] ?? null;
    this.qrOuvert = !!this.mobilisationMontree;
  }

  lieuDe(m: MaMobilisation): string {
    return m.point_operationnel_nom || m.lieu_texte || '';
  }

  private chargerRecap(): void {
    this.chargementRecap = true;
    this.recapIndisponible = false;
    forkJoin({
      crises: this.crisisService.getAll(),
      centres: this.pointService.getCartePublique(),
    }).subscribe({
      next: ({ crises, centres }) => {
        this.groupes = this.construireGroupes(
          crises.filter(c => c.is_open !== false),
          centres,
        );
        this.chargementRecap = false;
      },
      error: () => {
        // La carte en dessous reste utilisable : on n'affiche pas d'erreur alarmante, juste
        // un repli discret.
        this.chargementRecap = false;
        this.recapIndisponible = true;
      },
    });
  }

  /** Regroupe les centres sous leur crise. Une crise sans centre reste affichée — « aucun centre
   * ouvert » est une information utile, pas un trou. Les centres orphelins (sans crise, ou dont
   * la crise n'est pas dans la liste publique) terminent la liste dans un groupe à part, jamais
   * silencieusement écartés. */
  private construireGroupes(crises: Crisis[], centres: CentreAccueilPublic[]): GroupeSituation[] {
    // carte_publique ne renvoie déjà que des centres ouverts (crise non terminée, pas de
    // fermeture passée) : on ne refait pas ce tri ici, on se contente d'un ordre utile.
    const parNom = (a: CentreAccueilPublic, b: CentreAccueilPublic) => a.nom.localeCompare(b.nom, 'fr');

    const groupes = new Map<string, GroupeSituation>();
    // Crises les plus récentes en premier : c'est celle qui vient de se déclarer qu'on cherche.
    const crisesTriees = [...crises].sort(
      (a, b) => (b.start_date || '').localeCompare(a.start_date || ''),
    );
    for (const crise of crisesTriees) {
      groupes.set(String(crise.id), {
        cle: String(crise.id),
        crise,
        titre: crise.name,
        type: this.typeCrise(crise),
        localisation: this.localisationCrise(crise),
        debut: crise.start_date || null,
        centres: [],
      });
    }

    const orphelins: CentreAccueilPublic[] = [];
    for (const centre of centres) {
      const groupe = centre.crise ? groupes.get(String(centre.crise)) : undefined;
      if (groupe) {
        groupe.centres.push(centre);
      } else {
        orphelins.push(centre);
      }
    }

    const liste = Array.from(groupes.values());
    for (const groupe of liste) {
      groupe.centres.sort(parNom);
    }
    if (orphelins.length) {
      liste.push({
        cle: 'hors-crise',
        crise: null,
        titre: 'Autres centres ouverts',
        type: null,
        localisation: null,
        debut: null,
        centres: orphelins.sort(parNom),
      });
    }

    this.nbCrises = crisesTriees.length;
    this.nbCentres = centres.length;
    return liste;
  }

  /** Ce qu'on sait dire du lieu d'une crise sans authentification : la commune résolue, sinon
   * le nombre de communes de sa zone, sinon rien plutôt qu'un faux renseignement. */
  localisationCrise(crise: Crisis): string {
    if (crise.commune) { return crise.commune; }
    const communes = crise.zone_communes?.length ?? 0;
    if (communes === 1) { return '1 commune concernée'; }
    if (communes > 1) { return `${communes} communes concernées`; }
    return 'Localisation à préciser';
  }

  typeCrise(crise: Crisis): string {
    return crise.type_display || crise.type || 'Type non précisé';
  }

  /** Places restantes, uniquement quand la capacité est connue : afficher « 0 place » pour une
   * capacité non renseignée enverrait les gens ailleurs pour rien. */
  placesRestantes(centre: CentreAccueilPublic): number | null {
    if (centre.capacite_accueil == null) { return null; }
    return Math.max(0, centre.capacite_accueil - (centre.personnes_presentes || 0));
  }

  centreComplet(centre: CentreAccueilPublic): boolean {
    const restantes = this.placesRestantes(centre);
    return restantes !== null && restantes === 0;
  }

  estPosteDeSecours(centre: CentreAccueilPublic): boolean {
    return centre.type_code === 'SECOURS';
  }

  /** Itinéraire vers le centre : coordonnées si on les a (le plus fiable), sinon l'adresse
   * écrite. `null` quand on n'a ni l'une ni l'autre — mieux vaut pas de bouton qu'un bouton
   * qui ouvre une carte au milieu de nulle part. */
  lienItineraire(centre: CentreAccueilPublic): string | null {
    const base = 'https://www.google.com/maps/dir/?api=1&destination=';
    if (centre.latitude != null && centre.longitude != null) {
      return `${base}${centre.latitude},${centre.longitude}`;
    }
    if (centre.adresse?.trim()) {
      return `${base}${encodeURIComponent(centre.adresse.trim())}`;
    }
    return null;
  }

  navigateTo(route: string): void {
    this.router.navigate([route]);
  }

}
