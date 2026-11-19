import { Component, OnInit, OnDestroy, AfterViewInit, Input, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { styleCarte } from '../../../utils/carte-style';
import maplibregl from 'maplibre-gl';
import * as turf from '@turf/turf';
import { CrisisService } from '../../../../services/crisis.service';
import { forkJoin, Subscription } from 'rxjs';
import { Crisis } from '../../../models/crisis.model';
import { OfferService } from '../../../../services/offer.service';
import { Offer } from '../../../models/offer.model';
import { RequestService } from '../../../../services/request.service';
import { Request } from '../../../models/request.model';
import { GeolocationService } from '../../../../services/geolocation.service';
import { PositionEquipeService } from '../../../../services/position-equipe.service';
import { NoeudMeshUtilisateurService } from '../../../../services/noeud-mesh-utilisateur.service';
import { NoeudUtilisateurMeshtasticService } from '../../../../services/noeud-utilisateur-meshtastic.service';
import { PointOperationnelService } from '../../../../services/point-operationnel.service';
import type { FeatureCollection, Geometry, Polygon } from 'geojson';
import { AuthService } from '../../../../auth/services/auth.service';
import { PersonneVulnerableService } from '../../../../services/vulnerabilite.service';
import { InformationService } from '../../../../services/information.service';
import { PointOperationnel, CentreAccueilPublic } from '../../../models/point-operationnel.model';
import { VeilleService } from '../../../../services/veille.service';
import {
  EvenementRoutier, LIBELLES_ETAT_CIRCULATION, LIBELLES_ETAT_SURCOTE, LIBELLES_GRAVITE_ANTENNE,
  LIBELLES_TENDANCE_EAU, ObservationMeteo, PluiePrevue, PrecipitationsHiver, RafalesPrevues, CelluleOrage,
  StationCarburant,
  VentPrevu, sensDeCirculation, technologiesCoupees, variationEau,
} from '../../../models/veille.model';
import { AnimationVent, GrilleVent, decoderChampVent } from './vent-anime';

interface LayerVisibility {
  crises: boolean;
  requests: boolean;
  offers: boolean;
  informations: boolean;
  positions: boolean;
  personnelSecourisme: boolean;
  centresTous: boolean;
  centresHebergement: boolean;
  postesSecours: boolean;
  benevolesPompiers: boolean;
  /** Nœuds personnels des intervenants, et eux seuls : position firmware remontée pendant une
   * mission active. Tout le RESTE du réseau radio (relais, passerelles, répéteurs entendus,
   * liaisons mesurées, couverture calculée) a quitté cette carte le 10/11/2026 pour
   * /admin/carte-radio — voir CarteRadioComponent pour le pourquoi. */
  noeudsMeshCore: boolean;
  noeudsMeshtastic: boolean;
  /** Veille du territoire : événements du réseau routier national et stations de carburant,
   * lus dans la copie que tient NOTRE serveur (voir VeilleService). Chargés à la demande, pour
   * la seule emprise affichée. */
  evenementsRoutiers: boolean;
  stationsCarburant: boolean;
  stationsMeteo: boolean;
  /** Pluie prévue dans les trois heures (images nationales, voir VeilleService.pluiePrevue). */
  pluie: boolean;
  /** Rafales prévues dans les trois heures, sur la même réglette de temps que la pluie. */
  rafales: boolean;
  /** Neige, verglas et grêle prévus dans les trois heures, sur la même réglette. */
  hiver: boolean;
  /** Orages selon les relevés radar (19/11/2026) : contours des cellules de pluie intense, et
   * couloir estimé sur une heure. Rafraîchi toutes les deux minutes tant qu'il est affiché. */
  orages: boolean;
  /** Éclairs vus par le satellite MTG dans l'heure de données la plus récente (19/11/2026). */
  eclairs: boolean;
  /** Impacts Blitzortung, à titre indicatif (19/11/2026). */
  blitzortung: boolean;
  /** Tronçons de cours d'eau surveillés par Vigicrues, colorés par niveau de vigilance. */
  vigilanceCrues: boolean;
  /** Surfaces brûlées des trente derniers jours (EFFIS). */
  zonesBrulees: boolean;
  /** « Personne sensible dans les environs » : un cercle par fiche du registre, jamais un point.
   * Proposé à tous les acteurs institutionnels (les cercles ne disent rien du registre) ; chargé à la demande. */
  secteursVulnerables: boolean;
  /** Foyers actifs vus par satellite depuis 48 h (NASA FIRMS), sources fixes grisées. */
  foyersActifs: boolean;
  /** Massifs colorés par risque d'avalanche (bulletins de Météo-France). */
  avalanche: boolean;
  /** Arrêtés de circulation des collectivités (DiaLog) : fermetures, poids lourds, alternats. */
  arretesCirculation: boolean;
  /** Vitesses et état du trafic sur les routes nationales (stations de comptage de Bison Futé). */
  circulation: boolean;
  /** Hauteurs d'eau mesurées en rivière (stations Hub'Eau), colorées par tendance. */
  hauteursEau: boolean;
  /** Niveau de la mer aux marégraphes (Shom), colorés par surcote estimée. */
  niveauxMer: boolean;
  /** Antennes mobiles déclarées en panne ou en maintenance (Arcep). */
  antennesMobiles: boolean;
  /** Qualité de l'air estimée dans les grandes villes (OpenWeather). */
  qualiteAir: boolean;
  /** Vent prévu, animé : des particules portées par le champ de vent. */
  vent: boolean;
  /** Défibrillateurs déclarés en service (base nationale Géo'DAE). */
  defibrillateurs: boolean;
  /** Séismes des trente derniers jours (BCSF-Rénass), tirs de carrière compris. */
  seismes: boolean;
  /** Balises de radioactivité ambiante du réseau Téléray (ASNR). */
  radioactivite: boolean;
}

// Codes et libellés secourisme/soins (OfferSerializer.offer_type_nom, PointOperationnelSerializer.type_code).
const OFFER_TYPE_SOINS = 'Soins médicaux et paramédicaux';
const POINT_TYPE_SECOURS = 'SECOURS';
const POINT_TYPE_HEBERGEMENT = 'HEBERGEMENT';
const POSTE_SECOURS_ICON_ID = 'poste-secours-icon';

@Component({
  selector: 'app-map',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './map.component.html',
  styleUrl: './map.component.scss'
})
export class MapComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('mapContainer') mapContainer!: ElementRef;

  @Input() crises: Crisis[] = [];
  @Input() requests: Request[] = [];
  @Input() offers: Offer[] = [];
  @Input() informations: any[] = [];
  // Center of France by default, will be updated to user location if available
  @Input() center: [number, number] = [2.2137, 46.2276];
  @Input() zoom: number = 5;

  // Positions d'équipe : institutionnels seulement (case non rendue sinon).
  isInstitutional = false;

  // Panneau des calques replié par défaut (gênant sur mobile une fois déplié).
  layersPanelOpen = false;

  layerVisibility: LayerVisibility = {
    crises: true,
    requests: true,
    offers: true,
    informations: true,
    positions: true,
    personnelSecourisme: true,
    centresTous: true,
    centresHebergement: true,
    postesSecours: true,
    // Annuaire de bénévoles : masqué et chargé à la demande (voir DOCUMENTATION.md, § 6.3).
    benevolesPompiers: false,
    // Nœuds personnels MeshCore : position firmware, seulement pendant une mission active
    // (bridge.py, boucle_positions_missions).
    noeudsMeshCore: true,
    // Nœuds personnels Meshtastic : même règle (positions_en_mission).
    noeudsMeshtastic: true,
    // Veille : masquée et chargée à la demande, comme l'annuaire de bénévoles.
    evenementsRoutiers: false,
    stationsCarburant: false,
    stationsMeteo: false,
    pluie: false,
    rafales: false,
    hiver: false,
    orages: false,
    eclairs: false,
    blitzortung: false,
    vigilanceCrues: false,
    zonesBrulees: false,
    secteursVulnerables: false,
    foyersActifs: false,
    avalanche: false,
    arretesCirculation: false,
    circulation: false,
    hauteursEau: false,
    niveauxMer: false,
    antennesMobiles: false,
    qualiteAir: false,
    vent: false,
    defibrillateurs: false,
    seismes: false,
    radioactivite: false,
  };

  private map: maplibregl.Map | null = null;
  private crisisCircle: any[] = [];
  private requestGeoJSON: FeatureCollection<Geometry> | null = null;
  private proposalGeoJSON: FeatureCollection<Geometry> | null = null;
  private informationsGeoJSON: FeatureCollection<Geometry> | null = null;
  private teamPositionsGeoJSON: FeatureCollection<Geometry> | null = null;
  private noeudsMeshCoreGeoJSON: FeatureCollection<Geometry> | null = null;
  private noeudsMeshtasticGeoJSON: FeatureCollection<Geometry> | null = null;
  private personnelSecourismeGeoJSON: FeatureCollection<Geometry> | null = null;
  private benevolesPompiersGeoJSON: FeatureCollection<Geometry> | null = null;
  private centresTousGeoJSON: FeatureCollection<Geometry> | null = null;
  private centresHebergementGeoJSON: FeatureCollection<Geometry> | null = null;
  private postesSecoursGeoJSON: FeatureCollection<Geometry> | null = null;
  private subscription: Subscription | null = null;
  // MapLibre fixe la taille du canvas à l'initialisation : resize() à chaque changement de
  // taille du conteneur (repli de la sidebar, fenêtre).
  private resizeObserver: ResizeObserver | null = null;

  constructor(private crisisService: CrisisService,
              private requestService: RequestService,
              private offerService: OfferService,
              private informationService: InformationService,
              private geolocationService: GeolocationService,
              private positionEquipeService: PositionEquipeService,
              private pointOperationnelService: PointOperationnelService,
              private noeudMeshUtilisateurService: NoeudMeshUtilisateurService,
              private noeudUtilisateurMeshtasticService: NoeudUtilisateurMeshtasticService,
              private veilleService: VeilleService,
              private authService: AuthService,
              private personneVulnerableService: PersonneVulnerableService) {}
  ngOnInit(): void {
    this.isInstitutional = this.authService.isAdmin();

    // Load user location and center map on it if available, otherwise keep default center
    this.loadUserLocation();

    // If crises, requests, or offers were not passed in as inputs, load them from the API
    if (this.crises.length === 0) {
      this.loadCrises();
    }
    if (this.requests.length === 0 || this.offers.length === 0) {
      this.loadHelpData();
    }
    if (this.isInstitutional) {
      this.loadTeamPositions();
      this.loadCentres();
      // Annuaire de bénévoles chargé à la demande (onLayerToggle) : jusqu'à ~1300 fiches.
    }
    // Centres d'accueil et postes de secours : publics (PointOperationnelViewSet.carte_publique).
    this.loadCentresPublics();
    if (this.isInstitutional) {
      this.loadNoeudsMeshCore();
      this.loadNoeudsMeshtastic();
    }
  }

  /** Ré-applique la visibilité des calques sans recharger, sauf l'annuaire bénévoles et les relais
   * MeshCore, chargés à la première activation (minimisation des données de position). */
  onLayerToggle(): void {
    if (this.layerVisibility.secteursVulnerables && !this.secteursVulnerablesCharges) {
      this.secteursVulnerablesCharges = true;
      this.chargerSecteursVulnerables();
    }
    if (this.layerVisibility.benevolesPompiers && !this.benevolesPompiersCharges) {
      this.benevolesPompiersCharges = true;
      this.loadBenevolesPompiers();
    }
    this.applyClusterVisibility();
    this.applyLayerVisibility('team-positions-layer', this.layerVisibility.positions);
    this.applyLayerVisibility('team-positions-label', this.layerVisibility.positions);
    this.applyLayerVisibility('noeuds-meshcore-layer', this.layerVisibility.noeudsMeshCore);
    this.applyLayerVisibility('noeuds-meshcore-label', this.layerVisibility.noeudsMeshCore);
    this.applyLayerVisibility('noeuds-meshtastic-layer', this.layerVisibility.noeudsMeshtastic);
    this.applyLayerVisibility('noeuds-meshtastic-label', this.layerVisibility.noeudsMeshtastic);
    this.applyLayerVisibility('location-radius', this.layerVisibility.crises);
    this.applyLayerVisibility('personnel-secourisme-layer', this.layerVisibility.personnelSecourisme);
    this.applyLayerVisibility('centres-tous-layer', this.layerVisibility.centresTous);
    this.applyLayerVisibility('centres-hebergement-layer', this.layerVisibility.centresHebergement);
    this.applyLayerVisibility('postes-secours-layer', this.layerVisibility.postesSecours);
    this.applyLayerVisibility('benevoles-pompiers-layer', this.layerVisibility.benevolesPompiers);
    this.applyLayerVisibility('evenements-routiers-layer', this.layerVisibility.evenementsRoutiers);
    this.applyLayerVisibility('stations-carburant-layer', this.layerVisibility.stationsCarburant);
    this.applyLayerVisibility('stations-meteo-layer', this.layerVisibility.stationsMeteo);
    this.applyLayerVisibility('vigilance-crues-layer', this.layerVisibility.vigilanceCrues);
    this.applyLayerVisibility('zones-brulees-layer', this.layerVisibility.zonesBrulees);
    this.applyLayerVisibility('orages-layer', this.layerVisibility.orages);
    this.applyLayerVisibility('orages-couloirs-layer', this.layerVisibility.orages);
    this.applyLayerVisibility('eclairs-layer', this.layerVisibility.eclairs);
    this.applyLayerVisibility('blitzortung-layer', this.layerVisibility.blitzortung);
    if ((this.layerVisibility.orages || this.layerVisibility.eclairs || this.layerVisibility.blitzortung)
        && !this.rafraichissementOrages) {
      // Une image radar toutes les cinq minutes : relire toutes les deux suffit.
      this.rafraichissementOrages = setInterval(() => this.rafraichirVeille(), 120_000);
    }
    this.applyLayerVisibility('secteurs-vulnerables-layer', this.layerVisibility.secteursVulnerables);
    this.applyLayerVisibility('foyers-actifs-layer', this.layerVisibility.foyersActifs);
    this.applyLayerVisibility('avalanche-layer', this.layerVisibility.avalanche);
    this.applyLayerVisibility('arretes-circulation-layer', this.layerVisibility.arretesCirculation);
    this.applyLayerVisibility('circulation-layer', this.layerVisibility.circulation);
    this.applyLayerVisibility('hauteurs-eau-layer', this.layerVisibility.hauteursEau);
    this.applyLayerVisibility('niveaux-mer-layer', this.layerVisibility.niveauxMer);
    this.applyLayerVisibility('antennes-mobiles-layer', this.layerVisibility.antennesMobiles);
    this.applyLayerVisibility('qualite-air-layer', this.layerVisibility.qualiteAir);
    this.applyLayerVisibility('defibrillateurs-layer', this.layerVisibility.defibrillateurs);
    this.applyLayerVisibility('seismes-layer', this.layerVisibility.seismes);
    this.applyLayerVisibility('radioactivite-layer', this.layerVisibility.radioactivite);
    this.basculerPrevisions();
    this.basculerVent();
    this.rafraichirVeille();
  }

  // ── Veille du territoire : routes et carburant ──────────────────────────────────────────

  /** Vrai quand le serveur a plafonné la réponse : l'emprise affichée est trop large pour tout
   * montrer, et la légende invite à zoomer plutôt que de laisser croire que c'est tout. */
  veilleTronquee = { routes: false, stations: false, meteo: false, arretes: false, defibrillateurs: false, seismes: false, circulation: false, hauteursEau: false,
                     antennes: false };
  private veilleSuitLaCarte = false;

  /** Charge routes et stations pour l'emprise affichée, si leur calque est coché. Rappelé à
   * chaque déplacement de la carte : ces couches sont nationales, on n'en lit que la fenêtre. */
  private rafraichirVeille(): void {
    if (!this.map) return;
    const { evenementsRoutiers, stationsCarburant, stationsMeteo, vigilanceCrues, zonesBrulees, avalanche,
            arretesCirculation, defibrillateurs, seismes, radioactivite, foyersActifs, circulation,
            hauteursEau, niveauxMer, antennesMobiles, qualiteAir, orages, eclairs, blitzortung } = this.layerVisibility;
    if (!evenementsRoutiers && !stationsCarburant && !stationsMeteo && !vigilanceCrues && !zonesBrulees
        && !avalanche && !arretesCirculation && !defibrillateurs && !seismes && !radioactivite
        && !foyersActifs && !circulation && !hauteursEau && !niveauxMer && !antennesMobiles
        && !qualiteAir && !orages && !eclairs && !blitzortung) return;
    if (!this.veilleSuitLaCarte) {
      this.veilleSuitLaCarte = true;
      this.map.on('moveend', () => this.rafraichirVeille());
    }
    const bornes = this.map.getBounds();
    const borne = (valeur: number, limite: number) => +Math.max(-limite, Math.min(limite, valeur)).toFixed(4);
    const bbox: [number, number, number, number] = [
      borne(bornes.getWest(), 180), borne(bornes.getSouth(), 90),
      borne(bornes.getEast(), 180), borne(bornes.getNorth(), 90),
    ];
    if (qualiteAir) {
      this.veilleService.qualiteAir({ bbox }).subscribe({
        next: (reponse) => {
          const noms: Record<string, string> = { pm2_5: 'PM2,5', pm10: 'PM10', no2: 'NO₂', o3: 'O₃', so2: 'SO₂' };
          this.afficherCoucheVeille('qualite-air', {
            type: 'FeatureCollection',
            features: reponse.resultats.map(p => ({
              type: 'Feature', geometry: { type: 'Point', coordinates: [p.longitude, p.latitude] },
              properties: {
                etat: p.indice ?? 0,
                infobulle: `<strong>Qualité de l'air à ${this.echapper(p.nom)}</strong>`
                  + (p.indice != null ? `<br>Indice ${p.indice} sur 5 : ${this.echapper(p.libelle)}` : '<br>Estimation trop ancienne')
                  + (p.indice != null ? '<br>' + Object.keys(noms).filter(cle => p.composants[cle] != null)
                      .map(cle => `${noms[cle]} ${String(p.composants[cle]).replace('.', ',')}`).join(' · ') + ' µg/m³' : '')
                  + (p.pire_24h != null && p.pire_24h > (p.indice ?? 0) && p.pire_24h_le
                    ? `<br>D'ici 24 h : jusqu'à ${p.pire_24h} (${this.echapper(p.pire_24h_libelle)}) vers ${new Date(p.pire_24h_le).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}` : '')
                  + `<br><small>${this.echapper(reponse.source)}. Estimation par modèle, pas une mesure de station ; `
                  + 'l\'indice (1 à 5) n\'est pas l\'indice ATMO.</small>',
              },
            })),
          // Du vert (bon) au violet (très mauvais) ; gris : estimation trop ancienne.
          }, ['match', ['get', 'etat'], 1, '#2f9e44', 2, '#a3c93a', 3, '#e6b800', 4, '#f97316', 5, '#7c1d6f', '#9ca3af'],
          this.layerVisibility.qualiteAir);
        },
        error: () => {},
      });
    }
    if (antennesMobiles) {
      this.veilleService.antennesIndisponibles({ bbox }).subscribe({
        next: (reponse) => {
          this.veilleTronquee.antennes = reponse.tronque;
          const jour = (instant: string) => new Date(instant).toLocaleDateString('fr-FR');
          this.afficherCoucheVeille('antennes-mobiles', {
            type: 'FeatureCollection',
            features: reponse.resultats.map(a => {
              const coupees = technologiesCoupees(a.technologies);
              return {
                type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates: [a.longitude, a.latitude] },
                properties: {
                  etat: a.gravite,
                  infobulle: `<strong>Antenne ${this.echapper(a.operateur)}</strong>`
                    + (a.commune ? ` — ${this.echapper(a.commune)}` : '')
                    + `<br>${LIBELLES_GRAVITE_ANTENNE[a.gravite]}`
                    + (coupees ? `<br>Hors service : ${coupees}` : '')
                    + `<br>${a.motif === 'MAINTENANCE' ? 'Maintenance' : 'Incident'} depuis le ${jour(a.depuis)}`
                    + (a.debut_declare ? '' : ' (date de notre première observation)')
                    + '<br><small>Source : Arcep, déclarations des opérateurs'
                    + (reponse.jour_du_fichier ? `, état du ${jour(reponse.jour_du_fichier)}` : '')
                    + '. Une antenne en panne n\'est pas une zone sans réseau : une voisine peut couvrir.</small>',
                },
              };
            }),
          // Rouge : voix et données coupées. Orange : service partiel. Gris : déclarée sans coupure.
          }, ['match', ['get', 'etat'], 'TOTALE', '#c81e1e', 'PARTIELLE', '#f97316', '#9ca3af'],
          this.layerVisibility.antennesMobiles);
        },
        error: () => {},
      });
    }
    if (niveauxMer) {
      this.veilleService.niveauxMer({ bbox }).subscribe({
        next: (reponse) => {
          const metres = (valeur: number) => valeur.toFixed(2).replace('.', ',');
          const quand = (instant: string) => new Date(instant).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
          this.afficherCoucheVeille('niveaux-mer', {
            type: 'FeatureCollection',
            features: reponse.resultats.map(m => ({
              type: 'Feature', geometry: { type: 'Point', coordinates: [m.longitude, m.latitude] },
              properties: {
                etat: m.etat,
                infobulle: `<strong>Marégraphe de ${this.echapper(m.nom)}</strong>`
                  + (m.niveau_m != null ? `<br>Niveau mesuré : ${metres(m.niveau_m)} m` : '<br>Pas de mesure récente')
                  + (m.surcote_cm != null
                    ? `<br><strong>${LIBELLES_ETAT_SURCOTE[m.etat]}</strong> : ${m.surcote_cm > 0 ? '+' : ''}${m.surcote_cm} cm par rapport à la marée calculée (± ${Math.round(m.incertitude_cm ?? 0)} cm)`
                    : (m.niveau_m != null ? '<br>Marée pas encore calculée pour ce marégraphe' : ''))
                  + (m.pleine_mer_le && m.pleine_mer_niveau_m != null
                    ? `<br>Prochaine pleine mer vers ${new Date(m.pleine_mer_le).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })} : ${metres(m.pleine_mer_niveau_m)} m si l'écart se maintient` : '')
                  + (m.maximum_m != null ? `<br>Plus haut mesuré en ${m.jours_ajustes} jours : ${metres(m.maximum_m)} m` : '')
                  + (m.niveau_le ? `<br>Mesuré le ${quand(m.niveau_le)}` : '')
                  + '<br><small>Source : Shom (REFMAR), mesure brute. La marée et la surcote sont une estimation de ce serveur, pas une prédiction officielle ni une alerte.</small>',
              },
            })),
          // Rouge : forte surcote. Orange : marquée. Bleu : niveau attendu. Gris : sans estimation.
          }, ['match', ['get', 'etat'], 'FORTE', '#c81e1e', 'MARQUEE', '#f97316', 'NORMALE', '#0e7490', '#9ca3af'],
          this.layerVisibility.niveauxMer);
        },
        error: () => {},
      });
    }
    if (hauteursEau) {
      this.veilleService.hauteursEau({ bbox }).subscribe({
        next: (reponse) => {
          this.veilleTronquee.hauteursEau = reponse.tronque;
          this.afficherCoucheVeille('hauteurs-eau', {
            type: 'FeatureCollection',
            features: reponse.resultats.map(e => ({
              type: 'Feature', geometry: { type: 'Point', coordinates: [e.longitude, e.latitude] },
              properties: {
                etat: e.tendance,
                infobulle: `<strong>${this.echapper(e.nom)}</strong>`
                  + `<br>${LIBELLES_TENDANCE_EAU[e.tendance]}`
                  + (e.variation_1h_cm != null ? ` : ${variationEau(e.variation_1h_cm)} en 1 h` : '')
                  + (e.variation_3h_cm != null ? `${e.variation_1h_cm != null ? ',' : ' :'} ${variationEau(e.variation_3h_cm)} en 3 h` : '')
                  + (e.hauteur_m != null ? `<br>Hauteur à l'échelle : ${e.hauteur_m.toFixed(2).replace('.', ',')} m` : '')
                  + (e.debit_m3s != null ? `<br>Débit : ${e.debit_m3s >= 10 ? Math.round(e.debit_m3s) : e.debit_m3s.toFixed(1).replace('.', ',')} m³/s` : '')
                  + (e.hauteur_le ? `<br>Mesuré le ${new Date(e.hauteur_le).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}` : '')
                  + '<br><small>Source : Hub\'Eau. Mesure brute, non validée ; la hauteur ne se compare qu\'à elle-même.</small>',
              },
            })),
          // Rouge : hausse rapide. Orange : hausse. Bleu : stable. Bleu-gris : baisse. Gris : sans mesure.
          }, ['match', ['get', 'etat'], 'HAUSSE_RAPIDE', '#c81e1e', 'HAUSSE', '#f97316', 'STABLE', '#2563eb',
              'BAISSE', '#64748b', '#9ca3af'], this.layerVisibility.hauteursEau);
        },
        error: () => {},
      });
    }
    if (circulation) {
      this.veilleService.circulation({ bbox }, true).subscribe({
        next: (reponse) => {
          this.veilleTronquee.circulation = reponse.tronque;
          const heure = (instant: string | null) => instant
            ? new Date(instant).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) : '';
          this.afficherTracesVeille('circulation', 'line', {
            type: 'FeatureCollection',
            features: reponse.resultats.filter(t => t.trace).map(t => ({
              type: 'Feature', geometry: t.trace as Geometry,
              properties: {
                etat: t.etat, cote: t.cote,
                infobulle: `<strong>${this.echapper(t.axe)} ${sensDeCirculation(t.sens)}</strong>`
                  + `<br>${LIBELLES_ETAT_CIRCULATION[t.etat]}`
                  + (t.origine === 'OFFICIEL' ? ' — état donné par l\'exploitant'
                    : t.origine === 'ESTIME' ? ' — estimé d\'après la vitesse' : '')
                  + (t.vitesse_kmh != null ? `<br>${Math.round(t.vitesse_kmh)} km/h` : '')
                  + (t.vitesse_kmh != null && t.vitesse_habituelle_kmh != null ? ` (d'habitude ${t.vitesse_habituelle_kmh})` : '')
                  + (t.debit_veh_h != null ? `${t.vitesse_kmh != null ? ', ' : '<br>'}${t.debit_veh_h} véhicules/h` : '')
                  + (t.mesure_le ? `<br>Mesuré à ${heure(t.mesure_le)}` : '')
                  + '<br><small>Source : Bison Futé. Routes nationales et autoroutes de l\'État seulement ; '
                  + 'le trait relie les deux bouts du tronçon, sans suivre la route.</small>',
              },
            })),
          }, {
            // Vert : fluide. Orange : dense. Rouge : saturé. Noir : bloqué. Gris : sans mesure.
            'line-color': ['match', ['get', 'etat'], 'FLUIDE', '#2f9e44', 'DENSE', '#f59e0b',
                           'SATURE', '#c81e1e', 'BLOQUE', '#111827', '#9ca3af'],
            'line-width': ['match', ['get', 'etat'], 'FLUIDE', 3, 'INCONNU', 2, 5],
            // Les deux sens d'une route partagent le même trait : chacun est décalé de son côté.
            'line-offset': ['*', ['get', 'cote'], 3],
          }, this.layerVisibility.circulation);
        },
        error: () => {},
      });
    }
    if (evenementsRoutiers) {
      this.veilleService.evenementsRoutiers({ bbox }).subscribe({
        next: (reponse) => {
          this.veilleTronquee.routes = reponse.tronque;
          this.afficherCoucheVeille('evenements-routiers', this.evenementsVersGeoJSON(reponse.resultats),
            // Rouge : la route ne passe plus. Orange : accident, obstacle, conditions. Gris : le reste.
            ['match', ['get', 'etat'], 'grave', '#c81e1e', 'attention', '#f97316', '#6b7280'],
            this.layerVisibility.evenementsRoutiers);
        },
        error: () => {},
      });
    }
    if (stationsMeteo) this.rafraichirStationsMeteo(bbox);
    if (vigilanceCrues) {
      this.veilleService.vigilanceCrues({ bbox }, true).subscribe({
        next: (reponse) => this.afficherTracesVeille('vigilance-crues', 'line', {
          type: 'FeatureCollection',
          features: reponse.resultats.filter(t => t.trace).map(t => ({
            type: 'Feature', geometry: t.trace as Geometry,
            properties: {
              niveau: t.niveau,
              infobulle: `<strong>${this.echapper(t.nom)}</strong><br>Vigilance crues : ${this.echapper(t.couleur)}`
                + '<br><small>Source : Vigicrues. Seuls les principaux cours d\'eau sont surveillés.</small>',
            },
          })),
        }, {
          // Vert, jaune, orange, rouge : les couleurs de Vigicrues.
          'line-color': ['match', ['get', 'niveau'], 4, '#c81e1e', 3, '#f97316', 2, '#e6b800', '#2f9e44'],
          'line-width': ['match', ['get', 'niveau'], 1, 2.5, 4.5],
        }, this.layerVisibility.vigilanceCrues),
        error: () => {},
      });
    }
    if (foyersActifs) {
      this.veilleService.foyersActifs({ bbox }, true).subscribe({
        next: (reponse) => this.afficherCoucheVeille('foyers-actifs', {
          type: 'FeatureCollection',
          features: reponse.resultats.map(f => ({
            type: 'Feature', geometry: { type: 'Point', coordinates: [f.longitude, f.latitude] },
            properties: {
              etat: f.source_fixe ? 'fixe' : 'grave',
              infobulle: (f.source_fixe
                  ? '<strong>Source de chaleur fixe</strong><br>Vue au même endroit jour après jour : probablement une usine ou une torchère, pas un feu.'
                  : '<strong>Foyer détecté par satellite — à vérifier</strong><br>Peut être un feu, un écobuage ou un brûlage.')
                + `<br>${new Date(f.date).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}, confiance ${this.echapper(f.confiance)}`
                + (f.puissance_mw != null ? `, ${Math.round(f.puissance_mw)} MW` : '')
                + '<br><small>Source : NASA FIRMS, environ 3 h après le passage du satellite</small>',
            },
          })),
        // Rouge : foyer à vérifier. Gris : source fixe (usine, torchère).
        }, ['match', ['get', 'etat'], 'grave', '#dc2626', '#9ca3af'], this.layerVisibility.foyersActifs),
        error: () => {},
      });
    }
    if (defibrillateurs) {
      this.veilleService.defibrillateurs({ bbox }).subscribe({
        next: (reponse) => {
          this.veilleTronquee.defibrillateurs = reponse.tronque;
          this.afficherCoucheVeille('defibrillateurs', {
            type: 'FeatureCollection',
            features: reponse.resultats.map(d => ({
              type: 'Feature', geometry: { type: 'Point', coordinates: [d.longitude, d.latitude] },
              properties: {
                etat: d.acces_libre ? 'ok' : 'attention',
                infobulle: `<strong>${this.echapper(d.nom || 'Défibrillateur')}</strong><br>${this.echapper(d.adresse)}`
                  + (d.emplacement ? `<br>Emplacement : ${this.echapper(d.emplacement)}` : '')
                  + `<br>${this.echapper(d.acces || 'Accès non précisé')}${d.acces_libre ? ', accès libre' : ', accès non libre'}`
                  + (d.disponibilite ? `<br>Disponibilité déclarée : ${this.echapper(d.disponibilite)}` : '')
                  + '<br><small>Déclaré par l\'exploitant (Géo\'DAE), non vérifié. Arrêt cardiaque : appelez le 15.</small>',
              },
            })),
          // Vert : accès libre. Gris-vert : il faut qu'on vous ouvre.
          }, ['match', ['get', 'etat'], 'ok', '#16a34a', '#84a98c'], this.layerVisibility.defibrillateurs);
        },
        error: () => {},
      });
    }
    if (seismes) {
      this.veilleService.seismes({ bbox }).subscribe({
        next: (reponse) => {
          this.veilleTronquee.seismes = reponse.tronque;
          this.afficherCoucheVeille('seismes', {
            type: 'FeatureCollection',
            features: reponse.resultats.map(s => ({
              type: 'Feature', geometry: { type: 'Point', coordinates: [s.longitude, s.latitude] },
              properties: {
                etat: s.nature !== 'earthquake' ? 'autre' : s.magnitude >= 3 ? 'grave' : 'attention',
                infobulle: `<strong>${this.echapper(s.nature_libelle)} — magnitude ${s.magnitude}</strong>`
                  + (s.lieu ? `<br>près de ${this.echapper(s.lieu)}` : '')
                  + `<br>${new Date(s.date).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}`
                  + (s.profondeur_km != null ? `, à ${Math.round(s.profondeur_km)} km de profondeur` : '')
                  + '<br><small>Source : BCSF-Rénass et observatoires de l\'IPGP</small>',
              },
            })),
          // Rouge : séisme de magnitude 3 ou plus. Orange : séisme plus petit. Gris : tir de carrière, explosion.
          }, ['match', ['get', 'etat'], 'grave', '#c81e1e', 'attention', '#f97316', '#9ca3af'], this.layerVisibility.seismes);
        },
        error: () => {},
      });
    }
    if (radioactivite) {
      this.veilleService.radioactivite({ bbox }).subscribe({
        next: (reponse) => this.afficherCoucheVeille('radioactivite', {
          type: 'FeatureCollection',
          features: reponse.resultats.map(b => ({
            type: 'Feature', geometry: { type: 'Point', coordinates: [b.longitude, b.latitude] },
            properties: {
              etat: 'neutre',
              infobulle: `<strong>Balise ${this.echapper(b.nom)}</strong>`
                + `<br>${Math.round(b.debit_nsv_h)} nSv/h`
                + (b.bruit_de_fond_nsv_h != null ? ` (niveau habituel : ${Math.round(b.bruit_de_fond_nsv_h)} nSv/h)` : '')
                + `<br>Mesuré à ${new Date(b.mesure_le).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`
                + (b.valide ? '' : ' — mesure non validée')
                + '<br><small>Réseau Téléray (ASNR). Pas une alerte : la pluie fait monter la mesure.</small>',
            },
          })),
        // Une seule couleur, voulue : colorer par valeur ferait lire comme une alerte ce qui n'en est pas une.
        }, '#7c3aed', this.layerVisibility.radioactivite),
        error: () => {},
      });
    }
    if (arretesCirculation) {
      this.veilleService.arretesCirculation({ bbox }, true).subscribe({
        next: (reponse) => {
          this.veilleTronquee.arretes = reponse.tronque;
          const jour = (instant: string | null) => instant ? new Date(instant).toLocaleDateString('fr-FR') : '';
          this.afficherTracesVeille('arretes-circulation', 'line', {
            type: 'FeatureCollection',
            features: reponse.resultats.filter(a => a.trace).map(a => ({
              type: 'Feature', geometry: a.trace as Geometry,
              properties: {
                categorie: a.categorie,
                infobulle: `<strong>${this.echapper(a.categorie_libelle)}`
                  + (a.tonnage_max != null ? ` de plus de ${a.tonnage_max} t` : '') + '</strong>'
                  + (a.voies ? `<br>${this.echapper(a.voies)}` : '')
                  + (a.description ? `<br>${this.echapper(a.description)}` : '')
                  + `<br>${a.fin ? `Jusqu'au ${jour(a.fin)}` : 'Arrêté permanent'}`
                  + (a.autorite ? ` — ${this.echapper(a.autorite)}` : '')
                  + (a.url ? `<br><a href="${this.echapper(a.url)}" target="_blank" rel="noopener noreferrer">Voir l'arrêté</a>` : '')
                  + '<br><small>Source : DiaLog. Seules les collectivités qui y publient figurent ici.</small>',
              },
            })),
          }, {
            // Rouge : interdite à tous. Violet : poids lourds. Orange : alternat.
            'line-color': ['match', ['get', 'categorie'], 'FERMETURE', '#c81e1e', 'POIDS_LOURDS', '#7c3aed', '#f97316'],
            'line-width': 4,
          }, this.layerVisibility.arretesCirculation);
        },
        error: () => {},
      });
    }
    if (avalanche) {
      this.veilleService.risqueAvalanche({ bbox }, true).subscribe({
        next: (reponse) => this.afficherTracesVeille('avalanche', 'fill', {
          type: 'FeatureCollection',
          features: reponse.resultats.filter(m => m.trace).map(m => ({
            type: 'Feature', geometry: m.trace as Geometry,
            properties: {
              risque: m.risque ?? 0,
              infobulle: `<strong>${this.echapper(m.nom)}</strong> (${this.echapper(m.chaine)})`
                + (m.risque != null
                  ? `<br>Risque d'avalanche : ${m.risque} — ${this.echapper(reponse.libelles[String(m.risque)] ?? '')}`
                    + (m.risque_demain != null ? `<br>Demain : ${m.risque_demain}` : '')
                    + (m.resume ? `<br>${this.echapper(m.resume).replace(/\n/g, '<br>')}` : '')
                  : '<br>Pas de bulletin en ce moment')
                + '<br><small>Source : Météo-France. Indice pour tout le massif, pas pour une pente.</small>',
            },
          })),
        }, {
          // Échelle européenne : 1 vert clair, 2 jaune, 3 orange, 4 rouge, 5 rouge sombre.
          'fill-color': ['match', ['get', 'risque'], 5, '#7f1d1d', 4, '#ff0000', 3, '#ff9900', 2, '#ffff00', 1, '#ccff66', '#9ca3af'],
          'fill-opacity': 0.4, 'fill-outline-color': '#374151',
        }, this.layerVisibility.avalanche),
        error: () => {},
      });
    }
    if (blitzortung) {
      this.veilleService.blitzortung({ bbox }).subscribe({
        next: (reponse) => {
          const features = reponse.features.map(f => ({
            ...f, properties: {
              ...f.properties,
              infobulle: `<strong>Impact de foudre (Blitzortung)</strong><br>${new Date((f.properties as { instant: string }).instant).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`
                + '<br><small>Informations Blitzortung données à titre indicatif</small>',
            },
          }));
          this.afficherCoucheVeille('blitzortung', { type: 'FeatureCollection', features } as FeatureCollection<Geometry>,
            ['interpolate', ['linear'], ['get', 'age_min'], 0, '#ffffff', 10, '#fde047', 60, '#a8a29e'],
            this.layerVisibility.blitzortung);
        },
        error: () => {},
      });
    }
    if (eclairs) {
      this.veilleService.foudre({ bbox }).subscribe({
        next: (reponse) => {
          this.eclairsDerniereDonnee = reponse.derniere_donnee;
          const features = reponse.features.map(f => ({
            ...f, properties: {
              ...f.properties,
              infobulle: `<strong>Éclair vu par satellite</strong><br>${new Date((f.properties as { instant: string }).instant).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`
                + '<br><small>MTG (EUMETSAT) : position à quelques kilomètres près, 10 à 20 min de retard</small>',
            },
          }));
          this.afficherCoucheVeille('eclairs', { type: 'FeatureCollection', features } as FeatureCollection<Geometry>,
            // Du plus récent (jaune vif) au plus ancien (gris) sur l'heure affichée.
            ['interpolate', ['linear'], ['get', 'age_min'], 0, '#facc15', 20, '#f97316', 60, '#9ca3af'],
            this.layerVisibility.eclairs);
        },
        error: () => {},
      });
    }
    if (orages) {
      this.veilleService.orages({ bbox }).subscribe({
        next: (reponse) => {
          this.oragesHeureImage = reponse.heure_image;
          this.oragesPerime = reponse.perime;
          const cellules = reponse.cellules;
          // Le couloir d'abord : il passe SOUS les cellules.
          this.afficherTracesVeille('orages-couloirs', 'line', {
            type: 'FeatureCollection',
            features: cellules.filter(c => c.couloir).map(c => ({
              type: 'Feature', geometry: c.couloir as Geometry,
              properties: { infobulle: this.infobulleOrage(c) },
            })),
          }, { 'line-color': '#1e40af', 'line-width': 1.5, 'line-dasharray': [2, 2], 'line-opacity': 0.8 },
          this.layerVisibility.orages);
          this.afficherTracesVeille('orages', 'fill', {
            type: 'FeatureCollection',
            features: cellules.map(c => ({
              type: 'Feature', geometry: c.contour as Geometry,
              properties: { intensite: c.releves.intensite_max_mmh, infobulle: this.infobulleOrage(c) },
            })),
          }, {
            // Paliers d'intensité : 30, 50, 100 mm/h.
            'fill-color': ['step', ['get', 'intensite'], '#f59e0b', 50, '#dc2626', 100, '#7e22ce'],
            'fill-opacity': 0.55, 'fill-outline-color': '#450a0a',
          }, this.layerVisibility.orages);
        },
        error: () => {},
      });
    }
    if (zonesBrulees) {
      this.veilleService.zonesBrulees({ bbox }, true).subscribe({
        next: (reponse) => this.afficherTracesVeille('zones-brulees', 'fill', {
          type: 'FeatureCollection',
          features: reponse.resultats.filter(z => z.trace).map(z => ({
            type: 'Feature', geometry: z.trace as Geometry,
            properties: {
              infobulle: `<strong>Surface brûlée — ${this.echapper(z.commune_nom)}</strong>`
                + `<br>${z.surface_ha ?? '?'} ha`
                + (z.date_feu ? `, le ${new Date(z.date_feu).toLocaleDateString('fr-FR')}` : '')
                + '<br><small>Vue par satellite, avec un jour de retard — © UE, Copernicus EFFIS</small>',
            },
          })),
        }, { 'fill-color': '#7c2d12', 'fill-opacity': 0.5, 'fill-outline-color': '#431407' },
        this.layerVisibility.zonesBrulees),
        error: () => {},
      });
    }
    if (stationsCarburant) {
      this.veilleService.stationsCarburant({ bbox }).subscribe({
        next: (reponse) => {
          this.veilleTronquee.stations = reponse.tronque;
          this.afficherCoucheVeille('stations-carburant', this.stationsVersGeoJSON(reponse.resultats),
            // Rouge : plus rien à délivrer. Orange : un carburant manque. Vert : rien de signalé.
            ['match', ['get', 'etat'], 'grave', '#c81e1e', 'attention', '#f97316', '#0f766e'],
            this.layerVisibility.stationsCarburant);
        },
        error: () => {},
      });
    }
  }

  // ── Outil : zone atteignable depuis un point ─────────────────────────────────────────────
  //
  // « Jusqu'où va-t-on en dix minutes depuis la caserne ? » On choisit une durée et un mode,
  // on clique un point, le contour s'affiche. Le calcul est demandé par notre serveur.

  readonly DUREES_ZONE = [5, 10, 15, 20, 30, 45];
  zone = {
    minutes: 10, mode: 'voiture' as 'voiture' | 'pied',
    /** Le prochain clic sur la carte désigne le point de départ. */
    attendUnPoint: false, enCours: false, affichee: false, erreur: '',
  };

  choisirPointDeLaZone(): void {
    if (!this.map) return;
    this.zone.attendUnPoint = true;
    this.zone.erreur = '';
    this.map.getCanvas().style.cursor = 'crosshair';
    this.map.once('click', (e) => {
      this.map!.getCanvas().style.cursor = '';
      this.zone.attendUnPoint = false;
      this.calculerZone(e.lngLat.lat, e.lngLat.lng);
    });
  }

  calculerZone(lat: number, lon: number): void {
    this.zone.enCours = true;
    this.zone.erreur = '';
    this.geolocationService.zoneAtteignable(lat, lon, this.zone.minutes, this.zone.mode).subscribe({
      next: (reponse) => {
        this.zone.enCours = false;
        this.zone.affichee = true;
        this.dessinerZone(reponse.contour as Geometry, lat, lon);
      },
      error: (erreur) => {
        this.zone.enCours = false;
        this.zone.erreur = erreur?.error?.detail || 'Le calcul n\'a pas abouti.';
      },
    });
  }

  effacerZone(): void {
    this.zone.affichee = false;
    this.zone.erreur = '';
    const vide: FeatureCollection<Geometry> = { type: 'FeatureCollection', features: [] };
    (this.map?.getSource('zone-atteignable') as maplibregl.GeoJSONSource | undefined)?.setData(vide);
  }

  private dessinerZone(contour: Geometry, lat: number, lon: number): void {
    const data: FeatureCollection<Geometry> = {
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', geometry: contour, properties: {} },
        { type: 'Feature', geometry: { type: 'Point', coordinates: [lon, lat] }, properties: {} },
      ],
    };
    this.runWhenMapReady(() => {
      if (!this.map) return;
      const source = this.map.getSource('zone-atteignable') as maplibregl.GeoJSONSource | undefined;
      if (source) { source.setData(data); return; }
      this.map.addSource('zone-atteignable', { type: 'geojson', data });
      const premierTexte = this.map.getStyle().layers?.find(calque => calque.type === 'symbol')?.id;
      this.map.addLayer({
        id: 'zone-atteignable-layer', type: 'fill', source: 'zone-atteignable',
        filter: ['!=', ['geometry-type'], 'Point'],
        paint: { 'fill-color': '#2563eb', 'fill-opacity': 0.18, 'fill-outline-color': '#1d4ed8' },
      }, premierTexte);
      this.map.addLayer({
        id: 'zone-atteignable-point', type: 'circle', source: 'zone-atteignable',
        filter: ['==', ['geometry-type'], 'Point'],
        paint: { 'circle-color': '#1d4ed8', 'circle-radius': 6, 'circle-stroke-width': 2, 'circle-stroke-color': '#fff' },
      });
    });
  }

  // ── Vent animé : des particules portées par le champ de vent prévu ──────────────────────

  @ViewChild('toileVent') toileVent?: ElementRef<HTMLCanvasElement>;
  vent: VentPrevu | null = null;
  /** Heure du champ de vent en cours d'animation. */
  echeanceVent: string | null = null;
  private animationVent: AnimationVent | null = null;
  /** Champs déjà décodés, par calcul et par heure : changer d'heure ne redemande rien. */
  private grillesVent = new Map<string, GrilleVent>();
  private rafraichissementVent: ReturnType<typeof setInterval> | null = null;

  /** Appelé à chaque changement de calque : charge le vent à la première activation, le relit
   * toutes les dix minutes, et arrête l'animation quand le calque est décoché. */
  private basculerVent(): void {
    if (!this.layerVisibility.vent) {
      this.animationVent?.arreter();
      if (this.rafraichissementVent) { clearInterval(this.rafraichissementVent); this.rafraichissementVent = null; }
      return;
    }
    if (this.rafraichissementVent) { this.afficherVent(); return; }
    this.chargerVent();
    this.rafraichissementVent = setInterval(() => this.chargerVent(), 10 * 60 * 1000);
  }

  private chargerVent(): void {
    this.veilleService.ventPrevu().subscribe({
      next: (vent) => { this.vent = vent; this.afficherVent(); },
      error: () => {},
    });
  }

  /** Anime l'heure de vent la plus proche de celle de la réglette de prévision, ou de l'heure
   * qu'il est si aucune prévision n'est affichée. */
  private afficherVent(): void {
    const vent = this.vent;
    if (!this.layerVisibility.vent || !vent?.echeances.length) return;
    const instant = this.echeancePrevision ? new Date(this.echeancePrevision).getTime() : Date.now();
    const echeance = vent.echeances[this.rangLePlusProche(vent.echeances, instant)];
    const cle = `${vent.calcul}|${echeance}`;
    const connue = this.grillesVent.get(cle);
    if (connue) { this.animerVent(echeance, connue); return; }
    this.veilleService.ventPrevu(echeance).subscribe({
      next: (reponse) => {
        if (!reponse.champ) return;
        try {
          const grille = decoderChampVent(reponse.champ);
          this.grillesVent.set(cle, grille);
          this.animerVent(echeance, grille);
        } catch { /* champ illisible : on garde l'animation précédente */ }
      },
      error: () => {},
    });
  }

  private animerVent(echeance: string, grille: GrilleVent): void {
    this.echeanceVent = echeance;
    this.runWhenMapReady(() => {
      const toile = this.toileVent?.nativeElement;
      if (!this.map || !toile || !this.layerVisibility.vent) return;
      if (!this.animationVent) {
        this.animationVent = new AnimationVent(this.map, toile);
        // Les traînes sont dessinées à l'écran : dès que la carte bouge, elles sont fausses.
        this.map.on('move', () => this.animationVent?.effacer());
        this.map.on('resize', () => { if (this.layerVisibility.vent) this.animationVent?.redimensionner(); });
      }
      this.animationVent.definirGrille(grille);
      this.animationVent.demarrer();
    });
  }

  // ── Pluie et rafales prévues : une image nationale par quart d'heure, une réglette de temps ──

  pluie: PluiePrevue | null = null;
  rafales: RafalesPrevues | null = null;
  hiver: PrecipitationsHiver | null = null;
  /** Échéance choisie sur la réglette ; `null` tant qu'on n'y a pas touché : la carte suit
   * alors l'heure qu'il est. Les deux calques partagent ce choix. */
  echeanceChoisie: string | null = null;
  animationPrevision: ReturnType<typeof setInterval> | null = null;
  private rafraichissementPrevision: ReturnType<typeof setInterval> | null = null;
  private previsionsSuivies = { pluie: false, rafales: false, hiver: false };
  private readonly SERIES_PREVISION = ['pluie', 'rafales', 'hiver'] as const;

  /** Appelé à chaque changement de calque : charge une série à sa première activation, puis
   * relit celles qui sont cochées toutes les cinq minutes. */
  private basculerPrevisions(): void {
    this.applyLayerVisibility('pluie-layer', this.layerVisibility.pluie);
    this.applyLayerVisibility('rafales-layer', this.layerVisibility.rafales);
    this.applyLayerVisibility('hiver-layer', this.layerVisibility.hiver);
    for (const serie of this.SERIES_PREVISION) {
      const visible = this.layerVisibility[serie];
      if (visible && !this.previsionsSuivies[serie]) this.chargerPrevision(serie);
      this.previsionsSuivies[serie] = visible;
    }
    if (!this.SERIES_PREVISION.some(serie => this.layerVisibility[serie])) {
      this.arreterAnimationPrevision();
      if (this.rafraichissementPrevision) { clearInterval(this.rafraichissementPrevision); this.rafraichissementPrevision = null; }
      return;
    }
    // L'autre calque peut ne pas porter l'échéance affichée : on le recale.
    this.afficherPrevisions();
    if (this.rafraichissementPrevision) return;
    this.rafraichissementPrevision = setInterval(() => {
      if (this.layerVisibility.pluie) this.chargerPrevision('pluie');
      if (this.layerVisibility.rafales) this.chargerPrevision('rafales');
      if (this.layerVisibility.hiver) this.chargerPrevision('hiver');
    }, 5 * 60 * 1000);
  }

  private chargerPrevision(serie: 'pluie' | 'rafales' | 'hiver'): void {
    const fin = { error: () => {} };
    const afficher = () => this.afficherPrevisions();
    if (serie === 'pluie') {
      this.veilleService.pluiePrevue().subscribe({ next: (donnees) => { this.pluie = donnees; afficher(); }, ...fin });
    } else if (serie === 'rafales') {
      this.veilleService.rafalesPrevues().subscribe({ next: (donnees) => { this.rafales = donnees; afficher(); }, ...fin });
    } else {
      this.veilleService.precipitationsHiver().subscribe({ next: (donnees) => { this.hiver = donnees; afficher(); }, ...fin });
    }
  }

  /** Les quarts d'heure de la réglette : ceux des calques de prévision cochés, réunis. */
  get echeancesPrevision(): string[] {
    const toutes = new Set<string>();
    if (this.layerVisibility.pluie) this.pluie?.echeances.forEach(e => toutes.add(e));
    if (this.layerVisibility.rafales) this.rafales?.echeances.forEach(e => toutes.add(e));
    if (this.layerVisibility.hiver) this.hiver?.echeances.forEach(e => toutes.add(e));
    return [...toutes].sort((a, b) => new Date(a).getTime() - new Date(b).getTime());
  }

  /** Rang, dans `echeances`, de la plus proche de `instant` (millisecondes). */
  private rangLePlusProche(echeances: string[], instant: number): number {
    let meilleur = 0;
    echeances.forEach((echeance, i) => {
      if (Math.abs(new Date(echeance).getTime() - instant)
          < Math.abs(new Date(echeances[meilleur]).getTime() - instant)) meilleur = i;
    });
    return meilleur;
  }

  /** Rang de l'échéance affichée : celle qu'on a choisie si elle existe encore, sinon la plus
   * proche d'elle -- ou de l'heure qu'il est tant qu'on n'a rien choisi. */
  get indicePrevision(): number {
    const echeances = this.echeancesPrevision;
    const choisie = this.echeanceChoisie ? echeances.indexOf(this.echeanceChoisie) : -1;
    if (choisie >= 0) return choisie;
    return this.rangLePlusProche(echeances, this.echeanceChoisie ? new Date(this.echeanceChoisie).getTime() : Date.now());
  }

  get echeancePrevision(): string | null {
    return this.echeancesPrevision[this.indicePrevision] ?? null;
  }

  /** « maintenant », « dans 45 min », « dans 1 h 30 », « il y a 15 min ». */
  get ecartPrevision(): string {
    const echeance = this.echeancePrevision;
    if (!echeance) return '';
    const minutes = Math.round((new Date(echeance).getTime() - Date.now()) / 60000);
    if (Math.abs(minutes) < 8) return 'maintenant';
    const absolu = Math.abs(minutes);
    const duree = absolu < 60 ? `${absolu} min`
      : `${Math.floor(absolu / 60)} h${absolu % 60 ? ' ' + String(absolu % 60).padStart(2, '0') : ''}`;
    return minutes > 0 ? `dans ${duree}` : `il y a ${duree}`;
  }

  choisirEcheance(indice: number): void {
    const echeances = this.echeancesPrevision;
    this.echeanceChoisie = echeances[Math.max(0, Math.min(echeances.length - 1, +indice))] ?? null;
    this.afficherPrevisions();
  }

  basculerAnimationPrevision(): void {
    if (this.animationPrevision) { this.arreterAnimationPrevision(); return; }
    this.animationPrevision = setInterval(() => {
      const nombre = this.echeancesPrevision.length;
      if (nombre < 2) return;
      this.choisirEcheance((this.indicePrevision + 1) % nombre);
    }, 900);
  }

  private arreterAnimationPrevision(): void {
    if (this.animationPrevision) { clearInterval(this.animationPrevision); this.animationPrevision = null; }
  }

  /** Pose, pour chaque calque de prévision coché, l'image de l'échéance choisie. */
  private afficherPrevisions(): void {
    const echeance = this.echeancePrevision;
    // Le vent suit l'heure de la réglette.
    this.afficherVent();
    if (!echeance) return;
    if (this.layerVisibility.pluie && this.pluie) {
      this.poserImagePrevision('pluie', this.pluie, echeance, 0.7, e => this.veilleService.imagePluieUrl(e));
    }
    if (this.layerVisibility.rafales && this.rafales) {
      this.poserImagePrevision('rafales', this.rafales, echeance, 0.8, e => this.veilleService.imageRafalesUrl(e));
    }
    if (this.layerVisibility.hiver && this.hiver) {
      this.poserImagePrevision('hiver', this.hiver, echeance, 0.85, e => this.veilleService.imagePrecipitationHiverUrl(e));
    }
  }

  /** Pose l'image d'une série sur la carte, SOUS les noms de lieux du fond de carte (et donc
   * sous tous nos calques) : une prévision ne doit rien masquer. Si la série n'a pas l'échéance
   * demandée (une image manquée au relevé), elle montre sa plus proche. */
  private poserImagePrevision(nom: 'pluie' | 'rafales' | 'hiver', serie: PluiePrevue, echeance: string,
                              opacite: number, adresse: (echeance: string) => string): void {
    if (!serie.echeances.length) return;
    const montree = serie.echeances.includes(echeance) ? echeance
      : serie.echeances[this.rangLePlusProche(serie.echeances, new Date(echeance).getTime())];
    const url = adresse(montree);
    const coordinates = serie.coins as [[number, number], [number, number], [number, number], [number, number]];
    this.runWhenMapReady(() => {
      if (!this.map) return;
      const source = this.map.getSource(nom) as maplibregl.ImageSource | undefined;
      if (source) {
        source.updateImage({ url, coordinates });
        return;
      }
      this.map.addSource(nom, { type: 'image', url, coordinates });
      const premierTexte = this.map.getStyle().layers?.find(calque => calque.type === 'symbol')?.id;
      this.map.addLayer({
        id: `${nom}-layer`, type: 'raster', source: nom,
        layout: { visibility: this.layerVisibility[nom] ? 'visible' : 'none' },
        // « nearest » pour ce que nous peignons nous-mêmes : des classes nettes, pas un dégradé
        // inventé entre deux teintes.
        paint: { 'raster-opacity': opacite, 'raster-fade-duration': 0,
                 'raster-resampling': nom === 'pluie' ? 'linear' : 'nearest' },
      }, premierTexte);
    });
  }

  private rafraichirStationsMeteo(bbox: [number, number, number, number]): void {
    this.veilleService.observationsMeteo({ bbox }).subscribe({
      next: (reponse) => {
        this.veilleTronquee.meteo = reponse.tronque;
        this.afficherCoucheVeille('stations-meteo', this.mesuresVersGeoJSON(reponse.resultats),
          // Orange : rafale de 80 km/h ou plus, ou 20 mm de pluie dans l'heure. Bleu : le reste.
          ['match', ['get', 'etat'], 'attention', '#f97316', '#2563eb'],
          this.layerVisibility.stationsMeteo);
      },
      error: () => {},
    });
  }

  private mesuresVersGeoJSON(stations: ObservationMeteo[]): FeatureCollection<Geometry> {
    const heure = (instant: string | null) => instant
      ? new Date(instant).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) : '';
    return {
      type: 'FeatureCollection',
      features: stations.map(s => {
        const rafales = [s.rafale_kmh, s.rafale_1h_kmh].filter((v): v is number => v != null);
        const rafale = rafales.length ? Math.max(...rafales) : null;
        const lignes = [
          s.temperature_c != null ? `Température : ${s.temperature_c} °C` : '',
          s.vent_kmh != null ? `Vent moyen : ${s.vent_kmh} km/h` : '',
          rafale != null ? `Rafale : ${rafale} km/h` : '',
          s.pluie_1h_mm != null ? `Pluie sur 1 h : ${s.pluie_1h_mm} mm` : '',
          s.pluie_24h_mm != null ? `Pluie cumulée sur ${s.heures_cumulees} h : ${s.pluie_24h_mm} mm` : '',
          s.neige_cm ? `Neige au sol : ${s.neige_cm} cm` : '',
        ].filter(Boolean);
        return {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [s.longitude, s.latitude] },
          properties: {
            etat: (rafale ?? 0) >= 80 || (s.pluie_1h_mm ?? 0) >= 20 ? 'attention' : 'ok',
            infobulle: `<strong>${this.echapper(s.nom || s.station)}</strong>`
              + (s.altitude_m != null ? ` (${s.altitude_m} m)` : '')
              + `<br>${lignes.join('<br>') || 'Aucune mesure'}`
              + `<br><small>Mesuré à ${heure(s.mesure_le)} — source : Météo-France</small>`,
          },
        };
      }),
    };
  }

  /** Les textes de ces couches viennent de flux extérieurs (exploitants routiers, stations) :
   * ils sont échappés avant d'entrer dans une infobulle. */
  private echapper(texte: string | null | undefined): string {
    return (texte ?? '').replace(/[&<>"']/g, c => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' } as Record<string, string>)[c]);
  }

  private evenementsVersGeoJSON(evenements: EvenementRoutier[]): FeatureCollection<Geometry> {
    const attention = ['ACCIDENT', 'OBSTACLE', 'CONDITIONS'];
    return {
      type: 'FeatureCollection',
      features: evenements.map(e => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [e.longitude, e.latitude] },
        properties: {
          etat: e.categorie === 'FERMETURE' ? 'grave' : attention.includes(e.categorie) ? 'attention' : 'autre',
          infobulle: `<strong>${this.echapper(e.categorie_libelle)} — ${this.echapper(e.route)}</strong>`
            + (e.commune_nom ? `<br>${this.echapper(e.commune_nom)}` : '')
            + `<br>${this.echapper(e.natures.join(' · '))}`
            + (e.description ? `<br>${this.echapper(e.description).replace(/\n/g, '<br>')}` : '')
            + '<br><small>Source : Bison Futé (réseau national)</small>',
        },
      })),
    };
  }

  private stationsVersGeoJSON(stations: StationCarburant[]): FeatureCollection<Geometry> {
    return {
      type: 'FeatureCollection',
      features: stations.map(s => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [s.longitude, s.latitude] },
        properties: {
          etat: !s.ruptures_temporaires.length ? 'ok' : s.carburants_disponibles.length ? 'attention' : 'grave',
          infobulle: `<strong>Station — ${this.echapper(s.ville)}</strong><br>${this.echapper(s.adresse)}`
            + `<br>Disponible : ${this.echapper(s.carburants_disponibles.join(', ')) || 'aucun carburant'}`
            + (s.ruptures_temporaires.length ? `<br>En rupture : ${this.echapper(s.ruptures_temporaires.join(', '))}` : '')
            + (s.automate_24_24 ? '<br>Automate 24 h/24' : '')
            + '<br><small>Source : prix-carburants.gouv.fr, déclaré par la station</small>',
        },
      })),
    };
  }

  /** Comme `afficherCoucheVeille`, pour des lignes ou des surfaces : posées sous les noms de
   * lieux du fond de carte, pour ne pas les masquer. */
  // ══ Personnes vulnérables : des secteurs, jamais des points ═══════════════════════════════
  private secteursVulnerablesCharges = false;
  /** Ce que la carte dit du calque une fois chargé (fiches non situées, relevé manquant). */
  noteSecteursVulnerables = '';

  /** Charge les cercles « personne sensible dans les environs ». Un cercle ne porte RIEN : le
   * seul texte affiché au clic est le libellé fixe rendu par le serveur. Le centre n'est pas le
   * domicile, et le cercle s'élargit en habitat isolé (core/secteurs_vulnerables.py). */
  private chargerSecteursVulnerables(): void {
    this.personneVulnerableService.secteurs().subscribe({
      next: (reponse) => {
        const libelle = this.echapper(reponse.libelle);
        this.afficherTracesVeille('secteurs-vulnerables', 'fill', {
          type: 'FeatureCollection',
          features: reponse.features.map(f => ({ ...f, properties: { infobulle: `<strong>${libelle}</strong>` } })),
        }, { 'fill-color': '#f97316', 'fill-opacity': 0.28, 'fill-outline-color': '#c2410c' },
        this.layerVisibility.secteursVulnerables);
        this.noteSecteursVulnerables = !reponse.releve_disponible
          ? 'relevé des adresses manquant : lancez la simulation d’inondation de la commune'
          : reponse.non_situees ? `${reponse.non_situees} fiche(s) non située(s)` : '';
      },
      error: () => {
        this.secteursVulnerablesCharges = false;
        this.noteSecteursVulnerables = 'secteurs indisponibles pour le moment';
      },
    });
  }

  oragesHeureImage: string | null = null;
  eclairsDerniereDonnee: string | null = null;
  oragesPerime = false;
  private rafraichissementOrages: ReturnType<typeof setInterval> | null = null;

  /** Infobulle d'une cellule : les trois natures d'information, sans les mélanger. */
  private infobulleOrage(c: CelluleOrage): string {
    const r = c.releves, e = c.estimations, p = c.prevision_meteo_france;
    let html = `<strong>${this.echapper(r.libelle)}</strong>`
      + `<br><small>Selon les relevés</small><br>jusqu'à ${Math.round(r.intensite_max_mmh)} mm/h sur ${Math.round(r.surface_km2)} km²`;
    if (r.rafale_mesuree) {
      html += `<br>rafale mesurée ${r.rafale_mesuree.kmh} km/h (${this.echapper(r.rafale_mesuree.station)})`;
    }
    if (r.doppler?.rotation) {
      html += `<br><strong>Rotation détectée</strong> (radar de ${this.echapper(r.doppler.rotation.radar)})`;
    }
    if (r.doppler?.grele?.probable) {
      html += `<br>grêle probable selon le radar`;
    }
    if (r.doppler?.divergence) {
      html += `<br>divergence forte près du sol`;
    }
    if (e.vitesse_kmh != null) {
      html += `<br><small>Nos estimations (qui ne sont pas des prévisions)</small><br>vers ${this.echapper(e.vers)}, ~${e.vitesse_kmh} km/h`;
      if (e.ligne_de_grain) html += '<br>forme de ligne de grain';
    }
    if (p.grele || p.rafale_kmh || p.grele_niveau) {
      html += '<br><small>Selon la prévision Météo-France</small><br>'
        + [p.grele ? 'grêle prévue' : '', p.grele_niveau ? `diagnostic : ${this.echapper(p.grele_niveau)}` : '',
           p.rafale_kmh ? `rafales ${p.rafale_kmh} km/h et plus` : ''].filter(Boolean).join(', ');
    }
    return html;
  }

  private afficherTracesVeille(sourceId: string, type: 'line' | 'fill', data: FeatureCollection<Geometry>,
                               paint: any, visible: boolean): void {
    this.runWhenMapReady(() => {
      if (!this.map) return;
      const layerId = `${sourceId}-layer`;
      const existante = this.map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined;
      if (existante) {
        existante.setData(data);
        return;
      }
      this.map.addSource(sourceId, { type: 'geojson', data });
      const premierTexte = this.map.getStyle().layers?.find(calque => calque.type === 'symbol')?.id;
      this.map.addLayer({
        id: layerId, type, source: sourceId,
        layout: { visibility: visible ? 'visible' : 'none' }, paint,
      } as maplibregl.LayerSpecification, premierTexte);
      this.map.on('click', layerId, (e) => {
        if (!e.features || e.features.length === 0) return;
        new maplibregl.Popup().setLngLat(e.lngLat)
          .setHTML((e.features[0].properties || {})['infobulle'] || '').addTo(this.map!);
      });
      this.map.on('mouseenter', layerId, () => { this.map!.getCanvas().style.cursor = 'pointer'; });
      this.map.on('mouseleave', layerId, () => { this.map!.getCanvas().style.cursor = ''; });
    });
  }

  private afficherCoucheVeille(sourceId: string, data: FeatureCollection<Geometry>,
                               couleur: any, visible: boolean): void {
    this.runWhenMapReady(() => {
      if (!this.map) return;
      const layerId = `${sourceId}-layer`;
      const existante = this.map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined;
      if (existante) {
        existante.setData(data);
        return;
      }
      this.map.addSource(sourceId, { type: 'geojson', data });
      this.map.addLayer({
        id: layerId, type: 'circle', source: sourceId,
        layout: { visibility: visible ? 'visible' : 'none' },
        paint: {
          'circle-color': couleur, 'circle-radius': 6,
          'circle-stroke-width': 2, 'circle-stroke-color': '#fff',
        },
      });
      this.map.on('click', layerId, (e) => {
        if (!e.features || e.features.length === 0) return;
        const coordinates = (e.features[0].geometry as GeoJSON.Point).coordinates.slice() as [number, number];
        new maplibregl.Popup().setLngLat(coordinates)
          .setHTML((e.features[0].properties || {})['infobulle'] || '').addTo(this.map!);
      });
      this.map.on('mouseenter', layerId, () => { this.map!.getCanvas().style.cursor = 'pointer'; });
      this.map.on('mouseleave', layerId, () => { this.map!.getCanvas().style.cursor = ''; });
    });
  }

  private applyLayerVisibility(layerId: string, visible: boolean): void {
    if (!this.map || !this.map.getLayer(layerId)) return;
    this.map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none');
  }

  /** Demandes/offres/signalements partagent une source clusterisée : les masquer retire leurs
   * features de la source, sinon les clusters les compteraient encore. */
  private applyClusterVisibility(): void {
    if (!this.map) return;
    const source = this.map.getSource('clusters') as maplibregl.GeoJSONSource | undefined;
    if (!source) return;
    source.setData(this.buildVisibleClusterData());
  }

  private buildVisibleClusterData(): FeatureCollection<Geometry> {
    const parts: any[] = [];
    if (this.layerVisibility.requests && this.requestGeoJSON) parts.push(...this.requestGeoJSON.features);
    if (this.layerVisibility.offers && this.proposalGeoJSON) parts.push(...this.proposalGeoJSON.features);
    if (this.layerVisibility.informations && this.informationsGeoJSON) parts.push(...this.informationsGeoJSON.features);
    return { type: 'FeatureCollection', features: parts };
  }

  /** MapLibre ne rejoue pas 'load' pour un listener ajouté après coup : les données arrivant par
   * API après l'initialisation, on vérifie isStyleLoaded(). */
  private runWhenMapReady(cb: () => void): void {
    if (!this.map) return;
    if (this.map.isStyleLoaded()) {
      cb();
    } else {
      this.map.once('load', cb);
    }
  }

  private loadUserLocation(): void {
    // Verify if there's a stored location in the GeolocationService and center the map on it if available
    const storedLocation = this.geolocationService.location$;
    storedLocation.subscribe((location: any) => {
      if (location) {
        // Center the map on the stored location
        this.aRecentre = true;
        this.center = [location.longitude, location.latitude];
        this.zoom = 9;
        
        // If the map is already initialized, fly to the new center and zoom
        if (this.map) {
          this.map.flyTo({
            center: this.center,
            zoom: this.zoom,
            duration: 2000
          });
        }
      }
    });

    // Recentrage sur la position de l'utilisateur SEULEMENT si elle est déjà connue ou déjà
    // autorisée : ouvrir une carte ne doit pas déclencher l'invite de permission. Sur iOS,
    // cette invite surgissait au chargement de la page publique, l'utilisateur la refusait
    // (réaction normale devant une demande qu'il n'a pas sollicitée), et Safari refusait
    // ensuite DÉFINITIVEMENT la géolocalisation pour tout le site — y compris pour un
    // signalement géolocalisé. Voir GeolocationService.positionSansInvite (07/11/2026).
    if (!this.geolocationService.hasPermission()) {
      this.geolocationService.positionSansInvite()
        .then((coords: any) => {
          if (!coords) {
            // Position inconnue et pas d'autorisation déjà accordée : même repli que si le GPS
            // avait échoué, sinon la carte resterait centrée sur la France entière.
            this.centerOnUserPostalCodeIfAvailable();
            return;
          }
          this.aRecentre = true;
          this.center = [coords.longitude, coords.latitude];
          this.zoom = 11;
          
          if (this.map) {
            this.map.flyTo({
              center: this.center,
              zoom: this.zoom,
              duration: 2000
            });
          }
        })
        .catch((error: any) => {
          console.log('Géolocalisation non disponible:', error.message);
          // GPS indisponible : repli sur le code postal du profil, s'il existe.
          this.centerOnUserPostalCodeIfAvailable();
        });
    }
  }

  private centerOnUserPostalCodeIfAvailable(): void {
    const postalCode = this.authService.getCurrentUser()?.postal_code;
    if (!postalCode) return;

    this.geolocationService.getCoordinates(postalCode).subscribe({
      next: (res) => {
        const feature = res?.features?.[0];
        const coordinates = feature?.geometry?.coordinates;
        if (!coordinates) return;

        this.aRecentre = true;
        this.center = [coordinates[0], coordinates[1]];
        this.zoom = 10;
        if (this.map) {
          this.map.flyTo({ center: this.center, zoom: this.zoom, duration: 2000 });
        }
      },
      error: () => {},
    });
  }

  ngAfterViewInit(): void {
    this.initializeMap();
    this.observeContainerResize();
  }

  // Garde le canvas aligné sur .map-container (voir resizeObserver).
  private observeContainerResize(): void {
    if (typeof ResizeObserver === 'undefined') return; // pas de support (SSR/anciens navigateurs) : dégrade sans casser
    this.resizeObserver = new ResizeObserver(() => this.map?.resize());
    this.resizeObserver.observe(this.mapContainer.nativeElement);
  }

  ngOnDestroy(): void {
    if (this.subscription) this.subscription.unsubscribe();
    if (this.resizeObserver) this.resizeObserver.disconnect();
    this.arreterAnimationPrevision();
    if (this.rafraichissementPrevision) clearInterval(this.rafraichissementPrevision);
    this.animationVent?.arreter();
    if (this.rafraichissementVent) clearInterval(this.rafraichissementVent);
    if (this.rafraichissementOrages) clearInterval(this.rafraichissementOrages);
    if (this.map) this.map.remove();
  }

  /** Vrai dès que la carte a été centrée sur la personne (GPS ou code postal du profil). */
  private aRecentre = false;

  /** Dernier repli, pour un compte institutionnel : s'ouvrir sur la crise en cours.
   *
   * Sur le poste fixe d'une mairie il n'y a ni GPS ni code postal au profil : la carte restait
   * sur l'Europe entière, la crise réduite à un point (vu le 18/11/2026). Ne prend jamais le
   * pas sur une position connue, et ne s'applique pas à la carte publique. */
  private centrerSurLaCriseEnCours(): void {
    if (this.aRecentre || !this.authService.isInstitutionalEffective?.()) return;
    const crise = this.crises.find(c => c.is_open !== false && c.latitude != null && c.longitude != null);
    if (!crise) return;
    this.center = [crise.longitude as number, crise.latitude as number];
    this.zoom = 11;
    this.map?.flyTo({ center: this.center, zoom: this.zoom, duration: 1500 });
  }

  loadCrises() {
    this.subscription = this.crisisService.getAll().subscribe({
      next: (crises) => {
        console.log('Données de crises reçues:', crises);
        this.crises = crises;
        if (this.map) {
          this.addCrisisMarkers();
        }
        this.centrerSurLaCriseEnCours();
      },
      error: (error) => console.error('Erreur API:', error)
    });
  }

  jsonToGeoJSON(data: any[], jitter: boolean = false): FeatureCollection<Geometry> { // Convert requests/offers/informations data to GeoJSON format for MapLibre
    return {
      type: 'FeatureCollection',
      features: data
        .filter(d => d.latitude && d.longitude)
        .map(d => {
          let longitude = Number(d.longitude);
          let latitude = Number(d.latitude);
          if (jitter) { // Bruit aléatoire : empêche l'identification d'une position exacte.
            longitude += (Math.random() - 0.5) * 0.01;
            latitude += (Math.random() - 0.5) * 0.01;
          }
          return {
            type: 'Feature' as const,
            geometry: {
              type: 'Point' as const,
              coordinates: [longitude, latitude]
            },
            properties: {
              ...d
            }
          };
        })
    };
  }

  loadHelpData() {
    this.subscription = forkJoin({
      requests: this.requestService.getAll(),
      // L'annuaire de bénévoles n'est pas affiché sur la carte de crise.
      proposals: this.offerService.getAll({ exclude_type: 'Bénévolat' }),
      informations: this.informationService.getAll()
    }).subscribe({
      next: ({ requests, proposals, informations }) => {
        this.requests = requests;
        this.offers = proposals;
        this.informations = informations;

        const jitter = !this.isInstitutional;
        this.requestGeoJSON = this.jsonToGeoJSON(requests, jitter);
        this.proposalGeoJSON = this.jsonToGeoJSON(proposals, jitter);
        this.informationsGeoJSON = this.jsonToGeoJSON(informations, jitter);

        this.runWhenMapReady(() => this.addSourceAndLayers());

        // Calque institutionnel : offres de secourisme/soins, filtrées dans les offres déjà chargées.
        if (this.isInstitutional) {
          const personnel = proposals.filter((o: any) =>
            o.diplome_secourisme === true || o.offer_type_nom === OFFER_TYPE_SOINS
          );
          this.personnelSecourismeGeoJSON = this.jsonToGeoJSON(personnel);
          this.runWhenMapReady(() => this.addOrUpdatePersonnelSecourismeLayer());
        }
      },
      error: (err) => console.error('Erreur API:', err)
    });
  }

  /** Annuaire de bénévoles scopé au secteur de l'institution (OfferService.vueSecteur), séparé
   * de loadHelpData. Masqué par défaut. */
  /** Erreur affichée en infobulle du calque (souvent : institution absente ou sans commune). */
  benevolesPompiersError: string | null = null;
  // Chargé une seule fois, à la première activation du calque.
  private benevolesPompiersCharges = false;

  loadBenevolesPompiers(): void {
    this.offerService.vueSecteur().subscribe({
      next: (benevoles) => {
        this.benevolesPompiersError = null;
        this.benevolesPompiersGeoJSON = this.jsonToGeoJSON(benevoles);
        this.runWhenMapReady(() => this.addOrUpdateBenevolesPompiersLayer());
      },
      error: (err) => {
        // 400 le plus courant : institution de l'utilisateur vide, ou sans commune renseignée.
        this.benevolesPompiersError = err?.error?.error || "Annuaire indisponible pour ce compte.";
        console.warn('Bénévoles pompiers indisponibles :', this.benevolesPompiersError);
      },
    });
  }

  loadTeamPositions(): void {
    this.positionEquipeService.getAll().subscribe({
      next: (positions) => {
        this.teamPositionsGeoJSON = {
          type: 'FeatureCollection',
          features: positions
            .filter(p => p.latitude != null && p.longitude != null)
            .map(p => ({
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [Number(p.longitude), Number(p.latitude)] },
              properties: {
                utilisateur_nom: p.utilisateur_nom,
                team_noms: (p.team_noms || []).join(', ') || 'Aucune équipe',
                horodatage: p.horodatage,
              }
            }))
        };
        this.runWhenMapReady(() => this.addOrUpdateTeamPositionsLayer());
      },
      error: (err) => console.error('Erreur chargement positions équipes:', err)
    });
  }

  private addOrUpdateTeamPositionsLayer(): void {
    if (!this.map || !this.teamPositionsGeoJSON) return;

    const existingSource = this.map.getSource('team-positions') as maplibregl.GeoJSONSource | undefined;
    if (existingSource) {
      existingSource.setData(this.teamPositionsGeoJSON);
      return;
    }

    this.map.addSource('team-positions', { type: 'geojson', data: this.teamPositionsGeoJSON });

    const visibility = this.layerVisibility.positions ? 'visible' : 'none';

    this.map.addLayer({
      id: 'team-positions-layer',
      type: 'circle',
      source: 'team-positions',
      layout: { visibility },
      paint: {
        'circle-color': '#9c27b0',
        'circle-radius': 7,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#fff'
      }
    });

    this.map.addLayer({
      id: 'team-positions-label',
      type: 'symbol',
      source: 'team-positions',
      layout: {
        visibility,
        'text-field': ['get', 'utilisateur_nom'],
        'text-size': 11,
        'text-offset': [0, 1.2],
        'text-anchor': 'top'
      },
      paint: {
        'text-color': '#4a148c',
        'text-halo-color': '#fff',
        'text-halo-width': 1
      }
    });

    this.map.on('click', 'team-positions-layer', (e) => { // Popup avec le nom, l'équipe et la fraîcheur de la position
      if (!e.features || e.features.length === 0) return;
      const geometry = e.features[0].geometry as GeoJSON.Point;
      const coordinates = geometry.coordinates.slice() as [number, number];
      const nom = e.features[0].properties?.['utilisateur_nom'] || 'Inconnu';
      const equipes = e.features[0].properties?.['team_noms'] || 'Aucune équipe';
      const horodatage = e.features[0].properties?.['horodatage'];
      const dateTxt = horodatage ? new Date(horodatage).toLocaleString('fr-FR') : 'inconnue';

      new maplibregl.Popup()
        .setLngLat(coordinates)
        .setHTML(`<strong>${nom}</strong><br>Équipe(s) : ${equipes}<br>Dernière position connue : ${dateTxt}`)
        .addTo(this.map!);
    });

    this.map.on('mouseenter', 'team-positions-layer', () => { this.map!.getCanvas().style.cursor = 'pointer'; });
    this.map.on('mouseleave', 'team-positions-layer', () => { this.map!.getCanvas().style.cursor = ''; });
  }

  /** Nœuds personnels MeshCore : seulement pendant une mission EN_COURS de l'équipe du porteur
   * (règle appliquée côté serveur, positions_en_mission). */
  loadNoeudsMeshCore(): void {
    this.noeudMeshUtilisateurService.positionsEnMission().subscribe({
      next: (positions) => {
        this.noeudsMeshCoreGeoJSON = {
          type: 'FeatureCollection',
          features: positions.map(p => ({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [Number(p.longitude), Number(p.latitude)] },
            properties: {
              nom: p.utilisateur_nom || p.nom_noeud,
              batterie: this.libelleBatterie(p.tension_batterie_v, p.niveau_batterie_pct),
            },
          })),
        };
        this.runWhenMapReady(() => this.addOrUpdateNoeudsMeshCoreLayer());
      },
      error: (err) => console.error('Erreur chargement nœuds MeshCore:', err),
    });
  }

  /** Télémétrie batterie pour la popup ; chaîne vide si inconnue. */
  private libelleBatterie(tensionV: number | null, niveauPct: number | null): string {
    const morceaux: string[] = [];
    if (niveauPct != null) morceaux.push(`${niveauPct}%`);
    if (tensionV != null) morceaux.push(`${tensionV.toFixed(2)} V`);
    return morceaux.join(' · ');
  }

  private addOrUpdateNoeudsMeshCoreLayer(): void {
    if (!this.map || !this.noeudsMeshCoreGeoJSON) return;

    const existingSource = this.map.getSource('noeuds-meshcore') as maplibregl.GeoJSONSource | undefined;
    if (existingSource) {
      existingSource.setData(this.noeudsMeshCoreGeoJSON);
      return;
    }

    this.map.addSource('noeuds-meshcore', { type: 'geojson', data: this.noeudsMeshCoreGeoJSON });

    const visibility = this.layerVisibility.noeudsMeshCore ? 'visible' : 'none';

    this.map.addLayer({
      id: 'noeuds-meshcore-layer',
      type: 'circle',
      source: 'noeuds-meshcore',
      layout: { visibility },
      paint: {
        'circle-color': '#16a34a',
        'circle-radius': 6,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#fff',
      },
    });

    this.map.addLayer({
      id: 'noeuds-meshcore-label',
      type: 'symbol',
      source: 'noeuds-meshcore',
      layout: {
        visibility,
        'text-field': ['get', 'nom'],
        'text-size': 11,
        'text-offset': [0, 1.2],
        'text-anchor': 'top',
      },
      paint: { 'text-color': '#15803d', 'text-halo-color': '#fff', 'text-halo-width': 1 },
    });

    this.map.on('click', 'noeuds-meshcore-layer', (e) => {
      if (!e.features || e.features.length === 0) return;
      const geometry = e.features[0].geometry as GeoJSON.Point;
      const coordinates = geometry.coordinates.slice() as [number, number];
      const nom = e.features[0].properties?.['nom'] || 'Nœud';
      const batterie = e.features[0].properties?.['batterie'];
      new maplibregl.Popup().setLngLat(coordinates).setHTML(
        `<strong>${nom}</strong><br>Nœud MeshCore personnel${batterie ? `<br>Batterie : ${batterie}` : ''}`
      ).addTo(this.map!);
    });
    this.map.on('mouseenter', 'noeuds-meshcore-layer', () => { this.map!.getCanvas().style.cursor = 'pointer'; });
    this.map.on('mouseleave', 'noeuds-meshcore-layer', () => { this.map!.getCanvas().style.cursor = ''; });
  }

  /** Nœuds personnels Meshtastic : même règle que loadNoeudsMeshCore, en bleu. */
  loadNoeudsMeshtastic(): void {
    this.noeudUtilisateurMeshtasticService.positionsEnMission().subscribe({
      next: (positions) => {
        this.noeudsMeshtasticGeoJSON = {
          type: 'FeatureCollection',
          features: positions.map(p => ({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [Number(p.longitude), Number(p.latitude)] },
            properties: { nom: p.utilisateur_nom || p.nom_noeud },
          })),
        };
        this.runWhenMapReady(() => this.addOrUpdateNoeudsMeshtasticLayer());
      },
      error: (err) => console.error('Erreur chargement nœuds Meshtastic:', err),
    });
  }

  private addOrUpdateNoeudsMeshtasticLayer(): void {
    if (!this.map || !this.noeudsMeshtasticGeoJSON) return;

    const existingSource = this.map.getSource('noeuds-meshtastic') as maplibregl.GeoJSONSource | undefined;
    if (existingSource) {
      existingSource.setData(this.noeudsMeshtasticGeoJSON);
      return;
    }

    this.map.addSource('noeuds-meshtastic', { type: 'geojson', data: this.noeudsMeshtasticGeoJSON });

    const visibility = this.layerVisibility.noeudsMeshtastic ? 'visible' : 'none';

    this.map.addLayer({
      id: 'noeuds-meshtastic-layer',
      type: 'circle',
      source: 'noeuds-meshtastic',
      layout: { visibility },
      paint: {
        'circle-color': '#2563eb',
        'circle-radius': 6,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#fff',
      },
    });

    this.map.addLayer({
      id: 'noeuds-meshtastic-label',
      type: 'symbol',
      source: 'noeuds-meshtastic',
      layout: {
        visibility,
        'text-field': ['get', 'nom'],
        'text-size': 11,
        'text-offset': [0, 1.2],
        'text-anchor': 'top',
      },
      paint: { 'text-color': '#1d4ed8', 'text-halo-color': '#fff', 'text-halo-width': 1 },
    });

    this.map.on('click', 'noeuds-meshtastic-layer', (e) => {
      if (!e.features || e.features.length === 0) return;
      const geometry = e.features[0].geometry as GeoJSON.Point;
      const coordinates = geometry.coordinates.slice() as [number, number];
      const nom = e.features[0].properties?.['nom'] || 'Nœud';
      new maplibregl.Popup().setLngLat(coordinates).setHTML(`<strong>${nom}</strong><br>Nœud Meshtastic personnel`).addTo(this.map!);
    });
    this.map.on('mouseenter', 'noeuds-meshtastic-layer', () => { this.map!.getCanvas().style.cursor = 'pointer'; });
    this.map.on('mouseleave', 'noeuds-meshtastic-layer', () => { this.map!.getCanvas().style.cursor = ''; });
  }

  private addOrUpdatePersonnelSecourismeLayer(): void {
    if (!this.map || !this.personnelSecourismeGeoJSON) return;

    const existingSource = this.map.getSource('personnel-secourisme') as maplibregl.GeoJSONSource | undefined;
    if (existingSource) {
      existingSource.setData(this.personnelSecourismeGeoJSON);
      return;
    }

    this.map.addSource('personnel-secourisme', { type: 'geojson', data: this.personnelSecourismeGeoJSON });

    this.map.addLayer({
      id: 'personnel-secourisme-layer',
      type: 'circle',
      source: 'personnel-secourisme',
      layout: { visibility: this.layerVisibility.personnelSecourisme ? 'visible' : 'none' },
      paint: {
        'circle-color': '#f59e0b',
        'circle-radius': 6,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#fff'
      }
    });

    this.map.on('click', 'personnel-secourisme-layer', (e) => {
      if (!e.features || e.features.length === 0) return;
      const geometry = e.features[0].geometry as GeoJSON.Point;
      const coordinates = geometry.coordinates.slice() as [number, number];
      const props = e.features[0].properties || {};
      const nom = `${props['first_name_offer'] || ''} ${props['last_name_offer'] || ''}`.trim() || 'Inconnu';
      const type = props['offer_type_nom'] || (props['diplome_secourisme'] ? 'Diplôme de secourisme' : '');

      new maplibregl.Popup()
        .setLngLat(coordinates)
        .setHTML(`<strong>${nom}</strong><br>${type}`)
        .addTo(this.map!);
    });

    this.map.on('mouseenter', 'personnel-secourisme-layer', () => { this.map!.getCanvas().style.cursor = 'pointer'; });
    this.map.on('mouseleave', 'personnel-secourisme-layer', () => { this.map!.getCanvas().style.cursor = ''; });
  }

  private addOrUpdateBenevolesPompiersLayer(): void {
    if (!this.map || !this.benevolesPompiersGeoJSON) return;

    const existingSource = this.map.getSource('benevoles-pompiers') as maplibregl.GeoJSONSource | undefined;
    if (existingSource) {
      existingSource.setData(this.benevolesPompiersGeoJSON);
      return;
    }

    this.map.addSource('benevoles-pompiers', { type: 'geojson', data: this.benevolesPompiersGeoJSON });

    this.map.addLayer({
      id: 'benevoles-pompiers-layer',
      type: 'circle',
      source: 'benevoles-pompiers',
      layout: { visibility: this.layerVisibility.benevolesPompiers ? 'visible' : 'none' },
      paint: {
        'circle-color': '#7c3aed',
        'circle-radius': 5,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#fff'
      }
    });

    this.map.on('click', 'benevoles-pompiers-layer', (e) => {
      if (!e.features || e.features.length === 0) return;
      const geometry = e.features[0].geometry as GeoJSON.Point;
      const coordinates = geometry.coordinates.slice() as [number, number];
      const props = e.features[0].properties || {};
      const nom = `${props['first_name_offer'] || ''} ${props['last_name_offer'] || ''}`.trim() || 'Inconnu';
      // MapLibre sérialise les propriétés tableau/objet en JSON string dans une source GeoJSON.
      const raw = props['competences_libelles'];
      let competences = '';
      if (Array.isArray(raw)) {
        competences = raw.join(', ');
      } else if (typeof raw === 'string') {
        try { competences = JSON.parse(raw).join(', '); } catch { competences = raw; }
      }

      new maplibregl.Popup()
        .setLngLat(coordinates)
        .setHTML(`<strong>${nom}</strong><br>Ancien sapeur-pompier bénévole${competences ? '<br>' + competences : ''}`)
        .addTo(this.map!);
    });

    this.map.on('mouseenter', 'benevoles-pompiers-layer', () => { this.map!.getCanvas().style.cursor = 'pointer'; });
    this.map.on('mouseleave', 'benevoles-pompiers-layer', () => { this.map!.getCanvas().style.cursor = ''; });
  }

  /** Tous les points opérationnels : institutionnels seulement. */
  loadCentres(): void {
    this.pointOperationnelService.getAll().subscribe({
      next: (points) => {
        const withLocation = points.filter(p => p.latitude != null && p.longitude != null);
        this.centresTousGeoJSON = this.jsonToGeoJSON(withLocation);
        this.runWhenMapReady(() => this.addOrUpdateSimpleCircleLayer(
          'centres-tous', 'centres-tous-layer', this.centresTousGeoJSON, '#6366f1', this.layerVisibility.centresTous,
        ));
      },
      error: (err) => console.error('Erreur chargement centres:', err)
    });
  }

  /** Centres d'accueil et postes de secours : publics (carte_publique). */
  loadCentresPublics(): void {
    this.pointOperationnelService.getCartePublique().subscribe({
      next: (points: CentreAccueilPublic[]) => {
        const withLocation = points.filter(p => p.latitude != null && p.longitude != null);
        this.centresHebergementGeoJSON = this.jsonToGeoJSON(
          withLocation.filter(p => p.type_code === POINT_TYPE_HEBERGEMENT)
        );
        this.postesSecoursGeoJSON = this.jsonToGeoJSON(
          withLocation.filter(p => p.type_code === POINT_TYPE_SECOURS)
        );
        this.runWhenMapReady(() => {
          this.addOrUpdateSimpleCircleLayer(
            'centres-hebergement', 'centres-hebergement-layer', this.centresHebergementGeoJSON,
            '#059669', this.layerVisibility.centresHebergement,
          );
          this.addOrUpdatePostesSecoursLayer();
        });
      },
      error: (err) => console.error('Erreur chargement centres publics:', err)
    });
  }

  private addOrUpdateSimpleCircleLayer(
    sourceId: string, layerId: string, data: FeatureCollection<Geometry> | null,
    color: string, visible: boolean,
  ): void {
    if (!this.map || !data) return;
    const existing = this.map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined;
    if (existing) {
      existing.setData(data);
      return;
    }
    this.map.addSource(sourceId, { type: 'geojson', data });
    this.map.addLayer({
      id: layerId,
      type: 'circle',
      source: sourceId,
      layout: { visibility: visible ? 'visible' : 'none' },
      paint: {
        'circle-color': color,
        'circle-radius': 7,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#fff',
      },
    });
    this.map.on('click', layerId, (e) => {
      if (!e.features || e.features.length === 0) return;
      const geometry = e.features[0].geometry as GeoJSON.Point;
      const coordinates = geometry.coordinates.slice() as [number, number];
      const props = e.features[0].properties || {};
      new maplibregl.Popup()
        .setLngLat(coordinates)
        .setHTML(`<strong>${props['nom'] || 'Centre'}</strong><br>${props['type_libelle'] || ''}${props['accepte_animaux'] ? '<br>🐾 Animaux acceptés' : ''}`)
        .addTo(this.map!);
    });
    this.map.on('mouseenter', layerId, () => { this.map!.getCanvas().style.cursor = 'pointer'; });
    this.map.on('mouseleave', layerId, () => { this.map!.getCanvas().style.cursor = ''; });
  }

  /** Icône dédiée (croix rouge), reconnaissable sans légende. */
  private ensurePosteSecoursIcon(): Promise<void> {
    if (!this.map) return Promise.reject('map non initialisée');
    if (this.map.hasImage(POSTE_SECOURS_ICON_ID)) return Promise.resolve();

    const svg = `
      <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">
        <rect x="2" y="2" width="28" height="28" rx="5" fill="#ffffff" stroke="#dc2626" stroke-width="2"/>
        <rect x="13.5" y="7" width="5" height="18" fill="#dc2626"/>
        <rect x="7" y="13.5" width="18" height="5" fill="#dc2626"/>
      </svg>`;
    const url = `data:image/svg+xml;base64,${btoa(svg)}`;

    // Par une balise <img>, et non par `map.loadImage` : celle-ci passe par createImageBitmap,
    // qui ne sait pas décoder un SVG sous Chrome (« The source image could not be decoded »).
    // Le calque des postes de secours ne s'affichait donc jamais — vu le 18/11/2026 en
    // parcourant toutes les pages pour le manuel.
    return new Promise((resolve, reject) => {
      const image = new Image(32, 32);
      image.onload = () => {
        if (this.map && !this.map.hasImage(POSTE_SECOURS_ICON_ID)) this.map.addImage(POSTE_SECOURS_ICON_ID, image);
        resolve();
      };
      image.onerror = () => reject(new Error("icône illisible"));
      image.src = url;
    });
  }

  private addOrUpdatePostesSecoursLayer(): void {
    if (!this.map || !this.postesSecoursGeoJSON) return;

    const existing = this.map.getSource('postes-secours') as maplibregl.GeoJSONSource | undefined;
    if (existing) {
      existing.setData(this.postesSecoursGeoJSON);
      return;
    }

    this.ensurePosteSecoursIcon().then(() => {
      if (!this.map || !this.postesSecoursGeoJSON) return;
      this.map.addSource('postes-secours', { type: 'geojson', data: this.postesSecoursGeoJSON });
      this.map.addLayer({
        id: 'postes-secours-layer',
        type: 'symbol',
        source: 'postes-secours',
        layout: {
          visibility: this.layerVisibility.postesSecours ? 'visible' : 'none',
          'icon-image': POSTE_SECOURS_ICON_ID,
          'icon-size': 0.7,
          'icon-allow-overlap': true,
        },
      });
      this.map.on('click', 'postes-secours-layer', (e) => {
        if (!e.features || e.features.length === 0) return;
        const geometry = e.features[0].geometry as GeoJSON.Point;
        const coordinates = geometry.coordinates.slice() as [number, number];
        const props = e.features[0].properties || {};
        new maplibregl.Popup()
          .setLngLat(coordinates)
          .setHTML(`<strong>${props['nom'] || 'Poste de secours'}</strong>`)
          .addTo(this.map!);
      });
      this.map.on('mouseenter', 'postes-secours-layer', () => { this.map!.getCanvas().style.cursor = 'pointer'; });
      this.map.on('mouseleave', 'postes-secours-layer', () => { this.map!.getCanvas().style.cursor = ''; });
    }).catch((err) => console.error('Erreur chargement icône poste de secours:', err));
  }

  private addSourceAndLayers(): void {
    if (!this.map) return;
    const isAdmin = this.authService.isAdmin();

    if (this.map.getSource('clusters')) { // Déjà ajoutée (ex: second appel après un rechargement des données) : juste rafraîchir
      this.applyClusterVisibility();
      return;
    }

    this.map.addSource('clusters', { // Add cluster source for requests, offers and informations
      type: 'geojson',
      data: this.buildVisibleClusterData(),
      cluster: true,
      clusterMaxZoom: 8,
      clusterRadius: 50
    });
    this.map!.addLayer({ // Cluster layer to combine both requests and offers into clusters
      id: 'clusters-layer',
      type: 'circle',
      source: 'clusters',
      filter: ['has', 'point_count'],
      paint: {
              'circle-color': [ // Different colors based on the number of points in the cluster
                  'step',
                  ['get', 'point_count'],
                  '#4CAF50',
                  2,
                  '#FF9800',
                  7,
                  '#F44336',
                  15,
                  '#B71C1C'
              ],
              'circle-radius': [ // Different radius based on the number of points in the cluster
                  'step',
                  ['get', 'point_count'],
                  20,
                  100,
                  30,
                  750,
                  40
              ]
          }
      });

      this.map!.addLayer({ // Cluster count layer to show the number of points in each cluster
          id: 'cluster-count',
          type: 'symbol',
          source: 'clusters',
          filter: ['has', 'point_count'],
          layout: {
              'text-field': '{point_count_abbreviated}',
              'text-font': ['Noto Sans Regular'],
              'text-size': 12
          }
      });

      this.map!.on('click', 'unclustered-point', (e) => { // Shows popup with details when clicking on an individual point (request or offer)
          if (!e.features || e.features.length === 0) return;
          const geometry = e.features[0].geometry as GeoJSON.Point;
          let offerRequest: string;
          const coordinates = geometry.coordinates.slice() as [number, number];
          const statut = e.features[0].properties['status'] || 'N/A';
          const title = e.features[0].properties['title'] || 'N/A';
          const description = e.features[0].properties['description'] || 'Pas de description';
          let name: string = '';
          let first_name: string = '';
          if ('last_name_request' in e.features[0].properties) {
            offerRequest = 'la demande';
            if (isAdmin){ // Only show requester/offerer/informater names to admins
                  name = e.features[0].properties['last_name_request'] || 'N/A';
                  name = `<br>Nom demandeur: ${name}`
                  first_name = e.features[0].properties['first_name_request'] || 'N/A';
                  first_name = `<br>Prénom demandeur: ${first_name}`
            }
          }
          else if ('last_name_offer' in e.features[0].properties) {
            offerRequest = 'l\'offre';
            if (isAdmin){
                  name = e.features[0].properties['last_name_offer'] || 'N/A';
                  name = `<br>Nom offreur: ${name}`
                  first_name = e.features[0].properties['first_name_offer'] || 'N/A';
                  first_name = `<br>Prénom offreur: ${first_name}`
                  }
          }
          else {
            offerRequest = 'l\'information';
            if (isAdmin){
                  name = e.features[0].properties['last_name_information'] || 'N/A';
                  name = `<br>Nom informateur: ${name}`
                  first_name = e.features[0].properties['first_name_information'] || 'N/A';
                  first_name = `<br>Prénom informateur: ${first_name}`
            }
          }
          while (Math.abs(e.lngLat.lng - coordinates[0]) > 180) {
              coordinates[0] += e.lngLat.lng > coordinates[0] ? 360 : -360;
          }

          new maplibregl.Popup() // Create a popup with details about the request/offer/information
              .setLngLat(coordinates)
              .setHTML(
                  `Nom de ${offerRequest}: ${title}<br>Statut de ${offerRequest}: ${statut}<br>Description: ${description}${name}${first_name}`
              )
              .addTo(this.map!);
      });

        this.map!.addLayer({ // Layer for individual points (requests, offers and informations) that are not clustered
          id: 'unclustered-point',
          type: 'circle',
          source: 'clusters',
          filter: ['!', ['has', 'point_count']],
          paint: {
              'circle-color': [
              'case',
              ['has', 'last_name_request'],
              '#ff0000', // If it's a request
              ['has', 'last_name_offer'],
              '#11b4da', // If it's an offer
              ['has', 'last_name_information'],
              '#00ff00', // If it's an information
              '#cccccc' // Default color (should not happen)
              ],
              'circle-radius': 5,
              'circle-stroke-width': 1,
              'circle-stroke-color': '#fff'
          }
      });

      this.map!.on('click', 'clusters-layer', async (e) => { // Zoom into cluster on click
          const features = this.map!.queryRenderedFeatures(e.point, {
              layers: ['clusters-layer']
          });
          const clusterId = features[0].properties['cluster_id'];
          const source = this.map!.getSource('clusters') as maplibregl.GeoJSONSource;
          const zoom = await source.getClusterExpansionZoom(clusterId);
          const geometry = features[0].geometry as GeoJSON.Point;
          this.map!.easeTo({
              center: geometry.coordinates as [number, number],
              zoom
          });
      });

      this.addHullLayer();
      this.addHoverEffect();
      this.addDirectionArrowLayer();
  }

  /** Flèche orientée selon l'azimut de la photo (signalements) ; icon-rotate suit déjà la
   * convention azimut (0 = Nord). */
  private addDirectionArrowLayer(): void {
    if (!this.map) return;

    const arrowSvg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">' +
      '<path d="M12 2 L18 20 L12 16 L6 20 Z" fill="#1b5e20" stroke="white" stroke-width="1"/>' +
      '</svg>';

    const img = new Image(24, 24);
    img.onload = () => {
      if (!this.map) return;
      if (!this.map.hasImage('direction-arrow')) {
        this.map.addImage('direction-arrow', img);
      }
      this.map.addLayer({
        id: 'information-direction-arrow',
        type: 'symbol',
        source: 'clusters',
        filter: [
          'all',
          ['!', ['has', 'point_count']],
          ['has', 'last_name_information'],
          ['!=', ['get', 'azimuth'], null]
        ],
        layout: {
          'icon-image': 'direction-arrow',
          'icon-size': 1,
          'icon-rotate': ['get', 'azimuth'],
          'icon-rotation-alignment': 'map',
          'icon-allow-overlap': true,
          'icon-offset': [0, -12]
        }
      });
    };
    img.src = 'data:image/svg+xml;base64,' + btoa(arrowSvg);
  }

  private addHullLayer() { // Layer to show convex hull around clusters on hover

    this.map!.addSource('cluster-hull', {
      type: 'geojson',
      data: {
        type: 'FeatureCollection',
        features: []
      }
    });

    this.map!.addLayer({ // Fill layer for the convex hull
      id: 'cluster-hull-fill',
      type: 'fill',
      source: 'cluster-hull',
      paint: {
        'fill-color': '#0099ff',
        'fill-opacity': 0.25
      }
    });

    this.map!.addLayer({ // Outer line layer for the convex hull border
      id: 'cluster-hull-line',
      type: 'line',
      source: 'cluster-hull',
      paint: {
        'line-color': '#0066cc',
        'line-width': 2
      }
    });
  }

