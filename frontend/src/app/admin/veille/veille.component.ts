import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';

import { VeilleService } from '../../services/veille.service';
import {
  AntennesIndisponibles, QualiteAir, LIBELLES_GRAVITE_ANTENNE, technologiesCoupees,
  ArreteCirculation, ArretesCirculation, Circulation, LIBELLES_ETAT_CIRCULATION, TronconCirculation, sensDeCirculation,
  HauteursEau, LIBELLES_TENDANCE_EAU, LIBELLES_ETAT_SURCOTE, NiveauMer, NiveauxMer, StationHydrometrique, variationEau, CategorieEvenementRoutier, FoyersActifs, EvenementRoutier, EvenementsRoutiers, FicheVigilance, MeteoForets,
  ObservationMeteo, ObservationsMeteo, RafalesPrevues, PrecipitationsHiver, PhenomeneVigilance, RestrictionsEau, RisqueAvalanche,
  Radioactivite, SanteUrgences, Seisme, Seismes, Volcan,
  VigilanceCrues, ZonesBrulees, StationCarburant, StationsCarburant, VigilanceDepartement, VigilanceMeteo,
  CelluleOrage, OragesRadar,
} from '../../shared/models/veille.model';
import { Subscription } from 'rxjs';
import { pollWhileVisible } from '../../shared/utils/polling.util';

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
export class VeilleComponent implements OnInit, OnDestroy {

  /** Orages selon le radar (une image toutes les 5 min) : relu toutes les 2 min, onglet visible. */
  orages: OragesRadar | null = null;
  readonly FENETRES_CUMUL = ['1h', '3h', '24h'] as const;
  erreurOrages = false;
  private suiviOrages?: Subscription;

