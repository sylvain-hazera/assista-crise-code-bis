import { Component, OnInit } from '@angular/core';
import { MapComponent } from "../../shared/components/common/map/map.component";
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { forkJoin } from 'rxjs';
import { AuthService } from '../../auth/services/auth.service';
import { CrisisService } from '../../services/crisis.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { Crisis } from '../../shared/models/crisis.model';
import { CentreAccueilPublic } from '../../shared/models/point-operationnel.model';

@Component({
  selector: 'app-home',
  standalone: true,
  templateUrl: './home.component.html',
  styleUrls: ['./home.component.scss'],
  imports: [
    CommonModule,
    MapComponent,
  ],
  providers: [
  ]
})
export class HomeComponent implements OnInit {
  canDeclareCrisis = false;

  // ══ Récapitulatif public, au-dessus de la carte ════════════════════════════
  // Lu par des habitants non connectés, souvent sur téléphone et parfois dans l'urgence : les
  // deux seules questions auxquelles il répond sont « que se passe-t-il près de moi ? » et
  // « où puis-je aller ? ». Les deux endpoints utilisés sont publics (AllowAny) et à champs
  // restreints : CrisisViewSet.list et PointOperationnelViewSet.carte_publique.
  crisesEnCours: Crisis[] = [];
  centresOuverts: CentreAccueilPublic[] = [];
  chargementRecap = true;
  recapIndisponible = false;

  constructor(
    private router: Router,
    private authService: AuthService,
    private crisisService: CrisisService,
    private pointService: PointOperationnelService,
  ) {}

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

    this.chargerRecap();
  }

  private chargerRecap(): void {
    this.chargementRecap = true;
    this.recapIndisponible = false;
    forkJoin({
      crises: this.crisisService.getAll(),
      centres: this.pointService.getCartePublique(),
    }).subscribe({
      next: ({ crises, centres }) => {
        this.crisesEnCours = crises.filter(c => c.is_open !== false);
        // carte_publique ne renvoie déjà que des centres ouverts (crise non terminée, pas de
        // fermeture passée) : on ne refait pas ce tri ici, on se contente d'un ordre utile.
        this.centresOuverts = [...centres].sort((a, b) => a.nom.localeCompare(b.nom, 'fr'));
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
