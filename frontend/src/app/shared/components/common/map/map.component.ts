import { Component, OnInit, OnDestroy, AfterViewInit, Input, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import maplibregl from 'maplibre-gl';
import { CrisisService, Crisis } from '../../../../services/crisis.service';
import { HelpRequestService, HelpRequest } from '../../../../services/help-request.service';
import { HelpProposeService, HelpPropose } from '../../../../services/help-propose.service';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-map',
  imports: [],
  templateUrl: './map.component.html',
  styleUrl: './map.component.scss'
})
export class MapComponent {

  @Input() crises: Crisis[] = [];
  @Input() helpRequests: HelpRequest[] = [];
  @Input() helpProposals: HelpPropose[] = [];
  // Centre de la France par défaut
  @Input() center: [number, number] = [2.2137, 46.2276]; 
  @Input() zoom: number = 5;
  
  private map: maplibregl.Map | null = null;
  private CrisisMarkers: maplibregl.Marker[] = [];
  private requestGeoJSON: any = null;
  private proposalGeoJSON: any = null;
  private subscription: Subscription | null = null;

  constructor(private crisisService: CrisisService,
              private helpRequestService: HelpRequestService,
              private helpProposalService: HelpProposeService) {}
              
  ngOnInit(): void {
    // Si pas de données en entrée, on charge depuis le service
    if (this.crises.length === 0) {
      this.loadCrises();
    }
    if (this.helpRequests.length === 0) {
      this.loadHelpRequests();
    }
    if (this.helpProposals.length === 0) {
      this.loadHelpProposals();
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
    this.subscription = this.crisisService.getAllCrises().subscribe({
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

  loadHelpRequests() {
    this.subscription = this.helpRequestService.getAllRequests().subscribe({
      next: (helpRequests) => {
        console.log('Données de demandes d\'aide reçues:', helpRequests);
        this.helpRequests = helpRequests;
        if (this.map) {
          this.requestGeoJSON = this.jsonToGeoJSON(helpRequests);
          console.log('Help Requests GeoJSON:', this.requestGeoJSON);
          this.addSourceAndLayers();
          //this.addHelpRequestMarkers();
        }
      },
      error: (error) => console.error('Erreur API:', error)
    });
  }

  loadHelpProposals() {
    this.subscription = this.helpProposalService.getAllProposes().subscribe({
      next: (helpProposals) => {
        console.log('Données de propositions d\'aide reçues:', helpProposals);
        this.helpProposals = helpProposals;
        if (this.map) {
          this.proposalGeoJSON = this.jsonToGeoJSON(helpProposals);
          //this.addHelpProposalMarkers();
        }
      },
      error: (error) => console.error('Erreur API:', error)
    });
  }

  private addSourceAndLayers(): void {
    if (!this.map) return;
    const GeoJSON =  this.requestGeoJSON; //geojsonMerge.merge([this.requestGeoJSON, this.proposalGeoJSON]);
    console.log('Merged GeoJSON:', GeoJSON, this.requestGeoJSON);
    this.map.on('load', () => {
      // Ajout de la source pour les demandes d'aide
      if (GeoJSON) {
        this.map!.addSource('clusters', {
          type: 'geojson',
          data: GeoJSON,
          cluster: true,
          clusterMaxZoom: 14, // Max zoom to cluster points on
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
                    '#53d651',
                    2,
                    '#f1f075',
                    7,
                    '#f28cb1'
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

        this.map!.addLayer({
            id: 'unclustered-point',
            type: 'circle',
            source: 'clusters',
            filter: ['!', ['has', 'point_count']],
            paint: {
                'circle-color': '#11b4da',
                'circle-radius': 5,
                'circle-stroke-width': 1,
                'circle-stroke-color': '#fff'
            }
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
      }
      if (this.helpRequests.length > 0) {
        //this.addHelpRequestMarkers();
        this.requestGeoJSON = this.jsonToGeoJSON(this.helpRequests);
      }
      if (this.helpProposals.length > 0) {
        //this.addHelpProposalMarkers();
        this.proposalGeoJSON = this.jsonToGeoJSON(this.helpProposals);
      }
    });
  }

  private addCrisisMarkers(): void {
    if (!this.map) return;

    // Nettoyage
    this.CrisisMarkers.forEach(marker => marker.remove());
    this.CrisisMarkers = [];

    this.crises.forEach(crisis => {
      // MapLibre attend : [Longitude, Latitude]
      if (crisis.latitude && crisis.longitude) {
        
        // Création du Popup HTML
        const popupContent = `
          <div style="color: black; font-family: sans-serif;">
            <h3 style="margin: 0 0 5px 0;">${crisis.name}</h3>
            <p style="margin: 0;">${crisis.description || 'Pas de description'}</p>
            <br>
            <small>Créé le : ${new Date(crisis.createdAt || Date.now()).toLocaleDateString()}</small>
          </div>
        `;

        const popup = new maplibregl.Popup({ offset: 25 })
          .setHTML(popupContent);

        // Création du Marker
        const marker = new maplibregl.Marker({ color: this.getSeverityColor(crisis.severity || 'LOW') })
          .setLngLat([crisis.longitude, crisis.latitude])
          .setPopup(popup)
          .addTo(this.map!);

        this.CrisisMarkers.push(marker);
      }
    });
    
    /*this.map.addLayer({
        id: 'clusters',
        type: 'circle',
        source: this.CrisisMarkers,
        filter: ['has', 'point_count'],
        paint: {
          'circle-color': '#51bbd6',
          'circle-radius': ['step', ['get', 'point_count'], 20, 100, 30, 750, 40]
        }
      });*/
  }

  /*private addHelpRequestMarkers(): void {
    if (!this.map) return;

    // Nettoyage
    //this.HelpRequestMarkers.forEach(marker => marker.remove());
    //this.HelpRequestMarkers = [];

    this.helpRequests.forEach(request => {
      // MapLibre attend : [Longitude, Latitude]
      if (request.longitude && request.latitude) {
        // Création du Popup HTML
        const popupContent = `
          <div style="color: black; font-family: sans-serif;">
            <h3 style="margin: 0 0 5px 0;">Demande d'aide</h3>
            <p style="margin: 0;">Type : ${request.type_demande}</p>
            <br>
            <small>Créée le : ${new Date(request.date_creation || Date.now()).toLocaleDateString()}</small>
          </div>
        `;

        const popup = new maplibregl.Popup({ offset: 25 })
          .setHTML(popupContent);

        // Création du Marker
        const marker = new maplibregl.Marker({ color: '#d63200' }) // Couleur orange pour les demandes
          .setLngLat([request.longitude, request.latitude])
          .setPopup(popup)
          .addTo(this.map!);

        this.HelpRequestMarkers.push(marker);
      }
    });
  }*/

  /*private addHelpProposalMarkers(): void {
    if (!this.map) return;

    // Nettoyage
    this.HelpProposalMarkers.forEach(marker => marker.remove());
    this.HelpProposalMarkers = [];

    this.helpProposals.forEach(proposal => {
      // MapLibre attend : [Longitude, Latitude]
      if (proposal.longitude && proposal.latitude) {
        // Création du Popup HTML
        const popupContent = `
          <div style="color: black; font-family: sans-serif;">
            <h3 style="margin: 0 0 5px 0;">Proposition d'aide</h3>
            <br>
            <small>Créée le : ${new Date(proposal.createdAt || Date.now()).toLocaleDateString()}</small>
          </div>
        `;

        const popup = new maplibregl.Popup({ offset: 25 })
          .setHTML(popupContent);
        // Création du Marker
        const marker = new maplibregl.Marker({ color: '#0e1c8b' })
          .setLngLat([proposal.longitude, proposal.latitude])
          .setPopup(popup)
          .addTo(this.map!);

        this.HelpProposalMarkers.push(marker);
      }
    });
  }*/

  private getSeverityColor(severity: string): string {
    const colors: { [key: string]: string } = {
      'LOW': '#4CAF50',       // Vert
      'MEDIUM': '#FF9800',    // Orange
      'HIGH': '#F44336',      // Rouge
      'CRITICAL': '#B71C1C'   // Rouge foncé
    };
    // Retourne la couleur correspondante ou Bleu par défaut
    return colors[severity?.toUpperCase()] || '#2196F3';
  }
}
