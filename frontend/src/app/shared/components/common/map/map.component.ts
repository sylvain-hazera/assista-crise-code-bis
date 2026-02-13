import { Component, OnInit, OnDestroy, AfterViewInit, Input, ViewChild, ElementRef } from '@angular/core';
import maplibregl from 'maplibre-gl';
import * as turf from '@turf/turf';
import { CrisisService } from '../../../../services/crisis.service';
import { Crisis } from '../../../models/crisis.model';
import { RequestService } from '../../../../services/request.service';
import { Request } from '../../../models/request.model';
import { OfferService } from '../../../../services/offer.service';
import { Offer } from '../../../models/offer.model';
import { GeolocationService } from '../../../../services/geolocation.service';
import { forkJoin, Subscription } from 'rxjs';
import { FeatureCollection, Geometry, Polygon } from 'geojson';

@Component({
  selector: 'app-map',
  standalone: true,
  imports: [],
  templateUrl: './map.component.html',
  styleUrl: './map.component.scss'
})
export class MapComponent implements OnInit, AfterViewInit, OnDestroy {
  // Référence directe à la div HTML
  @ViewChild('mapContainer') mapContainer!: ElementRef;

  @Input() crises: Crisis[] = [];
  @Input() requests: Request[] = [];
  @Input() offers: Offer[] = [];
  // Centre de la France par défaut
  @Input() center: [number, number] = [2.2137, 46.2276]; 
  @Input() zoom: number = 5;
  
  private map: maplibregl.Map | null = null;
  private CrisisMarkers: maplibregl.Marker[] = [];
  private crisisCircle: any[] = [];
  private requestGeoJSON: any = null;
  private proposalGeoJSON: any = null;
  private subscription: Subscription | null = null;

  constructor(private crisisService: CrisisService,
              private requestService: RequestService,
              private offerService: OfferService,
              private geolocationService: GeolocationService) {}
  ngOnInit(): void {
    // Charger la géolocalisation si disponible
    this.loadUserLocation();
    
    // Si pas de données en entrée, on charge depuis le service
    if (this.crises.length === 0) {
      this.loadCrises();
    }
    if (this.requests.length === 0 || this.offers.length === 0) {
      this.loadHelpData();
    }
  }

