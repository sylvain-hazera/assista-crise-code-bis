import { Component, OnInit, OnDestroy, AfterViewInit, Input, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
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
import { PointOperationnelService } from '../../../../services/point-operationnel.service';
import type { FeatureCollection, Geometry, Polygon } from 'geojson';
import { AuthService } from '../../../../auth/services/auth.service';
import { InformationService } from '../../../../services/information.service';
import { PointOperationnel, CentreAccueilPublic } from '../../../models/point-operationnel.model';

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
}

// Codes/libellés déjà utilisés côté offre/point pour repérer secourisme/soins — voir
// OfferSerializer.offer_type_nom / PointOperationnelSerializer.type_code.
const OFFER_TYPE_SOINS = 'Soins médicaux et paramédicaux';
const POINT_TYPE_SECOURS = 'SECOURS';
const POINT_TYPE_HEBERGEMENT = 'HEBERGEMENT';
const POSTE_SECOURS_ICON_ID = 'poste-secours-icon';

@Component({
  selector: 'app-map',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './map.component.html',
  styleUrl: './map.component.scss'
})
export class MapComponent implements OnInit, AfterViewInit, OnDestroy {
  // Reference to the map container element in the template to initialize MapLibre on it
  @ViewChild('mapContainer') mapContainer!: ElementRef;

  @Input() crises: Crisis[] = [];
  @Input() requests: Request[] = [];
  @Input() offers: Offer[] = [];
  @Input() informations: any[] = [];
  // Center of France by default, will be updated to user location if available
  @Input() center: [number, number] = [2.2137, 46.2276];
  @Input() zoom: number = 5;

