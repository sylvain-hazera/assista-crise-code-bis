import { AfterViewInit, Component, ElementRef, OnDestroy, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import { takeWhile } from 'rxjs/operators';
import { styleCarte } from '../../shared/utils/carte-style';
import maplibregl from 'maplibre-gl';
import type { Feature, FeatureCollection, MultiPolygon, Point, Polygon } from 'geojson';

import { pollWhileVisible } from '../../shared/utils/polling.util';
import { TagSearchInputComponent } from '../../shared/components/common/tag-search-input/tag-search-input.component';
import { LocationService, Commune } from '../../services/location.service';
import { SimulationInondationService } from '../../services/simulation-inondation.service';
import { AdresseSimulee, NiveauObserve, SimulationAdresses, SimulationInondation, SimulationRuissellement } from '../../shared/models/simulation-inondation.model';

const ZONE_SOURCE_ID = 'inondation-zone';
const ADRESSES_SOURCE_ID = 'inondation-adresses';
const RUISSELLEMENT_SOURCE_ID = 'inondation-ruissellement';
const COMMUNE_SOURCE_ID = 'commune-contour';
const GEORISQUES_SOURCE_ID = 'georisques-alea';
// Zones inondables officielles Géorisques (BRGM/DGPR, rapportage 2020) récupérées EN VECTEUR via
// le backend (WFS) et dessinées ici en violet franc : les tuiles WMS d'origine, vert pâle à ~40 %
// d'opacité, étaient illisibles sur le fond de carte (demande utilisateur du 20/10/2026). Mêmes
// zones que le filtre de l'estimation des dégâts.
const GEORISQUES_COUCHES = [
  { valeur: 'ALEA_SYNT_01_01FOR_FXX', libelle: 'Débordement de cours d\'eau — fréquent (décennal)' },
  { valeur: 'ALEA_SYNT_01_02MOY_FXX', libelle: 'Débordement de cours d\'eau — moyen (centennal, réf. PPRI)' },
  { valeur: 'ALEA_SYNT_01_04FAI_FXX', libelle: 'Débordement de cours d\'eau — rare (millénal)' },
  { valeur: 'ALEA_SYNT_02_02MOY_FXX', libelle: 'Ruissellement — moyen (centennal)' },
  { valeur: 'ALEA_SYNT_03_02MOY_FXX', libelle: 'Submersion marine — moyen (centennal)' },
];
const CLE_DERNIERE_COMMUNE = 'simulation-inondation-derniere-commune';
const INTERVALLE_POLLING_MS = 6_000;
// Seuils de gravité par hauteur d'eau (m) -- limité ≤ 0,5 ; modéré ≤ 1 ; fort au-delà.
const SEUILS_GRAVITE = { limite: 0.5, modere: 1 };
const METRES_PAR_DEGRE_LAT = 111_320; // même valeur que core/inondation.py, pour la cohérence

type ColonneTri = 'adresse' | 'altitude' | 'profondeur';

/** Simulation grossière d'inondation par commune (outil de planification, pas une prévision).
 * Calcul asynchrone (Celery), interrogé par polling ; adresses BAN chargées séparément, sur
 * demande ; deux modes superposables (crue de rivière, ruissellement).
 * Voir DOCUMENTATION.md, § 6.5. */
@Component({
  selector: 'app-simulation-inondation',
  standalone: true,
  imports: [CommonModule, FormsModule, TagSearchInputComponent],
  templateUrl: './simulation-inondation.component.html',
  styleUrl: './simulation-inondation.component.scss',
})
export class SimulationInondationComponent implements AfterViewInit, OnDestroy {
  @ViewChild('mapContainer', { static: true }) mapContainer!: ElementRef<HTMLDivElement>;

  communeSearchFn = (q: string) => this.locationService.searchCommunesByName(q);

  communeSelectionnee: Commune | null = null;
  enCours = false;
  erreur = '';
  simulation: SimulationInondation | null = null;
  niveauCourant = 0;

  adresses: SimulationAdresses | null = null;
  adressesEnCours = false;
  adressesErreur = '';

  /** Dernier niveau observé (Hub'Eau, station la plus proche), même référentiel NGF : repère
   * informatif, un seul appel (cache serveur 5 min, core/hydrometrie.py). */
  niveauObserve: NiveauObserve | null = null;

  // Overlay des zones inondables officielles (Géorisques), indépendant de la simulation.
  readonly georisquesCouches = GEORISQUES_COUCHES;
  coucheGeorisquesActive = false;
  georisquesCouche = 'ALEA_SYNT_01_02MOY_FXX';

  coucheRiviereActive = true;
  coucheRuissellementActive = false;
  ruissellement: SimulationRuissellement | null = null;
  ruissellementEnCours = false;
  ruissellementErreur = '';

  triColonne: ColonneTri = 'profondeur';
  triDirection: 'asc' | 'desc' = 'desc';

  private map: maplibregl.Map | null = null;
  private mapPret = false;
  private pollingSub?: Subscription;
  private adressesPollingSub?: Subscription;
  private ruissellementPollingSub?: Subscription;

  constructor(
    private locationService: LocationService,
    private simulationService: SimulationInondationService,
  ) {}

  ngAfterViewInit(): void {
    this.map = new maplibregl.Map({
      container: this.mapContainer.nativeElement,
      style: styleCarte(),
      center: [2.5, 46.6],
      zoom: 5,
      attributionControl: false,
    });
    this.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    this.map.once('load', () => { this.mapPret = true; });

    this.restaurerDerniereCommune();
  }

  ngOnDestroy(): void {
    this.pollingSub?.unsubscribe();
    this.adressesPollingSub?.unsubscribe();
    this.ruissellementPollingSub?.unsubscribe();
    this.map?.remove();
  }

  /** Resélectionne la dernière commune (localStorage) ; le statut est relu sur le serveur.
   * Ne relance jamais le chargement des adresses. */
  private restaurerDerniereCommune(): void {
    try {
      const brut = localStorage.getItem(CLE_DERNIERE_COMMUNE);
      if (!brut) return;
      const commune = JSON.parse(brut) as Commune;
      if (commune?.code) this.choisirCommune(commune);
    } catch {
      // Stockage indisponible : l'utilisateur rechoisit sa commune.
    }
  }

  choisirCommune(commune: Commune): void {
    this.communeSelectionnee = commune;
    this.cadrerSurCommune(commune);
    this.majCoucheGeorisques();
    this.simulation = null;
    this.erreur = '';
    this.enCours = true;
    this.pollingSub?.unsubscribe();

    this.adresses = null;
    this.adressesErreur = '';
    this.adressesPollingSub?.unsubscribe();

    this.ruissellement = null;
    this.ruissellementErreur = '';
    this.ruissellementPollingSub?.unsubscribe();

    this.niveauObserve = null;
    this.simulationService.niveauObserve(commune.code).subscribe({
      next: (resultat) => { this.niveauObserve = resultat; },
      error: () => { /* repère informatif seulement -- une absence de donnée ne bloque rien */ },
    });

    try { localStorage.setItem(CLE_DERNIERE_COMMUNE, JSON.stringify(commune)); } catch { /* best-effort */ }

    this.pollingSub = pollWhileVisible(() => this.simulationService.simuler(commune.code), INTERVALLE_POLLING_MS)
      .pipe(takeWhile(resultat => resultat.statut === 'EN_COURS', true))
      .subscribe({
        next: (resultat) => {
          this.simulation = resultat;
          if (resultat.statut === 'EN_COURS') return;

          this.enCours = false;
          if (resultat.statut === 'ECHEC') {
            this.erreur = resultat.erreur || "Échec de la simulation pour cette commune.";
            return;
          }
          this.niveauCourant = resultat.niveaux?.[0] ?? 0;
          this.afficherSurCarte();
        },
        error: (err) => {
          this.enCours = false;
          this.erreur = err?.error?.erreur || "Échec de la simulation pour cette commune. Une nouvelle tentative est possible ; contacter le support si le problème persiste.";
        },
      });
  }

  /** Déclenché uniquement par le bouton « Charger les adresses ». */
  chargerAdresses(): void {
    const commune = this.communeSelectionnee;
    if (!commune || this.adressesEnCours) return;

    this.adresses = null;
    this.adressesErreur = '';
    this.adressesEnCours = true;
    this.adressesPollingSub?.unsubscribe();

    this.adressesPollingSub = pollWhileVisible(() => this.simulationService.chargerAdresses(commune.code), INTERVALLE_POLLING_MS)
      .pipe(takeWhile(resultat => resultat.statut === 'EN_COURS', true))
      .subscribe({
        next: (resultat) => {
          this.adresses = resultat;
          if (resultat.statut === 'EN_COURS') return;

          this.adressesEnCours = false;
          if (resultat.statut === 'ECHEC') {
            this.adressesErreur = resultat.erreur || "Échec du chargement des adresses pour cette commune.";
            return;
          }
          this.rafraichirCoucheAdresses();
        },
        error: (err) => {
          this.adressesEnCours = false;
          this.adressesErreur = err?.error?.erreur || "Échec du chargement des adresses. Une nouvelle tentative est possible.";
        },
      });
  }

  /** Couches indépendantes, activables ensemble ; le ruissellement se calcule à la première activation. */
  basculerCoucheRiviere(): void {
    this.coucheRiviereActive = !this.coucheRiviereActive;
    this.majVisibiliteCouches();
  }

  basculerCoucheRuissellement(): void {
    this.coucheRuissellementActive = !this.coucheRuissellementActive;
    this.majVisibiliteCouches();
    if (this.coucheRuissellementActive && this.communeSelectionnee && !this.ruissellement && !this.ruissellementEnCours) {
      this.chargerRuissellement();
    }
  }

  private chargerRuissellement(): void {
    const commune = this.communeSelectionnee;
    if (!commune || this.ruissellementEnCours) return;

    this.ruissellement = null;
    this.ruissellementErreur = '';
    this.ruissellementEnCours = true;
    this.ruissellementPollingSub?.unsubscribe();

    this.ruissellementPollingSub = pollWhileVisible(() => this.simulationService.chargerRuissellement(commune.code), INTERVALLE_POLLING_MS)
      .pipe(takeWhile(resultat => resultat.statut === 'EN_COURS', true))
      .subscribe({
        next: (resultat) => {
          this.ruissellement = resultat;
          if (resultat.statut === 'EN_COURS') return;

          this.ruissellementEnCours = false;
          if (resultat.statut === 'ECHEC') {
            this.ruissellementErreur = resultat.erreur || "Échec du calcul de ruissellement pour cette commune.";
            return;
          }
          this.afficherRuissellementSurCarte();
        },
        error: (err) => {
          this.ruissellementEnCours = false;
          this.ruissellementErreur = err?.error?.erreur || "Échec du calcul de ruissellement. Une nouvelle tentative est possible.";
        },
      });
  }

  /** Pas du curseur, déduit des deux premiers niveaux (grille régulière, NIVEAUX_PAR_DEFAUT). */
  get pasNiveau(): number {
    const niveaux = this.simulation?.niveaux ?? [0, 1];
    return niveaux.length > 1 ? Math.round((niveaux[1] - niveaux[0]) * 100) / 100 : 1;
  }

  get niveauMax(): number {
    const niveaux = this.simulation?.niveaux ?? [0];
    return niveaux[niveaux.length - 1] ?? 0;
  }

  onNiveauChange(): void {
    this.majPolygoneZone();
    this.majCouleurAdresses();
  }

  /** Profondeur d'eau à l'adresse pour le niveau du curseur ; null si non atteinte.
   * Distinct de `adresse.seuil_inondation` (seuil fixe). */
  profondeurActuelle(adresse: AdresseSimulee): number | null {
    if (adresse.seuil_inondation === null || this.niveauCourant < adresse.seuil_inondation) return null;
    if (adresse.altitude === null) return null;
    return Math.round((this.niveauCourant - adresse.altitude) * 100) / 100;
  }

  get adressesTriees(): AdresseSimulee[] {
    const adresses = this.adresses?.adresses ?? [];
    const direction = this.triDirection === 'asc' ? 1 : -1;
    return [...adresses].sort((a, b) => {
      if (this.triColonne === 'adresse') return a.adresse.localeCompare(b.adresse) * direction;
      if (this.triColonne === 'altitude') return ((a.altitude ?? -Infinity) - (b.altitude ?? -Infinity)) * direction;
      const pa = this.profondeurActuelle(a) ?? -Infinity;
      const pb = this.profondeurActuelle(b) ?? -Infinity;
      return (pa - pb) * direction;
    });
  }

  get nbAdressesTouchees(): number {
    return (this.adresses?.adresses ?? []).filter(a => this.profondeurActuelle(a) !== null).length;
  }

  trierPar(colonne: ColonneTri): void {
    if (this.triColonne === colonne) {
      this.triDirection = this.triDirection === 'asc' ? 'desc' : 'asc';
    } else {
      this.triColonne = colonne;
      this.triDirection = 'desc';
    }
  }

  exporterCsv(): void {
    if (!this.adresses) return;
    const lignes = [
      ['adresse', 'altitude_m', 'seuil_inondation_m', `profondeur_a_${this.niveauCourant}m`],
      ...this.adressesTriees.map(a => [
        a.adresse, a.altitude?.toString() ?? '', a.seuil_inondation?.toString() ?? 'jamais',
        this.profondeurActuelle(a)?.toString() ?? 'non touchée',
      ]),
    ];
    const csv = lignes.map(l => l.map(v => `"${String(v).replace(/"/g, '""')}"`).join(';')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const lien = document.createElement('a');
    lien.href = url;
    lien.download = `simulation-inondation-${this.communeSelectionnee?.code ?? 'commune'}.csv`;
    lien.click();
    URL.revokeObjectURL(url);
  }

  /** Zoom + centrage sur la commune dès sa sélection : la commune remplit la vue, sans
   * attendre la fin du calcul (demande utilisateur du 20/10/2026). Trace aussi son contour. */
  private cadrerSurCommune(commune: Commune): void {
    this.locationService.getCommuneContour(commune.code).subscribe({
      next: (geo) => this.runWhenMapReady(() => this.afficherContourCommune(geo?.contour ?? null)),
      error: () => { /* contour indisponible : le cadrage sur la zone simulée prendra le relais */ },
    });
  }

  private afficherContourCommune(geometry: Polygon | MultiPolygon | null): void {
    if (!this.map) return;
    const data: Feature = { type: 'Feature', properties: {}, geometry: geometry as any };
    const source = this.map.getSource(COMMUNE_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    if (source) source.setData(data as any);
    else if (geometry) {
      this.map.addSource(COMMUNE_SOURCE_ID, { type: 'geojson', data: data as any });
      this.map.addLayer({
        id: `${COMMUNE_SOURCE_ID}-layer`, type: 'line', source: COMMUNE_SOURCE_ID,
        paint: { 'line-color': '#1d4ed8', 'line-width': 2, 'line-dasharray': [2, 1] },
      });
    }
    if (!geometry) return;
    const anneaux = geometry.type === 'Polygon' ? geometry.coordinates : geometry.coordinates.flat();
    const coords = anneaux.flat() as [number, number][];
    if (!coords.length) return;
    const bounds = coords.reduce(
      (b, c) => b.extend(c as [number, number]),
      new maplibregl.LngLatBounds(coords[0], coords[0]),
    );
    this.map.fitBounds(bounds, { padding: 30, animate: true, duration: 600 });
  }

  /** Zones Géorisques de la commune choisie, dessinées en vecteur (voir GEORISQUES_COUCHES).
   * Rechargées à chaque changement de commune ou de scénario tant que la case est cochée. */
  georisquesMessage = '';

  majCoucheGeorisques(): void {
    this.georisquesMessage = '';
    const commune = this.communeSelectionnee;
    if (!this.coucheGeorisquesActive || !commune) {
      this.runWhenMapReady(() => this.dessinerZonesGeorisques(null));
      return;
    }
    const couche = this.georisquesCouche;
    this.georisquesMessage = 'Chargement des zones officielles…';
    this.simulationService.zonesGeorisques(commune.code, couche).subscribe({
      next: (r) => {
        if (commune !== this.communeSelectionnee || couche !== this.georisquesCouche) return;   // réponse périmée
        this.georisquesMessage = r.geometrie
          ? ''
          : `Aucune zone officielle « ${r.libelle} » sur cette commune : Géorisques ne couvre que les Territoires à Risque Important d'Inondation (TRI).`;
        this.runWhenMapReady(() => this.dessinerZonesGeorisques(r.geometrie));
      },
      error: (err) => {
        this.georisquesMessage = err?.error?.error || 'Zones Géorisques indisponibles pour le moment.';
        this.runWhenMapReady(() => this.dessinerZonesGeorisques(null));
      },
    });
  }

  private dessinerZonesGeorisques(geometrie: Polygon | MultiPolygon | null): void {
    if (!this.map) return;
    const data: Feature | FeatureCollection = geometrie
      ? { type: 'Feature', properties: {}, geometry: geometrie }
      : { type: 'FeatureCollection', features: [] };
    const source = this.map.getSource(GEORISQUES_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(data as any);
      return;
    }
    this.map.addSource(GEORISQUES_SOURCE_ID, { type: 'geojson', data: data as any });
    // Sous la zone simulée et les adresses, pour qu'elles restent lisibles par-dessus.
    const avant = this.map.getLayer(`${ZONE_SOURCE_ID}-fill`) ? `${ZONE_SOURCE_ID}-fill`
      : this.map.getLayer(`${ADRESSES_SOURCE_ID}-layer`) ? `${ADRESSES_SOURCE_ID}-layer` : undefined;
    this.map.addLayer({
      id: `${GEORISQUES_SOURCE_ID}-fill`, type: 'fill', source: GEORISQUES_SOURCE_ID,
      paint: { 'fill-color': '#7c3aed', 'fill-opacity': 0.35 },
    }, avant);
    this.map.addLayer({
      id: `${GEORISQUES_SOURCE_ID}-outline`, type: 'line', source: GEORISQUES_SOURCE_ID,
      paint: { 'line-color': '#5b21b6', 'line-width': 1.5 },
    }, avant);
  }

  private runWhenMapReady(cb: () => void): void {
    if (!this.map) return;
    if (this.mapPret) cb(); else this.map.once('load', cb);
  }

  /** Affiche la zone inondée et crée la couche d'adresses (vide) pour garder l'ordre des couches. */
  private afficherSurCarte(): void {
    this.runWhenMapReady(() => {
      this.creerCoucheAdresses();
      this.majPolygoneZone();
      this.cadrerSurZone();
    });
  }

  /** Remplit la couche d'adresses une fois chargées. */
  private rafraichirCoucheAdresses(): void {
    this.runWhenMapReady(() => {
      this.majCouleurAdresses();
      this.cadrerSurAdresses();
    });
  }

  private creerCoucheAdresses(): void {
    if (!this.map) return;
    if (this.map.getSource(ADRESSES_SOURCE_ID)) return;

    this.map.addSource(ADRESSES_SOURCE_ID, { type: 'geojson', data: this.adressesEnGeoJSON() as any });
    this.map.addLayer({
      id: `${ADRESSES_SOURCE_ID}-layer`, type: 'circle', source: ADRESSES_SOURCE_ID,
      paint: {
        'circle-radius': 5,
        'circle-stroke-width': 1,
        'circle-stroke-color': '#fff',
        'circle-color': '#6b7280',
      },
    });
    this.map.on('click', `${ADRESSES_SOURCE_ID}-layer`, (e) => {
      const feature = e.features?.[0];
      if (!feature) return;
      const props = feature.properties as any;
      const profondeur = props.profondeur_actuelle;
      const texte = profondeur === null || profondeur === undefined
        ? `${props.adresse}\nNon touchée à ce niveau (altitude ${props.altitude ?? '?'}m)`
        : `${props.adresse}\n${profondeur}m d'eau simulée (altitude ${props.altitude ?? '?'}m)`;
      new maplibregl.Popup({ offset: 10 }).setLngLat((feature.geometry as Point).coordinates as [number, number])
        .setText(texte).addTo(this.map!);
    });
    this.map.on('mouseenter', `${ADRESSES_SOURCE_ID}-layer`, () => { this.map!.getCanvas().style.cursor = 'pointer'; });
    this.map.on('mouseleave', `${ADRESSES_SOURCE_ID}-layer`, () => { this.map!.getCanvas().style.cursor = ''; });
  }

  /** `profondeur_actuelle` est recalculée et réécrite dans les features à chaque changement de
   * niveau (voir majCouleurAdresses) -- ce n'est PAS une nouvelle requête réseau, juste
   * source.setData() sur des données déjà en mémoire côté client. Vide tant que les adresses
   * n'ont pas été chargées (voir chargerAdresses). */
  get aDesAdressesAffichees(): boolean {
    return (this.adresses?.adresses?.length ?? 0) > 0 && this.coucheRiviereActive;
  }

  private adressesEnGeoJSON(): FeatureCollection<Point> {
    const adresses = this.adresses?.adresses ?? [];
    return {
      type: 'FeatureCollection',
      features: adresses.map((a): Feature<Point> => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [a.lon, a.lat] },
        properties: {
          adresse: a.adresse,
          altitude: a.altitude,
          seuil_inondation: a.seuil_inondation,
          profondeur_actuelle: this.profondeurActuelle(a),
        },
      })),
    };
  }

  /** Couleur data-driven sur `seuil_inondation` : gris = jamais touchée, rouge = touchée au niveau
   * courant, bleu = pas encore atteinte. */
  private majCouleurAdresses(): void {
    if (!this.map) return;
    const source = this.map.getSource(ADRESSES_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    if (!source) return;
    source.setData(this.adressesEnGeoJSON() as any);

    const layerId = `${ADRESSES_SOURCE_ID}-layer`;
    if (!this.map.getLayer(layerId)) return;
    // Gravité par HAUTEUR d'eau simulée (inspiré de la grille bluemapping, volet vitesse en
    // moins : le modèle "baignoire" ne calcule pas de vitesse). Seuils SEUILS_GRAVITE.
    this.map.setPaintProperty(layerId, 'circle-color', [
      'case',
      ['==', ['get', 'seuil_inondation'], null], '#6b7280',
      ['==', ['get', 'profondeur_actuelle'], null], '#2563eb',
      ['<=', ['get', 'profondeur_actuelle'], SEUILS_GRAVITE.limite], '#fbbf24',
      ['<=', ['get', 'profondeur_actuelle'], SEUILS_GRAVITE.modere], '#f97316',
      '#dc2626',
    ]);
  }

  private majPolygoneZone(): void {
    if (!this.map || !this.simulation) return;
    const palier = (this.simulation.paliers ?? []).find(p => p.niveau === this.niveauCourant);
    const geometry = palier?.polygone_geojson ?? null;
    const data: Feature | FeatureCollection = geometry
      ? { type: 'Feature', properties: {}, geometry }
      : { type: 'FeatureCollection', features: [] };

    const source = this.map.getSource(ZONE_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(data as any);
      return;
    }
    this.map.addSource(ZONE_SOURCE_ID, { type: 'geojson', data: data as any });
    this.map.addLayer({
      id: `${ZONE_SOURCE_ID}-fill`, type: 'fill', source: ZONE_SOURCE_ID,
      paint: { 'fill-color': '#2563eb', 'fill-opacity': 0.25 },
    }, `${ADRESSES_SOURCE_ID}-layer`);
    this.map.addLayer({
      id: `${ZONE_SOURCE_ID}-outline`, type: 'line', source: ZONE_SOURCE_ID,
      paint: { 'line-color': '#1d4ed8', 'line-width': 1.5 },
    }, `${ADRESSES_SOURCE_ID}-layer`);
  }

  /** Cadrage initial sur la zone inondée, puis sur les adresses (cadrerSurAdresses). */
  private cadrerSurZone(): void {
    if (!this.map) return;
    const palier = (this.simulation?.paliers ?? []).find(p => p.niveau === this.niveauCourant);
    const geometry = palier?.polygone_geojson;
    if (!geometry) return;
    const coords = geometry.type === 'Polygon' ? geometry.coordinates[0] : geometry.coordinates.flatMap(p => p[0]);
    if (!coords || coords.length === 0) return;
    const bounds = coords.reduce(
      (b, [lng, lat]) => b.extend([lng, lat] as [number, number]),
      new maplibregl.LngLatBounds(coords[0] as [number, number], coords[0] as [number, number]),
    );
    this.map.fitBounds(bounds, { padding: 40, maxZoom: 15, animate: false });
  }

  private cadrerSurAdresses(): void {
    const adresses = this.adresses?.adresses ?? [];
    if (!this.map || adresses.length === 0) return;
    const premiere = adresses[0];
    const bounds = new maplibregl.LngLatBounds([premiere.lon, premiere.lat], [premiere.lon, premiere.lat]);
    adresses.forEach(a => bounds.extend([a.lon, a.lat]));
    this.map.fitBounds(bounds, { padding: 40, maxZoom: 15, animate: false });
  }

  /** Visibilité de chaque couche selon son interrupteur ; la couche adresses n'est pas concernée. */
  private majVisibiliteCouches(): void {
    if (!this.map) return;
    const visibiliteRiviere = this.coucheRiviereActive ? 'visible' : 'none';
    const visibiliteRuissellement = this.coucheRuissellementActive ? 'visible' : 'none';
    for (const id of [`${ZONE_SOURCE_ID}-fill`, `${ZONE_SOURCE_ID}-outline`]) {
      if (this.map.getLayer(id)) this.map.setLayoutProperty(id, 'visibility', visibiliteRiviere);
    }
    if (this.map.getLayer(`${RUISSELLEMENT_SOURCE_ID}-layer`)) {
      this.map.setLayoutProperty(`${RUISSELLEMENT_SOURCE_ID}-layer`, 'visibility', visibiliteRuissellement);
    }
  }

  private afficherRuissellementSurCarte(): void {
    this.runWhenMapReady(() => {
      this.creerOuMajCoucheRuissellement();
      this.cadrerSurRuissellement();
    });
  }

  /** Carré à la taille réelle d'une case de grille, en degrés (suit le zoom), comme
   * core/ruissellement.py:_polygone_cellule. */
  private carreGrille(lon: number, lat: number, pasMetres: number): Polygon {
    const demiLat = (pasMetres / 2) / METRES_PAR_DEGRE_LAT;
    const demiLon = (pasMetres / 2) / (METRES_PAR_DEGRE_LAT * Math.max(Math.cos(lat * Math.PI / 180), 0.1));
    return {
      type: 'Polygon',
      coordinates: [[
        [lon - demiLon, lat - demiLat], [lon + demiLon, lat - demiLat],
        [lon + demiLon, lat + demiLat], [lon - demiLon, lat + demiLat],
        [lon - demiLon, lat - demiLat],
      ]],
    };
  }

  /** Grille de carrés pleins (un heatmap, en pixels et flouté, rend mal une grille régulière).
   * Couleur par paliers sur `accumulation`, transparente sous le premier seuil. Seuils empiriques
   * (Portets, Bordeaux). */
  private creerOuMajCoucheRuissellement(): void {
    if (!this.map || !this.ruissellement) return;
    const points = this.ruissellement.points ?? [];
    const pasMetres = this.ruissellement.pas_metres ?? 75;
    const data: FeatureCollection<Polygon> = {
      type: 'FeatureCollection',
      features: points.map((p): Feature<Polygon> => ({
        type: 'Feature',
        geometry: this.carreGrille(p.lon, p.lat, pasMetres),
        properties: { accumulation: p.accumulation },
      })),
    };

    const source = this.map.getSource(RUISSELLEMENT_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(data as any);
      return;
    }

    this.map.addSource(RUISSELLEMENT_SOURCE_ID, { type: 'geojson', data: data as any });
    // `before` seulement si la couche adresses existe : MapLibre refuse une couche inexistante.
    const avant = this.map.getLayer(`${ADRESSES_SOURCE_ID}-layer`) ? `${ADRESSES_SOURCE_ID}-layer` : undefined;
    this.map.addLayer({
      id: `${RUISSELLEMENT_SOURCE_ID}-layer`, type: 'fill', source: RUISSELLEMENT_SOURCE_ID,
      layout: { visibility: this.coucheRuissellementActive ? 'visible' : 'none' },
      paint: {
        'fill-opacity': 0.55,
        'fill-color': [
          'step', ['get', 'accumulation'],
          'rgba(0,0,0,0)', 5, '#fde047', 20, '#fb923c', 50, '#dc2626', 150, '#7f1d1d',
        ],
      },
    }, avant);
    this.map.on('click', `${RUISSELLEMENT_SOURCE_ID}-layer`, (e) => {
      const feature = e.features?.[0];
      if (!feature) return;
      const accumulation = (feature.properties as any).accumulation;
      new maplibregl.Popup({ offset: 10 }).setLngLat(e.lngLat)
        .setText(`Accumulation relative : ${accumulation} (plus c'est élevé, plus l'eau s'y concentre)`)
        .addTo(this.map!);
    });
  }

  private cadrerSurRuissellement(): void {
    const points = this.ruissellement?.points ?? [];
    if (!this.map || points.length === 0) return;
    const premier = points[0];
    const bounds = new maplibregl.LngLatBounds([premier.lon, premier.lat], [premier.lon, premier.lat]);
    points.forEach(p => bounds.extend([p.lon, p.lat]));
    this.map.fitBounds(bounds, { padding: 40, maxZoom: 15, animate: false });
  }
}
