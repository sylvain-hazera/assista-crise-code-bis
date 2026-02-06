import { Component, OnInit, OnDestroy, AfterViewInit, Input, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import maplibregl from 'maplibre-gl';
import { CrisisService, Crisis } from '../../../../services/crisis.service';
import { HelpRequestService, HelpRequest } from '../../../../services/help-request.service';
import { HelpProposeService, HelpPropose } from '../../../../services/help-propose.service';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-map',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './map.component.html',
  styleUrl: './map.component.scss'
})
export class MapComponent implements OnInit, AfterViewInit, OnDestroy {
  // Référence directe à la div HTML
  @ViewChild('mapContainer') mapContainer!: ElementRef;

  @Input() crises: Crisis[] = [];
  @Input() helpRequests: HelpRequest[] = [];
  @Input() helpProposals: HelpPropose[] = [];
  // Centre de la France par défaut
  @Input() center: [number, number] = [2.2137, 46.2276]; 
  @Input() zoom: number = 5;
  
  private map: maplibregl.Map | null = null;
  private markers: maplibregl.Marker[] = [];
  private subscription: Subscription | null = null;

  constructor(private crisisService: CrisisService,
              private helpRequestService: HelpRequestService,
              private helpProposalService: HelpProposeService) {}

  ngOnInit(): void {
    // Si pas de données en entrée, on charge depuis le service
    // if (this.crises.length === 0) {
    //   this.loadCrises();
    // }
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

  // loadCrises() {
  //   this.subscription = this.crisisService.getAllCrises().subscribe({
  //     next: (crises) => {
  //       console.log('Données de crises reçues:', crises);
  //       this.crises = crises;
  //       if (this.map) {
  //         this.addCrisisMarkers();
  //       }
  //     },
  //     error: (error) => console.error('Erreur API:', error)
  //   });
  // }

  loadHelpRequests() {
    this.subscription = this.helpRequestService.getAllRequests().subscribe({
      next: (helpRequests) => {
        console.log('Données de demandes d\'aide reçues:', helpRequests);
        this.helpRequests = helpRequests;
        if (this.map) {
            this.addHelpRequestMarkers();
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
      // if (this.crises.length > 0) {
      //   this.addCrisisRadius();
      // }
      if (this.helpRequests.length > 0) {
        this.addHelpRequestMarkers();
      }
      if (this.helpProposals.length > 0) {
        this.addHelpProposalMarkers();
      }
    });
  }

  // private addCrisisRadius(): void {
  //   if (!this.map) return;
  //   this.crises.forEach(crisis => {
  //     if (crisis.longitude && crisis.latitude) {
        
  //     }
  //   });
  // }
  private addHelpRequestMarkers(): void {
    if (!this.map) return;

    // Nettoyage
    this.markers.forEach(marker => marker.remove());
    this.markers = [];

    this.helpRequests.forEach(request => {
      // MapLibre attend : [Longitude, Latitude]
      if (request.longitude && request.latitude) {
        // Création du Popup HTML
        const popupContent = `
          <div style="color: black; font-family: sans-serif;">
            <h3 style="margin: 0 0 5px 0;">Demande d'aide</h3>
            <p style="margin: 5px 0;">Titre : ${request.titre || 'N/A'}</p>
            // <p style="margin: 0;">Type : ${request.type_demande}</p>
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