private addHoverEffect() { // Show convex hull around clusters on hover

    const source = this.map!.getSource('clusters') as maplibregl.GeoJSONSource;

    this.map!.on('mouseenter', 'clusters-layer', async (e) => { // Change cursor to pointer when hovering over clusters

      this.map!.getCanvas().style.cursor = 'pointer';

      const feature = e.features?.[0];
      if (!feature) return;

      const clusterId = feature.properties!['cluster_id'];

      try {
        const points = await source.getClusterLeaves(clusterId, 1000, 0);

        if (!points || !points.length) return;

        const fc = turf.featureCollection(points as any[]);

        const hull = turf.convex(fc);

        if (!hull) return;

        const hullSource = this.map!.getSource('cluster-hull') as maplibregl.GeoJSONSource;
        hullSource.setData(hull);
      } catch (err) {
        console.error('Error getting cluster leaves:', err);
      }
    });

    this.map!.on('mouseleave', 'clusters-layer', () => { // Reset cursor and clear hull when no longer hovering over clusters

      this.map!.getCanvas().style.cursor = '';

      const hullSource = this.map!.getSource('cluster-hull') as maplibregl.GeoJSONSource;
      hullSource?.setData({
        type: 'FeatureCollection',
        features: []
      });
    });
  }

  /** Vrai quand le navigateur n'a pas pu fournir de contexte WebGL : le gabarit affiche alors
   * un message au lieu d'un cadre vide. */
  carteIndisponible = false;

  private initializeMap(): void { // Initialize MapLibre map and add controls
    // MapLibre exige WebGL, et son absence n'est pas un cas théorique : accélération
    // matérielle désactivée, poste ancien, pilote graphique en panne, politique d'entreprise.
    // Sans ce garde, le constructeur lève et l'exception traverse ngAfterViewInit : la PAGE
    // ENTIÈRE ne s'affiche pas, pas seulement la carte — sur une plateforme de crise consultée
    // depuis le premier ordinateur disponible, c'est une page blanche au mauvais moment.
    //
    // Révélé par le harnais de test (28/10/2026) : quatre composants embarquant une carte
    // échouaient tous sur « Failed to initialize WebGL », ce qui était la bonne nouvelle —
    // le test disait vrai, c'est le composant qui était fragile.
    try {
      this.map = new maplibregl.Map({
        container: this.mapContainer.nativeElement,
        style: styleCarte(),
        center: this.center,
        zoom: this.zoom
      });
    } catch (erreur) {
      console.warn('Carte indisponible : contexte WebGL impossible à créer.', erreur);
      // Posé au tour suivant, et non tout de suite : on est dans ngAfterViewInit, donc la
      // détection de changement de ce cycle est déjà passée. L'écrire directement déclenche
      // NG0100 (« expression a changé après vérification »), qui est une vraie erreur en mode
      // développement — et un bandeau qui n'apparaît qu'au prochain cycle en production.
      Promise.resolve().then(() => this.carteIndisponible = true);
      return;
    }

    this.map.addControl(new maplibregl.NavigationControl(), 'top-right'); // Add zoom and rotation controls to the map

    // Bouton « ma position » (07/11/2026). Il remplace le recentrage automatique au chargement,
    // retiré parce qu'il déclenchait l'invite de permission sans que l'utilisateur l'ait
    // demandée — et qu'un refus est DÉFINITIF sur iOS (voir
    // GeolocationService.positionSansInvite). Ici l'invite part d'un clic : c'est le contexte
    // qu'exige Safari, et l'utilisateur sait pourquoi on la lui demande.
    //
    // `trackUserLocation: false` : un point à la demande, jamais un suivi continu — le suivi
    // de position a son propre dispositif explicite (SuiviPositionPermanentService), activé
    // par l'utilisateur et visible dans l'en-tête.
    this.map.addControl(new maplibregl.GeolocateControl({
      positionOptions: { enableHighAccuracy: true, timeout: 20000, maximumAge: 60000 },
      trackUserLocation: false,
      showAccuracyCircle: true,
    }), 'top-right');

    this.map.on('load', () => {
      // If crises, requests, or offers were already loaded before the map was ready, add them to the map now
      if (this.crises.length > 0) {
        this.addCrisisMarkers();
        // Sort crisis circles by radius in descending order to ensure larger circles are drawn first and smaller ones on top for better visibility
        this.crisisCircle.sort(
          (b, a) => a.properties.radius - b.properties.radius
        );
        const circleGeojson: FeatureCollection<Polygon> = {
        type: 'FeatureCollection',
        features: this.crisisCircle
        };
        this.map!.addSource('location-radius', { // Add source for crisis circles
          type: 'geojson',
          data: circleGeojson
        });
        this.map!.addLayer({ // Add fill layer for crisis circles
          id: 'location-radius',
          type: 'fill',
          source: 'location-radius',
          paint: {
            'fill-color': '#8CCFFF',
            'fill-opacity': 0.5
          }
        });

        this.map!.on('click', 'location-radius', (e) => { // Show popup with crisis details when clicking on a crisis circle
        const properties = e.features?.[0]?.properties || {};
        new maplibregl.Popup()
        .setHTML(`
          <div style="color: black; font-family: sans-serif;">
            <h3 style="margin: 0 0 5px 0;">${properties?.['name'] || 'Nom inconnu'}</h3>
            <p style="margin: 0;">${properties?.['description'] || 'Pas de description'}</p>
            <p style="margin: 0;"><strong>Type:</strong> ${properties?.['type'] || 'Type inconnu'}</p>
            <br>
            <small>Créé le : ${new Date(properties?.['start_date'] || Date.now()).toLocaleDateString()}</small>
          </div>
        `)
        .setLngLat(e.lngLat)
        .addTo(this.map!);
        });
      }
      if (this.requests.length > 0) {
        this.requestGeoJSON = this.jsonToGeoJSON(this.requests);
      }
      if (this.offers.length > 0) {
        this.proposalGeoJSON = this.jsonToGeoJSON(this.offers);
      }
    });
  } 

  private addCrisisMarkers(): void {
    if (!this.map) return;

    // Clear existing crisis circles
    this.crisisCircle = [];

    this.crises.forEach(crisis => {
      // Zone précise dessinée (polygone) : utilisée telle quelle, sans fusion ni calcul de cercle
      if (crisis.zone_geojson) {
        this.crisisCircle.push({
          type: 'Feature',
          geometry: crisis.zone_geojson,
          properties: {
            center: [crisis.longitude, crisis.latitude],
            radius: crisis.radius,
            name: crisis.name,
            description: crisis.description,
            start_date: crisis.start_date,
            type: crisis.type
          }
        });
        return;
      }

      // Zone composée de communes/départements (union calculée dans crisis-zone-secteurs.util.ts).
      if (crisis.zone_secteurs_geojson) {
        this.crisisCircle.push({
          type: 'Feature',
          geometry: crisis.zone_secteurs_geojson,
          properties: {
            center: [crisis.longitude, crisis.latitude],
            radius: crisis.radius,
            name: crisis.name,
            description: crisis.description,
            start_date: crisis.start_date,
            type: crisis.type
          }
        });
        return;
      }

      // Create a circle for each crisis
      if (crisis.latitude && crisis.longitude) {
        let radiusCenter = [crisis.longitude, crisis.latitude] as [number, number];
        let radius = crisis.radius || 10; // Radius in kilometers, default to 10km if not specified
        let circle = turf.circle(radiusCenter, radius, {steps: 64, units: 'kilometers'})
        circle.properties = {center: radiusCenter, radius: radius, name: crisis.name, description: crisis.description, start_date: crisis.start_date, type: crisis.type};
        
        // Merge circles if they intersect and are of the same type
        for (const crisisCircles of this.crisisCircle) {
          if(turf.booleanIntersects(crisisCircles, circle) && crisisCircles.properties.type == crisis.type) {
            this.crisisCircle = this.crisisCircle.filter(c => c !== crisisCircles);
            radiusCenter = [(radiusCenter[0] + crisisCircles.properties.center[0])/2, (radiusCenter[1] + crisisCircles.properties.center[1])/2];
            radius = Math.max(turf.distance(crisisCircles.properties.center, radiusCenter, {units: 'kilometers'}) + crisisCircles.properties.radius, turf.distance(circle.properties['center'], radiusCenter, {units: 'kilometers'}) + circle.properties['radius']);
            circle = turf.circle(radiusCenter, radius, {steps: 64, units: 'kilometers'});
            circle.properties = {center: radiusCenter, radius: radius, name: crisis.name + ' || ' + crisisCircles.properties.name, description: crisis.description, start_date: crisis.start_date, type: crisis.type};
          }
        }
        this.crisisCircle.push(circle);
      }
    });
  }
}