  vigilance: VigilanceMeteo | null = null;
  observations: ObservationsMeteo | null = null;
  crues: VigilanceCrues | null = null;
  eau: RestrictionsEau | null = null;
  forets: MeteoForets | null = null;
  rafales: RafalesPrevues | null = null;
  hiver: PrecipitationsHiver | null = null;
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
  circulation: Circulation | null = null;
  hauteursEau: HauteursEau | null = null;
  mer: NiveauxMer | null = null;
  antennes: AntennesIndisponibles | null = null;
  air: QualiteAir | null = null;
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
    this.suiviOrages = pollWhileVisible(() => this.service.orages(), 120_000).subscribe({
      next: (orages) => { this.orages = orages; this.erreurOrages = false; },
      error: () => { this.erreurOrages = true; },
    });
    // Rafales prévues sur la commune : lues par le serveur dans ses images, rien ne sort.
    this.service.rafalesPrevues(true).subscribe({
      next: (rafales) => { this.rafales = rafales; },
      error: () => { this.rafales = null; },
    });
    this.service.precipitationsHiver(true).subscribe({
      next: (hiver) => { this.hiver = hiver; },
      error: () => { this.hiver = null; },
    });
  }

  ngOnDestroy(): void { this.suiviOrages?.unsubscribe(); }

  /** Une cellule touche-t-elle déjà la commune de l'institution, ou l'atteindrait-elle ? */
  communesOrage(cellule: CelluleOrage, max = 12): string {
    const noms = cellule.releves.communes_sous_la_pluie.map(c => c.nom);
    return noms.length > max ? `${noms.slice(0, max).join(', ')} et ${noms.length - max} autre(s)` : noms.join(', ');
  }

  /** Communes atteintes, regroupées par délai : « dans 15 min : A, B ; dans 30 min : C ». */
  atteintesParDelai(cellule: CelluleOrage): { delai: number; noms: string }[] {
    const groupes = new Map<number, string[]>();
    for (const c of cellule.estimations.communes_atteintes) {
      const tranche = Math.ceil((c.dans_min ?? 0) / 15) * 15;
      groupes.set(tranche, [...(groupes.get(tranche) ?? []), c.nom]);
    }
    return [...groupes].sort((a, b) => a[0] - b[0]).map(([delai, noms]) => ({
      delai, noms: noms.length > 10 ? `${noms.slice(0, 10).join(', ')} et ${noms.length - 10} autre(s)` : noms.join(', '),
    }));
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
    this.service.qualiteAir({ rayon_km: this.rayonKm }).subscribe({
      next: (air) => { this.air = air; },
      error: () => { this.air = null; },
    });
    this.service.antennesIndisponibles({ rayon_km: this.rayonKm }).subscribe({
      next: (antennes) => { this.antennes = antennes; },
      error: () => { this.antennes = null; },
    });
    this.service.niveauxMer({ rayon_km: this.rayonKm }).subscribe({
      next: (mer) => { this.mer = mer; },
      error: () => { this.mer = null; },
    });
    this.service.hauteursEau({ rayon_km: this.rayonKm }).subscribe({
      next: (hauteurs) => { this.hauteursEau = hauteurs; },
      error: () => { this.hauteursEau = null; },
    });
    this.service.circulation({ rayon_km: this.rayonKm }).subscribe({
      next: (circulation) => { this.circulation = circulation; },
      error: () => { this.circulation = null; },
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

  // ── Qualité de l'air ──

  /** Polluants montrés, avec leur nom d'usage. */
  readonly POLLUANTS: { cle: string; nom: string }[] = [
    { cle: 'pm2_5', nom: 'particules fines PM2,5' }, { cle: 'pm10', nom: 'PM10' },
    { cle: 'no2', nom: 'dioxyde d’azote' }, { cle: 'o3', nom: 'ozone' },
  ];

  /** Vrai quand la prévision annonce pire que l'état du moment. */
  get airSeDegrade(): boolean {
    const point = this.air?.plus_proche;
    return !!point && point.pire_24h != null && point.indice != null && point.pire_24h > point.indice;
  }

  // ── Réseau mobile ──

  readonly LIBELLES_GRAVITE_ANTENNE = LIBELLES_GRAVITE_ANTENNE;
  readonly technologiesCoupees = technologiesCoupees;
  /** Nombre d'antennes listées : au-delà, la carte. */
  readonly ANTENNES_LISTEES = 10;

  /** « Orange 41, SFR 13 » : les pannes affichées, par opérateur. */
  get antennesParOperateur(): { operateur: string; nombre: number }[] {
    return Object.entries(this.antennes?.par_operateur ?? {}).map(([operateur, nombre]) => ({ operateur, nombre }));
  }

  /** Les opérateurs dont des déclarations ont été écartées parce qu'elles ont plus de six mois. */
  get antennesEcartees(): { operateur: string; nombre: number; toutes: boolean }[] {
    const affichees = this.antennes?.par_operateur ?? {};
    return Object.entries(this.antennes?.ecartees_par_operateur ?? {})
      .map(([operateur, nombre]) => ({ operateur, nombre, toutes: !affichees[operateur] }));
  }

  get nombreAntennes(): number {
    return this.antennesParOperateur.reduce((total, ligne) => total + ligne.nombre, 0);
  }

  // ── Niveau de la mer ──

  readonly LIBELLES_ETAT_SURCOTE = LIBELLES_ETAT_SURCOTE;

  /** Les marégraphes qui ont une mesure récente : les autres ne disent rien. */
  get maregraphesMesures(): NiveauMer[] {
    return (this.mer?.resultats ?? []).filter(m => m.niveau_m != null);
  }

  // ── Hauteurs d'eau ──

  readonly LIBELLES_TENDANCE_EAU = LIBELLES_TENDANCE_EAU;
  readonly variationEau = variationEau;
  /** Stations stables ou en baisse : masquées tant qu'on ne les demande pas. */
  toutesLesHauteurs = false;

  get stationsEnHausse(): StationHydrometrique[] {
    return (this.hauteursEau?.resultats ?? []).filter(s => s.tendance === 'HAUSSE_RAPIDE' || s.tendance === 'HAUSSE');
  }

  /** Les stations à lister : celles qui montent, ou toutes celles qui ont une mesure. */
  get stationsEauVisibles(): StationHydrometrique[] {
    return this.toutesLesHauteurs
      ? (this.hauteursEau?.resultats ?? []).filter(s => s.tendance !== 'INCONNUE')
      : this.stationsEnHausse;
  }

  get stationsEauMesurees(): number {
    const bilan = this.hauteursEau?.bilan;
    return bilan ? bilan.HAUSSE_RAPIDE + bilan.HAUSSE + bilan.STABLE + bilan.BAISSE : 0;
  }

  // ── Circulation ──

  readonly LIBELLES_ETAT_CIRCULATION = LIBELLES_ETAT_CIRCULATION;
  readonly sensDeCirculation = sensDeCirculation;

  /** Les tronçons qui ne roulent pas normalement : bloqués, saturés ou denses. */
  get ralentissements(): TronconCirculation[] {
    return (this.circulation?.resultats ?? []).filter(t => t.etat === 'BLOQUE' || t.etat === 'SATURE' || t.etat === 'DENSE');
  }

  /** Nombre de tronçons dont on connaît l'état (les « sans mesure » ne disent rien). */
  get tronconsMesures(): number {
    const bilan = this.circulation?.bilan;
    return bilan ? bilan.BLOQUE + bilan.SATURE + bilan.DENSE + bilan.FLUIDE : 0;
  }

  /** Neige, verglas ou grêle PRÉVUS sur la commune d'ici trois heures : le plus dangereux de ce
   * qui est annoncé, et la première échéance où il l'est. `null` si rien de tel n'est prévu. */
  get hiverPrevu(): { libelle: string; echeance: string; grave: boolean } | null {
    const ici = this.hiver?.ici;
    if (!this.hiver || !ici?.couvert || !ici.pire) return null;
    const premiere = ici.familles.find(f => f.famille === ici.pire);
    const famille = this.hiver.legende.find(f => f.cle === ici.pire);
    if (!premiere || !famille) return null;
    return { libelle: famille.libelle.toLowerCase(), echeance: premiere.echeance,
             grave: ici.pire === 'VERGLAS' || ici.pire === 'GRELE' };
  }

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
