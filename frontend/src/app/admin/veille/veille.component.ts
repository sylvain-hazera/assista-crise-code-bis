import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';

import { VeilleService } from '../../services/veille.service';
import {
  CategorieEvenementRoutier, EvenementRoutier, EvenementsRoutiers, FicheVigilance,
  PhenomeneVigilance, StationCarburant, StationsCarburant, VigilanceDepartement, VigilanceMeteo,
} from '../../shared/models/veille.model';

/** Veille du territoire : ce que les services de l'État publient en ce moment pour le
 * territoire de l'institution — vigilance météorologique, routes, carburant.
 *
 * Trois règles tiennent cette page :
 *
 * 1. **Elle ne parle qu'à notre serveur.** Les sources sont relevées par une tâche planifiée et
 *    copiées en base ; ouvrir cette page ne déclenche aucun appel vers l'extérieur et ne dit à
 *    personne qui regarde quoi.
 * 2. **Une copie ancienne se dit ancienne.** Chaque bloc affiche l'heure de son relevé et se
 *    signale quand il est périmé : une vigilance d'hier présentée comme celle d'aujourd'hui
 *    serait pire que pas de vigilance.
 * 3. **Un bloc vide dit pourquoi.** « Aucun événement » sur le réseau national ne veut pas dire
 *    que la route départementale est ouverte ; la page rappelle ce que chaque source couvre. */
@Component({
  selector: 'app-veille',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './veille.component.html',
  styleUrl: './veille.component.scss',
})
export class VeilleComponent implements OnInit {

  vigilance: VigilanceMeteo | null = null;
  routes: EvenementsRoutiers | null = null;
  stations: StationsCarburant | null = null;

  erreurVigilance = false;
  erreurRoutes = false;
  erreurStations = false;

  readonly RAYONS = [10, 30, 60, 100];
  rayonKm = 30;

  /** Travaux et restrictions : nombreux et rarement urgents, masqués tant qu'on ne les demande pas. */
  avecTravaux = false;
  /** Par défaut, seules les stations où un carburant manque. */
  toutesLesStations = false;
  bulletinNationalOuvert = false;

  readonly ECHEANCES: { cle: 'J' | 'J1'; libelle: string }[] = [
    { cle: 'J', libelle: "Aujourd'hui" }, { cle: 'J1', libelle: 'Demain' },
  ];
  private readonly SECONDAIRES: CategorieEvenementRoutier[] = ['TRAVAUX', 'RESTRICTION'];

  constructor(private service: VeilleService) {}

  ngOnInit(): void {
    this.chargerVigilance();
    this.chargerTerritoire();
  }

  chargerVigilance(departement?: string): void {
    this.erreurVigilance = false;
    this.service.vigilance(departement).subscribe({
      next: (vigilance) => { this.vigilance = vigilance; },
      error: () => { this.erreurVigilance = true; },
    });
  }

  chargerTerritoire(): void {
    this.erreurRoutes = this.erreurStations = false;
    this.service.evenementsRoutiers({ rayon_km: this.rayonKm }).subscribe({
      next: (routes) => { this.routes = routes; },
      error: () => { this.erreurRoutes = true; },
    });
    this.service.stationsCarburant({ rayon_km: this.rayonKm }).subscribe({
      next: (stations) => { this.stations = stations; },
      error: () => { this.erreurStations = true; },
    });
  }

  changerRayon(rayon: number): void {
    if (rayon === this.rayonKm) return;
    this.rayonKm = rayon;
    this.chargerTerritoire();
  }

  vignetteUrl(echeance: string): string {
    return this.service.vignetteUrl(echeance);
  }

  // ── Vigilance ──

  nomCouleur(couleur: number): string {
    return this.vigilance?.couleurs[String(couleur)] ?? 'vert';
  }

  nomPhenomene(phenomene: PhenomeneVigilance): string {
    const nom = this.vigilance?.phenomenes[String(phenomene.id)] ?? 'phénomène';
    return nom.charAt(0).toUpperCase() + nom.slice(1);
  }

  fiche(departement: VigilanceDepartement, echeance: 'J' | 'J1'): FicheVigilance | null {
    return departement.detail?.[echeance] ?? null;
  }

  /** Début et fin des tranches à la couleur maximale du phénomène, ou null s'il n'en a pas
   * (les crues sont publiées sans horaire). */
  horaire(phenomene: PhenomeneVigilance): { debut: string; fin: string } | null {
    const tranches = phenomene.periodes.filter(p => p.couleur === phenomene.couleur);
    if (!tranches.length) return null;
    return {
      debut: tranches.map(p => p.debut).sort()[0],
      fin: tranches.map(p => p.fin).sort().reverse()[0],
    };
  }

  /** Phénomènes d'un département, toutes échéances confondues, pour le tableau national. */
  resumePhenomenes(departement: VigilanceDepartement): PhenomeneVigilance[] {
    const parId = new Map<number, PhenomeneVigilance>();
    for (const echeance of ['J', 'J1'] as const) {
      for (const phenomene of this.fiche(departement, echeance)?.phenomenes ?? []) {
        const connu = parId.get(phenomene.id);
        if (!connu || phenomene.couleur > connu.couleur) parId.set(phenomene.id, phenomene);
      }
    }
    return [...parId.values()].sort((a, b) => b.couleur - a.couleur || a.id - b.id);
  }

  // ── Routes ──

  get evenementsVisibles(): EvenementRoutier[] {
    const tous = this.routes?.resultats ?? [];
    return this.avecTravaux ? tous : tous.filter(e => !this.SECONDAIRES.includes(e.categorie));
  }

  get nombreSecondaires(): number {
    return (this.routes?.resultats ?? []).filter(e => this.SECONDAIRES.includes(e.categorie)).length;
  }

  /** L'événement n'a pas encore commencé (chantier annoncé). */
  aVenir(evenement: EvenementRoutier): boolean {
    return !!evenement.debut && new Date(evenement.debut).getTime() > Date.now();
  }

  // ── Carburant ──

  get stationsVisibles(): StationCarburant[] {
    const toutes = this.stations?.resultats ?? [];
    return this.toutesLesStations ? toutes : toutes.filter(s => s.ruptures_temporaires.length > 0);
  }

  aSec(station: StationCarburant): boolean {
    return station.ruptures_temporaires.length > 0 && station.carburants_disponibles.length === 0;
  }

  /** Une station qui n'a rien déclaré depuis un mois : ses ruptures ne disent plus rien. */
  muette(station: StationCarburant): boolean {
    if (!station.mis_a_jour_le) return true;
    return Date.now() - new Date(station.mis_a_jour_le).getTime() > 30 * 24 * 3600 * 1000;
  }
}
