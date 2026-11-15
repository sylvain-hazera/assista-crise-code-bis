import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';

import { VeilleService } from '../../services/veille.service';
import {
  ArreteCirculation, ArretesCirculation, CategorieEvenementRoutier, FoyersActifs, EvenementRoutier, EvenementsRoutiers, FicheVigilance, MeteoForets,
  ObservationMeteo, ObservationsMeteo, RafalesPrevues, PhenomeneVigilance, RestrictionsEau, RisqueAvalanche,
  Radioactivite, SanteUrgences, Seisme, Seismes, Volcan,
  VigilanceCrues, ZonesBrulees, StationCarburant, StationsCarburant, VigilanceDepartement, VigilanceMeteo,
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
  observations: ObservationsMeteo | null = null;
  crues: VigilanceCrues | null = null;
  eau: RestrictionsEau | null = null;
  forets: MeteoForets | null = null;
  rafales: RafalesPrevues | null = null;
  sante: SanteUrgences | null = null;
  radioactivite: Radioactivite | null = null;
  seismes: Seismes | null = null;
  /** Les seuls volcans à portée du territoire : vide en métropole, et le bloc ne s'affiche pas. */
  volcans: Volcan[] = [];
  rayonVolcanKm = 15;
  feux: ZonesBrulees | null = null;
  foyers: FoyersActifs | null = null;
  /** Reste null en plaine comme en cas d'erreur : le bloc n'apparaît que s'il y a un massif. */
  avalanche: RisqueAvalanche | null = null;
  routes: EvenementsRoutiers | null = null;
  arretes: ArretesCirculation | null = null;
  stations: StationsCarburant | null = null;

  erreurVigilance = false;
  erreurObservations = false;
  erreurCrues = false;
  erreurEau = false;
  erreurFeux = false;
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
    this.chargerDepartement();
    this.chargerTerritoire();
  }

  /** Ce qui se lit par département et ne dépend pas du rayon : restrictions d'eau et danger
   * de feu de forêt. */
  chargerDepartement(): void {
    this.erreurEau = false;
    this.service.restrictionsEau().subscribe({
      next: (eau) => { this.eau = eau; },
      error: () => { this.erreurEau = true; },
    });
    this.service.volcans().subscribe({
      next: (reponse) => { this.volcans = reponse.volcans.filter(v => v.a_portee); this.rayonVolcanKm = reponse.rayon_km; },
      error: () => { this.volcans = []; },
    });
    this.service.santeUrgences().subscribe({
      next: (sante) => { this.sante = sante; },
      error: () => { this.sante = null; },
    });
    this.service.meteoForets().subscribe({
      next: (forets) => { this.forets = forets; },
      error: () => { this.forets = null; },
    });
    // Rafales prévues sur la commune : lues par le serveur dans ses images, rien ne sort.
    this.service.rafalesPrevues(true).subscribe({
      next: (rafales) => { this.rafales = rafales; },
      error: () => { this.rafales = null; },
    });
  }

  chargerVigilance(departement?: string): void {
    this.erreurVigilance = false;
    this.service.vigilance(departement).subscribe({
      next: (vigilance) => { this.vigilance = vigilance; },
      error: () => { this.erreurVigilance = true; },
    });
  }

  chargerTerritoire(): void {
    this.erreurObservations = this.erreurRoutes = this.erreurStations = false;
    this.erreurCrues = this.erreurFeux = false;
    this.service.vigilanceCrues({ rayon_km: this.rayonKm }).subscribe({
      next: (crues) => { this.crues = crues; },
      error: () => { this.erreurCrues = true; },
    });
    this.service.radioactivite({ rayon_km: this.rayonKm }).subscribe({
      next: (radioactivite) => { this.radioactivite = radioactivite; },
      error: () => { this.radioactivite = null; },
    });
    // Sous 1,5, un séisme n'est pas ressenti et la liste se noie dans les tirs de carrière.
    this.service.seismes({ rayon_km: this.rayonKm }, 1.5).subscribe({
      next: (seismes) => { this.seismes = seismes; },
      error: () => { this.seismes = null; },
    });
    this.service.risqueAvalanche({ rayon_km: this.rayonKm }).subscribe({
      next: (avalanche) => { this.avalanche = avalanche; },
      error: () => { this.avalanche = null; },
    });
    this.service.foyersActifs({ rayon_km: this.rayonKm }).subscribe({
      next: (foyers) => { this.foyers = foyers; },
      error: () => { this.foyers = null; },
    });
    this.service.zonesBrulees({ rayon_km: this.rayonKm }).subscribe({
      next: (feux) => { this.feux = feux; },
      error: () => { this.erreurFeux = true; },
    });
    this.service.observationsMeteo({ rayon_km: this.rayonKm }).subscribe({
      next: (observations) => { this.observations = observations; },
      error: () => { this.erreurObservations = true; },
    });
    this.service.arretesCirculation({ rayon_km: this.rayonKm }).subscribe({
      next: (arretes) => { this.arretes = arretes; },
      error: () => { this.arretes = null; },
    });
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

  // ── Mesures des stations ──

  /** Seuils d'affichage, pas d'alerte : ils servent à faire ressortir une ligne dans un tableau.
   * 80 km/h de rafale et 20 mm en une heure sont l'ordre de grandeur à partir duquel
   * Météo-France parle de vent fort et de pluie intense ; 50 mm sur la journée, de cumul notable. */
  readonly RAFALE_FORTE_KMH = 80;
  readonly PLUIE_FORTE_1H_MM = 20;
  readonly PLUIE_FORTE_24H_MM = 50;

  /** Rafale la plus forte PRÉVUE sur la commune d'ici trois heures : son palier en clair et la
   * première échéance où il est atteint. `null` si rien n'atteint le premier palier, ou si la
   * commune est hors de la prévision (outre-mer). */
  get rafalePrevue(): { libelle: string; echeance: string; forte: boolean } | null {
    const ici = this.rafales?.ici;
    if (!this.rafales || !ici?.couvert || !ici.maximum_kmh) return null;
    const seuils = this.rafales.legende.map(palier => palier.a_partir_de_kmh);
    const suivant = seuils[seuils.indexOf(ici.maximum_kmh) + 1];
    const atteint = ici.paliers.find(palier => palier.a_partir_de_kmh === ici.maximum_kmh);
    if (!atteint) return null;
    return {
      libelle: suivant ? `${ici.maximum_kmh} à ${suivant} km/h` : `${ici.maximum_kmh} km/h ou plus`,
      echeance: atteint.echeance,
      forte: ici.maximum_kmh >= this.RAFALE_FORTE_KMH,
    };
  }

  /** La rafale la plus forte connue : celle de l'heure écoulée ou celle des dix dernières minutes. */
  rafale(station: ObservationMeteo): number | null {
    const valeurs = [station.rafale_kmh, station.rafale_1h_kmh].filter((v): v is number => v != null);
    return valeurs.length ? Math.max(...valeurs) : null;
  }

  remarquable(station: ObservationMeteo): boolean {
    return (this.rafale(station) ?? 0) >= this.RAFALE_FORTE_KMH
      || (station.pluie_1h_mm ?? 0) >= this.PLUIE_FORTE_1H_MM
      || (station.pluie_24h_mm ?? 0) >= this.PLUIE_FORTE_24H_MM;
  }

  /** Points cardinaux d'où vient le vent (la source donne des degrés). */
  direction(degres: number | null): string {
    if (degres == null) return '';
    return ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO'][Math.round(degres / 45) % 8];
  }

  // ── Séismes et radioactivité ──

  /** Les vrais séismes d'abord ; tirs de carrière et explosions sont listés à part. */
  get seismesNaturels(): Seisme[] {
    return (this.seismes?.resultats ?? []).filter(s => s.nature === 'earthquake');
  }

  get autresSecousses(): Seisme[] {
    return (this.seismes?.resultats ?? []).filter(s => s.nature !== 'earthquake');
  }

  /** « en hausse » seulement quand le nombre a au moins doublé et qu'il y en a au moins cinq :
   * sous un volcan, passer de un à trois séismes ne veut rien dire. */
  sismiciteEnHausse(volcan: Volcan): boolean {
    return volcan.seismes_7_jours >= 5 && volcan.seismes_7_jours >= 2 * Math.max(1, volcan.seismes_7_jours_precedents);
  }

  // ── Eau et feux ──

  /** Rang d'un niveau de restriction d'eau, pour la pastille : 0 aucune … 4 crise. */
  rangEau(niveau: string): number {
    return ['', 'vigilance', 'alerte', 'alerte_renforcee', 'crise'].indexOf(niveau);
  }

  libelleEau(niveau: string): string {
    return niveau ? (this.eau?.libelles[niveau] ?? niveau) : 'Aucune restriction';
  }

  libelleAvalanche(niveau: number | null): string {
    return niveau == null ? 'pas de bulletin' : (this.avalanche?.libelles[String(niveau)] ?? String(niveau));
  }

  libelleFeu(niveau: number | null): string {
    return niveau == null ? '—' : (this.forets?.libelles[String(niveau)] ?? String(niveau));
  }

  // ── Routes ──

  get evenementsVisibles(): EvenementRoutier[] {
    const tous = this.routes?.resultats ?? [];
    return this.avecTravaux ? tous : tous.filter(e => !this.SECONDAIRES.includes(e.categorie));
  }

  get nombreSecondaires(): number {
    return (this.routes?.resultats ?? []).filter(e => this.SECONDAIRES.includes(e.categorie)).length;
  }

  /** Arrêtés temporaires de fermeture : ce qu'une cellule de crise doit voir d'abord. Les
   * arrêtés permanents et les restrictions de tonnage sont comptés, et se lisent sur la carte. */
  get fermeturesTemporaires(): ArreteCirculation[] {
    return (this.arretes?.resultats ?? []).filter(a => a.categorie === 'FERMETURE' && a.fin);
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