  private loadUserLocation(): void {
    // Vérifier si une position est déjà stockée
    const storedLocation = this.geolocationService.location$;
    storedLocation.subscribe(location => {
      if (location) {
        // Centrer la carte sur la position de l'utilisateur avec un zoom adapté
        this.center = [location.longitude, location.latitude];
        this.zoom = 9; // Zoom sur la région (ville/département)
        
        // Si la carte est déjà initialisée, la recentrer
        if (this.map) {
          this.map.flyTo({
            center: this.center,
            zoom: this.zoom,
            duration: 2000 // animation de 2 secondes
          });
        }
      }
    });

    // Si pas de position stockée, demander la géolocalisation
    if (!this.geolocationService.hasPermission()) {
      this.geolocationService.requestLocation()
        .then(coords => {
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
        .catch(error => {
          console.log('Géolocalisation non disponible:', error.message);
          // Garder le centre par défaut (France)
        });
    }
  }

  ngAfterViewInit(): void {
    this.initializeMap();
  }

  ngOnDestroy(): void {
    if (this.subscription) this.subscription.unsubscribe();
    if (this.map) this.map.remove();
  }

  loadCrises() {
    this.subscription = this.crisisService.getAllCrisis().subscribe({
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

  jsonToGeoJSON(data: any[]) {
    return {
      type: 'FeatureCollection',
      features: data
        .filter(d => d.latitude && d.longitude)
        .map(d => ({
          type: 'Feature',
          geometry: {
            type: 'Point',
            coordinates: [
              Number(d.longitude),
              Number(d.latitude)
            ]
          },
          properties: {
            ...d
          }
        }))
    };
  }

  loadHelpData() {
    this.subscription = forkJoin({
      requests: this.requestService.getAllRequests(),
      proposals: this.offerService.getAllOffers()
    }).subscribe({
      next: ({ requests, proposals }) => {
        console.log('Requests:', requests);
        console.log('Proposals:', proposals);

        this.requests = requests;
        this.offers = proposals;

        this.requestGeoJSON = this.jsonToGeoJSON(requests);
        this.proposalGeoJSON = this.jsonToGeoJSON(proposals);

        if (this.map) {
          this.addSourceAndLayers();
        }
      },
      error: (err) => console.error('Erreur API:', err)
    });
  }

  private addSourceAndLayers(): void {
    if (!this.map) return;
    const geoJsonList = [this.requestGeoJSON, this.proposalGeoJSON];
    const mergedGeoJSON: FeatureCollection<Geometry> = {
        type: 'FeatureCollection',
        features: geoJsonList.flatMap(geoJson => geoJson ? geoJson.features : [])
        };
    console.log('Merged GeoJSON:', mergedGeoJSON);
    this.map.on('load', () => {
      // Ajout de la source pour les demandes d'aide
      if (mergedGeoJSON) {
        this.map!.addSource('clusters', {
          type: 'geojson',
          data: mergedGeoJSON,
          cluster: true,
          clusterMaxZoom: 8, // Max zoom to cluster points on
          clusterRadius: 50 // Radius of each cluster when clustering points (defaults to 50)
        });
      }
      this.map!.addLayer({
        id: 'clusters-layer',
        type: 'circle',
        source: 'clusters',
        filter: ['has', 'point_count'],
        paint: {
                'circle-color': [
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
                'circle-radius': [
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

        this.map!.addLayer({
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

        this.map!.on('click', 'unclustered-point', (e) => {
            if (!e.features || e.features.length === 0) return;
            const geometry = e.features[0].geometry as GeoJSON.Point;
            let offerRequest: string;
            const coordinates = geometry.coordinates.slice() as [number, number];
            const statut = e.features[0].properties['statut'] || 'N/A';
            const titre = e.features[0].properties['titre'] || 'N/A';
            let name: string;
            if ('nom_demande' in e.features[0].properties) {
              offerRequest = 'la demande';
              name = e.features[0].properties['nom_demande'] || 'N/A';
            }
            else {
              offerRequest = 'l\'offre';
              name = e.features[0].properties['nom_offre'] || 'N/A';
            }
            while (Math.abs(e.lngLat.lng - coordinates[0]) > 180) {
                coordinates[0] += e.lngLat.lng > coordinates[0] ? 360 : -360;
            }

            new maplibregl.Popup()
                .setLngLat(coordinates)
                .setHTML(
                    `Nom de ${offerRequest}: ${name}<br>Statut de ${offerRequest}: ${statut}`
                )
                .addTo(this.map!);
        });
        
          this.map!.addLayer({
            id: 'unclustered-point',
            type: 'circle',
            source: 'clusters',
            filter: ['!', ['has', 'point_count']],
            paint: {
                'circle-color': [
                'case',
                ['has', 'nom_demande'],
                '#ff0000',
                '#11b4da'
                ],
                'circle-radius': 5,
                'circle-stroke-width': 1,
                'circle-stroke-color': '#fff'
            }
        });

        this.map!.on('click', 'clusters-layer', async (e) => {
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

        this.map!.on('mouseenter', 'clusters-layer', () => {
            this.map!.getCanvas().style.cursor = 'pointer';
        });
        this.map!.on('mouseleave', 'clusters-layer', () => {
            this.map!.getCanvas().style.cursor = '';
        });
        this.addHullLayer();
        this.addHoverEffect();
    });
  }

  private addHullLayer() {

    this.map!.addSource('cluster-hull', {
      type: 'geojson',
      data: {
        type: 'FeatureCollection',
        features: []
      }
    });

    this.map!.addLayer({
      id: 'cluster-hull-fill',
      type: 'fill',
      source: 'cluster-hull',
      paint: {
        'fill-color': '#0099ff',
        'fill-opacity': 0.25
      }
    });

    this.map!.addLayer({
      id: 'cluster-hull-line',
      type: 'line',
      source: 'cluster-hull',
      paint: {
        'line-color': '#0066cc',
        'line-width': 2
      }
    });
  }

private addHoverEffect() {

    const source = this.map!.getSource('clusters') as maplibregl.GeoJSONSource;

    this.map!.on('mouseenter', 'clusters-layer', async (e) => {

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

    this.map!.on('mouseleave', 'clusters-layer', () => {

      this.map!.getCanvas().style.cursor = '';

      const hullSource = this.map!.getSource('cluster-hull') as maplibregl.GeoJSONSource;
      hullSource?.setData({
        type: 'FeatureCollection',
        features: []
      });
    });
  }

  private initializeMap(): void {
    this.map = new maplibregl.Map({
      container: this.mapContainer.nativeElement,
      style: 'https://raw.githubusercontent.com/go2garret/maps/main/src/assets/json/openStreetMap.json', 
      center: this.center,
      zoom: this.zoom
    });

    this.map.addControl(new maplibregl.NavigationControl(), 'top-right');

    this.map.on('load', () => {
      // Si on a déjà des données (reçues avant le chargement de la carte), on affiche
      if (this.crises.length > 0) {
        this.addCrisisMarkers();
        const circleGeojson: FeatureCollection<Polygon> = {
        type: 'FeatureCollection',
        features: this.crisisCircle
        };
        this.map!.addSource('location-radius', {
          type: 'geojson',
          data: circleGeojson
        });
        console.log('Circle GeoJSON:', circleGeojson);
        this.map!.addLayer({
          id: 'location-radius',
          type: 'fill',
          source: 'location-radius',
          paint: {
            'fill-color': '#8CCFFF',
            'fill-opacity': 0.5
          }
        });

        this.map!.on('click', 'location-radius', (e) => {
        const properties = e.features?.[0]?.properties || {};
        console.log('Crisis properties:', properties);
        new maplibregl.Popup()
        .setHTML(`
          <div style="color: black; font-family: sans-serif;">
            <h3 style="margin: 0 0 5px 0;">${properties?.['nom'] || 'Nom inconnu'}</h3>
            <p style="margin: 0;">${properties?.['description'] || 'Pas de description'}</p>
            <br>
            <small>Créé le : ${new Date(properties?.['date_debut'] || Date.now()).toLocaleDateString()}</small>
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

    // Nettoyage
    this.CrisisMarkers.forEach(marker => marker.remove());
    this.CrisisMarkers = [];
    this.crisisCircle = [];

    this.crises.forEach(crisis => {
      // MapLibre attend : [Longitude, Latitude]
      if (crisis.latitude && crisis.longitude) {
        console.log('Ajout de la crise sur la carte:', crisis);
        const radiusCenter = [crisis.longitude, crisis.latitude] as [number, number];
        const radius = 10; // kilometer
        const circle = turf.circle(radiusCenter, radius, {steps: 64, units: 'kilometers'})
        circle.properties = {center: radiusCenter, radius: radius, nom: crisis.nom, description: crisis.description, date_debut: crisis.date_debut};
        this.crisisCircle.push(circle);
      }
    });
  }
}
