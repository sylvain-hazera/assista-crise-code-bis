import { Component, OnInit, OnDestroy, AfterViewInit, Input, ViewChild, ElementRef } from '@angular/core';
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
import type { FeatureCollection, Geometry, Polygon } from 'geojson';
import { AuthService } from '../../../../auth/services/auth.service';
import { InformationService } from '../../../../services/information.service';

@Component({
  selector: 'app-map',
  standalone: true,
  imports: [],
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
  
  private map: maplibregl.Map | null = null;
  private crisisCircle: any[] = [];
  private requestGeoJSON: any = null;
  private proposalGeoJSON: any = null;
  private informationsGeoJSON: any = null;
  private subscription: Subscription | null = null;

  constructor(private crisisService: CrisisService,
              private requestService: RequestService,
              private offerService: OfferService,
              private informationService: InformationService,
              private geolocationService: GeolocationService,
              private authService: AuthService) {}
  ngOnInit(): void {
    // Load user location and center map on it if available, otherwise keep default center
    this.loadUserLocation();
    
    // If crises, requests, or offers were not passed in as inputs, load them from the API
    if (this.crises.length === 0) {
      this.loadCrises();
    }
    if (this.requests.length === 0 || this.offers.length === 0) {
      this.loadHelpData();
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
          // Keep default center and zoom if geolocation fails or is denied
        });
    }
  }

  ngAfterViewInit(): void { // Initialize the map after the view is initialized to ensure the container is available
    this.initializeMap();
  }

  ngOnDestroy(): void { // Clean up subscriptions and map instance to prevent memory leaks
    if (this.subscription) this.subscription.unsubscribe();
    if (this.map) this.map.remove();
  }

  loadCrises() { // Charger les crises depuis l'API et les ajouter à la carte
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

  jsonToGeoJSON(data: any[]) { // Convert requests/offers data to GeoJSON format for MapLibre
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

  loadHelpData() { // Load both requests and offers in parallel and process them together to add to the map
    this.subscription = forkJoin({
      requests: this.requestService.getAll(),
      proposals: this.offerService.getAll(),
      informations: this.informationService.getAll()
    }).subscribe({
      next: ({ requests, proposals, informations }) => {
        console.log('Requests:', requests);
        console.log('Proposals:', proposals);
        console.log('Informations:', informations);

        this.requests = requests;
        this.offers = proposals;
        this.informations = informations;

        this.requestGeoJSON = this.jsonToGeoJSON(requests);
        this.proposalGeoJSON = this.jsonToGeoJSON(proposals);
        this.informationsGeoJSON = this.jsonToGeoJSON(informations);

        if (this.map) {
          this.addSourceAndLayers();
        }
      },
      error: (err) => console.error('Erreur API:', err)
    });
  }
  private addSourceAndLayers(): void {
    if (!this.map) return;
    const isAdmin = this.authService.isAdmin();
    const geoJsonList = [this.requestGeoJSON, this.proposalGeoJSON, this.informationsGeoJSON]; // Merge requests, offers and informations into a single GeoJSON
    const mergedGeoJSON: FeatureCollection<Geometry> = {
        type: 'FeatureCollection',
        features: geoJsonList.flatMap(geoJson => geoJson ? geoJson.features : [])
        };
    if (!isAdmin) { // If not admin, add random noise to coordinates to prevent exact location identification
      mergedGeoJSON.features.forEach(feature => {
        const geometry = feature.geometry as GeoJSON.Point;
        const originalCoords = geometry.coordinates as [number, number];
        geometry.coordinates = [
          originalCoords[0] + (Math.random() - 0.5) * 0.01,
          originalCoords[1] + (Math.random() - 0.5) * 0.01,
        ];
      });
    }
    this.map.on('load', () => {
      if (mergedGeoJSON) {
        this.map!.addSource('clusters', { // Add cluster source for both requests and offers
          type: 'geojson',
          data: mergedGeoJSON,
          cluster: true,
          clusterMaxZoom: 8,
          clusterRadius: 50
        });
      }
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
              if (isAdmin){ // Only show requester/offerer names to admins
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

            new maplibregl.Popup() // Create a popup with details about the request/offer
                .setLngLat(coordinates)
                .setHTML(
                    `Nom de ${offerRequest}: ${title}<br>Statut de ${offerRequest}: ${statut}<br>Description: ${description}${name}${first_name}`
                )
                .addTo(this.map!);
        });
        
          this.map!.addLayer({ // Layer for individual points (requests and offers) that are not clustered
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
    });
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

  private initializeMap(): void { // Initialisation de la carte MapLibre
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
        // Trier les cercles par rayon pour que les petits cercles soient visibles par-dessus les grands
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
      // Create a circle for each crisis
      if (crisis.latitude && crisis.longitude) {
        let radiusCenter = [crisis.longitude, crisis.latitude] as [number, number];
        let radius = crisis.radius || 10; // Utiliser le rayon de la crise ou 10km par défaut
        let circle = turf.circle(radiusCenter, radius, {steps: 64, units: 'kilometers'})
        circle.properties = {center: radiusCenter, radius: radius, name: crisis.name, description: crisis.description, start_date: crisis.start_date, type: crisis.type};
        
        // Fusionner les cercles du même type qui se chevauchent
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