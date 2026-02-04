import { Component, OnInit, OnDestroy, AfterViewInit, Input, ViewChild, ElementRef } from '@angular/core';
import maplibregl from 'maplibre-gl';
import { CrisisService } from '../../../../services/crisis.service';
import { Subscription } from 'rxjs';
import { Crisis } from '../../../models/crisis.model';
import { OfferService } from '../../../../services/offer.service';
import { Offer } from '../../../models/offer.model';
import { RequestService } from '../../../../services/request.service';
import { Request } from '../../../models/request.model';

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
  private markers: maplibregl.Marker[] = [];
  private subscription: Subscription | null = null;

  constructor(private crisisService: CrisisService,
              private requestService: RequestService,
              private offerService: OfferService) {}

  ngOnInit(): void {
    // Si pas de données en entrée, on charge depuis le service
    if (this.crises.length === 0) {
      this.loadCrises();
    }
    if (this.requests.length === 0) {
      this.loadHelpRequests();
    }
    if (this.offers.length === 0) {
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

  loadHelpRequests() {
    this.subscription = this.requestService.getAllRequests().subscribe({
      next: (requests) => {
        console.log('Données de demandes d\'aide reçues:', requests);
        this.requests = requests;
        if (this.map) {
            this.addHelpRequestMarkers();
        }
      },
      error: (error) => console.error('Erreur API:', error)
    });
  }

  loadHelpProposals() {
    this.subscription = this.offerService.getAllOffers().subscribe({
      next: (offers) => {
        console.log('Données de propositions d\'aide reçues:', offers);
        this.offers = offers;
        if (this.map) {
            this.addHelpProposalMarkers();
        }
      },
      error: (error) => console.error('Erreur API:', error)
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
      if (this.requests.length > 0) {
        this.addHelpRequestMarkers();
      }
      if (this.offers.length > 0) {
        this.addHelpProposalMarkers();
      }
    });
  }

  private addCrisisMarkers(): void {
    if (!this.map) return;

    // Nettoyage
    this.markers.forEach(marker => marker.remove());
    this.markers = [];

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

        this.markers.push(marker);
      }
    });
  }

  private addHelpRequestMarkers(): void {
    if (!this.map) return;

    // Nettoyage
    this.markers.forEach(marker => marker.remove());
    this.markers = [];

    this.requests.forEach(request => {
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

        this.markers.push(marker);
      }
    });
  }

  private addHelpProposalMarkers(): void {
    if (!this.map) return;

    // Nettoyage
    this.markers.forEach(marker => marker.remove());
    this.markers = [];

    this.offers.forEach(proposal => {
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

        this.markers.push(marker);
      }
    });
  }

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