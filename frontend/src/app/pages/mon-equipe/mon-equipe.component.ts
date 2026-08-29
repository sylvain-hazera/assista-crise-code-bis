import { Component, OnDestroy, OnInit, ViewChild, ElementRef, AfterViewInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import maplibregl from 'maplibre-gl';

import { TeamService } from '../../services/team.service';
import { MissionService } from '../../services/mission.service';
import { DossierService } from '../../services/dossier.service';
import { PositionEquipeService } from '../../services/position-equipe.service';
import { RequestService } from '../../services/request.service';
import { InformationService } from '../../services/information.service';

import { Team } from '../../shared/models/team.model';
import { Mission } from '../../shared/models/mission.model';
import { Dossier } from '../../shared/models/dossier.model';
import { DernierePosition } from '../../shared/models/derniere-position.model';

const STATUT_LABELS: Record<string, string> = {
  EN_ATTENTE_DISTRIBUTION: 'En attente de distribution',
  NOUVEAU: 'Nouveau',
  EN_ATTENTE_AFFECTATION: "En attente d'affectation",
  AFFECTE: 'Affecté à une équipe',
  EN_COURS: 'En cours de traitement',
  RESOLU: 'Résolu',
  CLOTURE: 'Clôturé',
};

@Component({
  selector: 'app-mon-equipe',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './mon-equipe.component.html',
  styleUrl: './mon-equipe.component.scss',
})
export class MonEquipeComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('minimapContainer') minimapContainer!: ElementRef;

  isLoading = true;
  errorMessage = '';

  team: Team | null = null;
  missions: Mission[] = [];
  dossiers: Dossier[] = [];
  positions: DernierePosition[] = [];

  photoUrls: Record<string, string> = {};

  private teamId = '';
  private map: maplibregl.Map | null = null;

  constructor(
    private route: ActivatedRoute,
    private teamService: TeamService,
    private missionService: MissionService,
    private dossierService: DossierService,
    private positionEquipeService: PositionEquipeService,
    private requestService: RequestService,
    private informationService: InformationService,
  ) {}

  ngOnInit(): void {
    this.teamId = this.route.snapshot.params['id'];
    if (!this.teamId) {
      this.errorMessage = 'Équipe introuvable.';
      this.isLoading = false;
      return;
    }
    this.loadAll();
  }

  ngAfterViewInit(): void {
    // La carte a besoin du conteneur (rendu seulement une fois isLoading=false) : elle est
    // initialisée depuis loadAll() une fois les données arrivées, pas ici.
  }

  private loadAll(): void {
    forkJoin({
      team: this.teamService.getById(this.teamId),
      missions: this.missionService.getAll(),
      dossiers: this.dossierService.getAll(),
      positions: this.positionEquipeService.getAll(),
    }).subscribe({
      next: ({ team, missions, dossiers, positions }) => {
        this.team = team;
        this.missions = missions.filter(m => m.equipe_ids?.includes(this.teamId));
        this.dossiers = dossiers.filter(d => d.equipe === this.teamId);
        this.positions = positions.filter(p => p.team_ids?.includes(this.teamId));
        this.isLoading = false;

        this.dossiers.filter(d => d.demande || d.information).forEach(d => this.loadDossierPhoto(d));

        setTimeout(() => this.initMinimap());
      },
      error: () => {
        this.errorMessage = "Impossible de charger cette équipe : elle n'existe pas ou vous n'y avez plus accès.";
        this.isLoading = false;
      },
    });
  }

  statutLabel(statut: string): string {
    return STATUT_LABELS[statut] || statut;
  }

  /** Photo principale de la demande/du signalement à l'origine du dossier — 403/404 silencieux
   * si absente ou non accessible (pas d'erreur affichée, juste pas de vignette). */
  private loadDossierPhoto(dossier: Dossier): void {
    const service = dossier.demande ? this.requestService : this.informationService;
    const id = dossier.demande || dossier.information;
    if (!id) return;
    service.preview(id).subscribe({
      next: (blob) => { this.photoUrls[dossier.id] = URL.createObjectURL(blob); },
      error: () => {},
    });
  }

  private initMinimap(): void {
    if (!this.minimapContainer || this.map) return;

    const dossierPoints = this.dossiers.filter(d => d.latitude != null && d.longitude != null);
    const memberPoints = this.positions.filter(p => p.latitude != null && p.longitude != null);

    const allCoords: [number, number][] = [
      ...dossierPoints.map(d => [d.longitude!, d.latitude!] as [number, number]),
      ...memberPoints.map(p => [p.longitude!, p.latitude!] as [number, number]),
    ];

    const center: [number, number] = allCoords.length
      ? allCoords[0]
      : [2.2137, 46.2276];

    this.map = new maplibregl.Map({
      container: this.minimapContainer.nativeElement,
      style: 'https://raw.githubusercontent.com/go2garret/maps/main/src/assets/json/openStreetMap.json',
      center,
      zoom: allCoords.length ? 11 : 5,
    });
    this.map.addControl(new maplibregl.NavigationControl(), 'top-right');

    this.map.on('load', () => {
      if (!this.map) return;

      if (dossierPoints.length) {
        this.map.addSource('dossiers', {
          type: 'geojson',
          data: {
            type: 'FeatureCollection',
            features: dossierPoints.map(d => ({
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [d.longitude!, d.latitude!] },
              properties: { titre: d.titre, numero: d.numero, statut: this.statutLabel(d.statut) },
            })),
          },
        });
        this.map.addLayer({
          id: 'dossiers-layer',
          type: 'circle',
          source: 'dossiers',
          paint: { 'circle-color': '#ff0000', 'circle-radius': 6, 'circle-stroke-width': 1, 'circle-stroke-color': '#fff' },
        });
        this.map.on('click', 'dossiers-layer', (e) => {
          const f = e.features?.[0];
          if (!f) return;
          const coords = (f.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
          new maplibregl.Popup()
            .setLngLat(coords)
            .setHTML(`<strong>${f.properties?.['titre']}</strong><br>${f.properties?.['numero']}<br>${f.properties?.['statut']}`)
            .addTo(this.map!);
        });
        this.map.on('mouseenter', 'dossiers-layer', () => { this.map!.getCanvas().style.cursor = 'pointer'; });
        this.map.on('mouseleave', 'dossiers-layer', () => { this.map!.getCanvas().style.cursor = ''; });
      }

      if (memberPoints.length) {
        this.map.addSource('membres', {
          type: 'geojson',
          data: {
            type: 'FeatureCollection',
            features: memberPoints.map(p => ({
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [p.longitude!, p.latitude!] },
              properties: { nom: p.utilisateur_nom, horodatage: p.horodatage },
            })),
          },
        });
        this.map.addLayer({
          id: 'membres-layer',
          type: 'circle',
          source: 'membres',
          paint: { 'circle-color': '#9c27b0', 'circle-radius': 7, 'circle-stroke-width': 2, 'circle-stroke-color': '#fff' },
        });
        this.map.on('click', 'membres-layer', (e) => {
          const f = e.features?.[0];
          if (!f) return;
          const coords = (f.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
          const dateTxt = f.properties?.['horodatage'] ? new Date(f.properties['horodatage']).toLocaleString('fr-FR') : 'inconnue';
          new maplibregl.Popup()
            .setLngLat(coords)
            .setHTML(`<strong>${f.properties?.['nom']}</strong><br>Dernière position connue : ${dateTxt}`)
            .addTo(this.map!);
        });
        this.map.on('mouseenter', 'membres-layer', () => { this.map!.getCanvas().style.cursor = 'pointer'; });
        this.map.on('mouseleave', 'membres-layer', () => { this.map!.getCanvas().style.cursor = ''; });
      }

      if (allCoords.length > 1) {
        const bounds = allCoords.reduce(
          (b, c) => b.extend(c),
          new maplibregl.LngLatBounds(allCoords[0], allCoords[0])
        );
        this.map.fitBounds(bounds, { padding: 50, maxZoom: 13 });
      }
    });
  }

  ngOnDestroy(): void {
    Object.values(this.photoUrls).forEach(url => URL.revokeObjectURL(url));
    this.map?.remove();
  }
}