  // Positions d'équipe réservées aux acteurs institutionnels : la checkbox correspondante
  // n'est même pas rendue pour un visiteur non institutionnel (voir map.component.html).
  isInstitutional = false;

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
  };

  private map: maplibregl.Map | null = null;
  private crisisCircle: any[] = [];
  private requestGeoJSON: FeatureCollection<Geometry> | null = null;
  private proposalGeoJSON: FeatureCollection<Geometry> | null = null;
  private informationsGeoJSON: FeatureCollection<Geometry> | null = null;
  private teamPositionsGeoJSON: FeatureCollection<Geometry> | null = null;
  private personnelSecourismeGeoJSON: FeatureCollection<Geometry> | null = null;
  private centresTousGeoJSON: FeatureCollection<Geometry> | null = null;
  private centresHebergementGeoJSON: FeatureCollection<Geometry> | null = null;
  private postesSecoursGeoJSON: FeatureCollection<Geometry> | null = null;
  private subscription: Subscription | null = null;

  constructor(private crisisService: CrisisService,
              private requestService: RequestService,
              private offerService: OfferService,
              private informationService: InformationService,
              private geolocationService: GeolocationService,
              private positionEquipeService: PositionEquipeService,
              private pointOperationnelService: PointOperationnelService,
              private authService: AuthService) {}
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
    }
    // Centres d'accueil et postes de secours : visibles sans authentification (contrairement
    // aux deux calques ci-dessus), voir PointOperationnelViewSet.carte_publique.
    this.loadCentresPublics();
  }

  /** Appelé par les checkbox du panneau de calques (voir template) : ré-applique la
   * visibilité sur les couches déjà ajoutées à la carte, sans jamais recharger les données. */
  onLayerToggle(): void {
    this.applyClusterVisibility();
    this.applyLayerVisibility('team-positions-layer', this.layerVisibility.positions);
    this.applyLayerVisibility('team-positions-label', this.layerVisibility.positions);
    this.applyLayerVisibility('location-radius', this.layerVisibility.crises);
    this.applyLayerVisibility('personnel-secourisme-layer', this.layerVisibility.personnelSecourisme);
    this.applyLayerVisibility('centres-tous-layer', this.layerVisibility.centresTous);
    this.applyLayerVisibility('centres-hebergement-layer', this.layerVisibility.centresHebergement);
    this.applyLayerVisibility('postes-secours-layer', this.layerVisibility.postesSecours);
  }

  private applyLayerVisibility(layerId: string, visible: boolean): void {
    if (!this.map || !this.map.getLayer(layerId)) return;
    this.map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none');
  }

  /** Les demandes/offres/signalements partagent une seule source clusterisée : les cacher
   * doit donc retirer leurs features de la source elle-même (pas juste la visibilité de
   * calque), sinon un cluster masqué continuerait à compter les points cachés. */
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

  /** MapLibre ne rejoue jamais l'événement 'load' pour un listener attaché après coup : sur ce
   * composant, les données arrivent par API après l'initialisation de la carte, donc un simple
   * `map.on('load', cb)` tardif ne se déclenchait jamais — c'est ce qui empêchait demandes/
   * offres/signalements de s'afficher (seules les zones de crise, ajoutées de façon
   * synchrone dans initializeMap(), apparaissaient). */
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

    // If no stored location, request geolocation permission and get current position
    if (!this.geolocationService.hasPermission()) {
      this.geolocationService.requestLocation()
        .then((coords: any) => {
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
          // GPS refusé/indisponible : se rabat sur le code postal du profil (adresse connue
          // de l'utilisateur), moins précis mais toujours plus pertinent que le centre par
          // défaut de la France — jamais bloquant si l'utilisateur n'est pas connecté ou n'a
          // pas renseigné de code postal.
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

        this.center = [coordinates[0], coordinates[1]];
        this.zoom = 10;
        if (this.map) {
          this.map.flyTo({ center: this.center, zoom: this.zoom, duration: 2000 });
        }
      },
      error: () => {},
    });
  }

  ngAfterViewInit(): void { // Initialize the map after the view is initialized to ensure the container is available
    this.initializeMap();
  }

  ngOnDestroy(): void { // Clean up subscriptions and map instance to prevent memory leaks
    if (this.subscription) this.subscription.unsubscribe();
    if (this.map) this.map.remove();
  }

  loadCrises() { // Load crises from the API and add them to the map
    this.subscription = this.crisisService.getAll().subscribe({
      next: (crises) => {
        console.log('Données de crises reçues:', crises);
        this.crises = crises;
        if (this.map) {
          this.addCrisisMarkers();
        }
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
          if (jitter) { // Add random noise to coordinates to prevent exact location identification
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

  loadHelpData() { // Load requests, offers and informations in parallel and process them together to add to the map
    this.subscription = forkJoin({
      requests: this.requestService.getAll(),
      proposals: this.offerService.getAll(),
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

        // Calque dédié, institutionnel uniquement : offres de secourisme/soins isolées parmi
        // toutes les offres déjà chargées ci-dessus — pas d'appel réseau supplémentaire.
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

  /** Tous les points opérationnels (centres d'accueil, de regroupement des moyens...) —
   * institutionnel uniquement, comme les positions équipes : un point logistique interne n'a
   * pas vocation à être exposé au grand public comme le sont les deux calques publics dédiés
   * (centres d'accueil, postes de secours — voir loadCentresPublics). */
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

  /** Centres d'accueil et postes de secours : visibles sans authentification (voir
   * PointOperationnelViewSet.carte_publique) — contrairement à "Tous les centres" ci-dessus,
   * réservé aux institutionnels. */
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
        .setHTML(`<strong>${props['nom'] || 'Centre'}</strong><br>${props['type_libelle'] || ''}`)
        .addTo(this.map!);
    });
    this.map.on('mouseenter', layerId, () => { this.map!.getCanvas().style.cursor = 'pointer'; });
    this.map.on('mouseleave', layerId, () => { this.map!.getCanvas().style.cursor = ''; });
  }

  /** Icône dédiée (croix rouge sur fond blanc) plutôt qu'un simple point coloré, pour rester
   * immédiatement identifiable — y compris par un visiteur anonyme qui ne connaît pas la
   * légende des calques. */
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

    return new Promise((resolve, reject) => {
      this.map!.loadImage(url).then(({ data: image }) => {
        if (!this.map!.hasImage(POSTE_SECOURS_ICON_ID)) this.map!.addImage(POSTE_SECOURS_ICON_ID, image);
        resolve();
      }).catch(reject);
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

  /** Petite flèche orientée selon l'azimut capturé au moment de la photo (boussole du
   * téléphone) — uniquement sur les signalements (Information) qui en ont une, superposée
   * au marqueur point. `icon-rotate` en degrés horaires depuis le haut correspond
   * exactement à la convention azimut (0 = Nord), pas de conversion nécessaire. */
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

  private initializeMap(): void { // Initialize MapLibre map and add controls
    this.map = new maplibregl.Map({
      container: this.mapContainer.nativeElement,
      style: 'https://raw.githubusercontent.com/go2garret/maps/main/src/assets/json/openStreetMap.json', 
      center: this.center,
      zoom: this.zoom
    });

    this.map.addControl(new maplibregl.NavigationControl(), 'top-right'); // Add zoom and rotation controls to the map

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

      // Zone composée à partir de communes/départements ajoutés (union bufferisée,
      // calculée côté frontend au moment de l'ajout — cf. crisis-zone-secteurs.util.ts)
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