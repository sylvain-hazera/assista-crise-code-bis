import { Component, OnDestroy, OnInit, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import maplibregl from 'maplibre-gl';

import { TeamService } from '../../services/team.service';
import { DossierService } from '../../services/dossier.service';
import { RequestService } from '../../services/request.service';
import { InformationService } from '../../services/information.service';

import { Team } from '../../shared/models/team.model';
import { Dossier } from '../../shared/models/dossier.model';

const STATUT_LABELS: Record<string, string> = {
  EN_ATTENTE_DISTRIBUTION: 'En attente de distribution',
  NOUVEAU: 'Nouveau',
  EN_ATTENTE_AFFECTATION: "En attente d'affectation",
  AFFECTE: 'Affecté à une équipe',
  EN_COURS: 'En cours de traitement',
  RESOLU: 'Résolu',
  CLOTURE: 'Clôturé',
};

const PRIORITE_OPTIONS: { value: Dossier['priorite']; label: string }[] = [
  { value: 'URGENTE', label: 'Urgente' },
  { value: 'NORMALE', label: 'Normale' },
  { value: 'BASSE', label: 'Basse' },
];

// Le tri par priorité prime toujours sur l'ordre manuel : un dossier urgent doit remonter en
// tête même s'il vient d'être ajouté (ordre par défaut à 0, sinon systématiquement premier
// quelle que soit sa priorité — ce qui n'a pas de sens opérationnellement).
const PRIORITE_RANG: Record<string, number> = { URGENTE: 0, NORMALE: 1, BASSE: 2 };

const PRIORITE_COULEUR: Record<string, string> = { URGENTE: '#dc2626', NORMALE: '#f59e0b', BASSE: '#3b82f6' };

@Component({
  selector: 'app-mes-interventions',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './mes-interventions.component.html',
  styleUrl: './mes-interventions.component.scss',
})
export class MesInterventionsComponent implements OnInit, OnDestroy {
  @ViewChild('minimapContainer') minimapContainer?: ElementRef;

  isLoading = true;
  errorMessage = '';

  teams: Team[] = [];
  allDossiers: Dossier[] = [];
  selectedTeamId: string | 'ALL' = 'ALL';
  statutFilter: string | 'ALL' = 'ALL';

  photoUrls: Record<string, string> = {};
  savingDossierId: string | null = null;

  readonly priorites = PRIORITE_OPTIONS;
  readonly statutOptions = Object.entries(STATUT_LABELS).map(([value, label]) => ({ value, label }));

  private map: maplibregl.Map | null = null;

  constructor(
    private teamService: TeamService,
    private dossierService: DossierService,
    private requestService: RequestService,
    private informationService: InformationService,
  ) {}

  ngOnInit(): void {
    this.teamService.mesEquipes().subscribe({
      next: (teams) => {
        this.teams = teams;
        if (!teams.length) {
          this.isLoading = false;
          return;
        }
        // Vue "de management PAR équipe" : on démarre sur la première équipe, pas sur un
        // mélange "toutes mes équipes" qui n'a pas de zone/minimap cohérente à afficher.
        this.selectedTeamId = teams[0].id!;
        this.loadDossiers();
      },
      error: () => {
        this.errorMessage = 'Impossible de charger vos équipes.';
        this.isLoading = false;
      },
    });
  }

  private loadDossiers(): void {
    const teamIds = new Set(this.teams.map(t => t.id));
    this.dossierService.getAll().subscribe({
      next: (dossiers) => {
        this.allDossiers = dossiers.filter(d => d.equipe && teamIds.has(d.equipe));
        this.isLoading = false;
        this.allDossiers.filter(d => d.demande || d.information).forEach(d => this.loadDossierPhoto(d));
        setTimeout(() => this.refreshMinimap());
      },
      error: () => {
        this.errorMessage = 'Impossible de charger les dossiers de vos équipes.';
        this.isLoading = false;
      },
    });
  }

  private loadDossierPhoto(dossier: Dossier): void {
    const service = dossier.demande ? this.requestService : this.informationService;
    const id = dossier.demande || dossier.information;
    if (!id) return;
    service.preview(id).subscribe({
      next: (blob) => { this.photoUrls[dossier.id] = URL.createObjectURL(blob); },
      error: () => {},
    });
  }

  statutLabel(statut: string): string {
    return STATUT_LABELS[statut] || statut;
  }

  teamName(teamId: string | undefined): string {
    return this.teams.find(t => t.id === teamId)?.name || '—';
  }

  get selectedTeam(): Team | null {
    return this.selectedTeamId === 'ALL' ? null : (this.teams.find(t => t.id === this.selectedTeamId) ?? null);
  }

  onTeamChange(): void {
    setTimeout(() => this.refreshMinimap());
  }

  get filteredDossiers(): Dossier[] {
    let list = this.allDossiers;
    if (this.selectedTeamId !== 'ALL') {
      list = list.filter(d => d.equipe === this.selectedTeamId);
    }
    if (this.statutFilter !== 'ALL') {
      list = list.filter(d => d.statut === this.statutFilter);
    }
    return [...list].sort((a, b) => {
      const rangA = PRIORITE_RANG[a.priorite] ?? 1;
      const rangB = PRIORITE_RANG[b.priorite] ?? 1;
      if (rangA !== rangB) return rangA - rangB;
      return a.ordre - b.ordre;
    });
  }

  /** Le réordonnancement manuel n'a de sens qu'au sein d'une même équipe (chaque équipe gère
   * sa propre tournée) : les flèches haut/bas ne sont donc affichées que si une équipe précise
   * est sélectionnée, jamais sur la vue "toutes mes équipes" mélangeant plusieurs tournées. */
  get canReorder(): boolean {
    return this.selectedTeamId !== 'ALL';
  }

  moveUp(dossier: Dossier): void {
    const list = this.filteredDossiers;
    const index = list.findIndex(d => d.id === dossier.id);
    if (index <= 0) return;
    this.swapOrdre(dossier, list[index - 1]);
  }

  moveDown(dossier: Dossier): void {
    const list = this.filteredDossiers;
    const index = list.findIndex(d => d.id === dossier.id);
    if (index === -1 || index >= list.length - 1) return;
    this.swapOrdre(dossier, list[index + 1]);
  }

  private swapOrdre(a: Dossier, b: Dossier): void {
    const ordreA = a.ordre;
    const ordreB = b.ordre;
    this.savingDossierId = a.id;
    this.dossierService.definirPriorite(a.id, { ordre: ordreB }).subscribe({
      next: (updated) => { a.ordre = updated.ordre; },
      error: () => {},
      complete: () => { this.savingDossierId = null; },
    });
    this.dossierService.definirPriorite(b.id, { ordre: ordreA }).subscribe({
      next: (updated) => { b.ordre = updated.ordre; },
      error: () => {},
    });
  }

  onPrioriteChange(dossier: Dossier, priorite: Dossier['priorite']): void {
    this.savingDossierId = dossier.id;
    this.dossierService.definirPriorite(dossier.id, { priorite }).subscribe({
      next: (updated) => { dossier.priorite = updated.priorite; },
      error: () => {},
      complete: () => { this.savingDossierId = null; },
    });
  }

  /** Lien "itinéraire" vers Google Maps depuis la position actuelle du terrain jusqu'au
   * dossier — ouvre l'appli maps native sur mobile, Google Maps web sinon. */
  mapsDirectionsUrl(dossier: Dossier): string | null {
    if (dossier.latitude == null || dossier.longitude == null) return null;
    return `https://www.google.com/maps/dir/?api=1&destination=${dossier.latitude},${dossier.longitude}`;
  }

  // ── Minimap de la zone de l'équipe sélectionnée ──────────────────────────────

  private refreshMinimap(): void {
    if (!this.minimapContainer) return;

    const dossiers = this.filteredDossiers.filter(d => d.latitude != null && d.longitude != null);
    const coords: [number, number][] = dossiers.map(d => [d.longitude!, d.latitude!]);

    if (!this.map) {
      this.map = new maplibregl.Map({
        container: this.minimapContainer.nativeElement,
        style: 'https://raw.githubusercontent.com/go2garret/maps/main/src/assets/json/openStreetMap.json',
        center: coords[0] ?? [2.2137, 46.2276],
        zoom: coords.length ? 11 : 5,
      });
      this.map.addControl(new maplibregl.NavigationControl(), 'top-right');
      this.map.on('load', () => this.drawMinimapLayers(dossiers, coords));
    } else if (this.map.isStyleLoaded()) {
      this.drawMinimapLayers(dossiers, coords);
    } else {
      this.map.once('load', () => this.drawMinimapLayers(dossiers, coords));
    }
  }

  private drawMinimapLayers(dossiers: Dossier[], coords: [number, number][]): void {
    if (!this.map) return;
    const map = this.map;

    const zoneGeojson = this.selectedTeam?.zone_precise_geojson ?? null;
    const zoneSource = map.getSource('zone-equipe') as maplibregl.GeoJSONSource | undefined;
    if (zoneGeojson) {
      const feature: GeoJSON.Feature = { type: 'Feature', properties: {}, geometry: zoneGeojson as any };
      if (zoneSource) {
        zoneSource.setData(feature);
      } else {
        map.addSource('zone-equipe', { type: 'geojson', data: feature });
        map.addLayer({ id: 'zone-equipe-fill', type: 'fill', source: 'zone-equipe', paint: { 'fill-color': '#8CCFFF', 'fill-opacity': 0.3 } });
        map.addLayer({ id: 'zone-equipe-line', type: 'line', source: 'zone-equipe', paint: { 'line-color': '#3b82f6', 'line-width': 2 } });
      }
    } else if (zoneSource) {
      zoneSource.setData({ type: 'FeatureCollection', features: [] });
    }

    const dossierFeatures: GeoJSON.Feature[] = dossiers.map(d => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [d.longitude!, d.latitude!] },
      properties: {
        titre: d.titre,
        numero: d.numero,
        priorite: d.priorite,
        color: PRIORITE_COULEUR[d.priorite] ?? '#6b7280',
      },
    }));
    const dossierSource = map.getSource('dossiers-equipe') as maplibregl.GeoJSONSource | undefined;
    const dossierData: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: dossierFeatures };
    if (dossierSource) {
      dossierSource.setData(dossierData);
    } else {
      map.addSource('dossiers-equipe', { type: 'geojson', data: dossierData });
      map.addLayer({
        id: 'dossiers-equipe-layer',
        type: 'circle',
        source: 'dossiers-equipe',
        paint: {
          'circle-color': ['get', 'color'],
          'circle-radius': 7,
          'circle-stroke-width': 2,
          'circle-stroke-color': '#fff',
        },
      });
      map.on('click', 'dossiers-equipe-layer', (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const coordinates = (f.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
        new maplibregl.Popup()
          .setLngLat(coordinates)
          .setHTML(`<strong>${f.properties?.['titre']}</strong><br>${f.properties?.['numero']}`)
          .addTo(map);
      });
      map.on('mouseenter', 'dossiers-equipe-layer', () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'dossiers-equipe-layer', () => { map.getCanvas().style.cursor = ''; });
    }

    if (coords.length > 1) {
      const bounds = coords.reduce((b, c) => b.extend(c), new maplibregl.LngLatBounds(coords[0], coords[0]));
      map.fitBounds(bounds, { padding: 50, maxZoom: 13 });
    } else if (coords.length === 1) {
      map.flyTo({ center: coords[0], zoom: 12 });
    }
  }

  ngOnDestroy(): void {
    Object.values(this.photoUrls).forEach(url => URL.revokeObjectURL(url));
    this.map?.remove();
  }
}
