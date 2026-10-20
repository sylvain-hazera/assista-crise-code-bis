import { Component, OnInit, OnDestroy, AfterViewInit, Input, Output, EventEmitter, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { styleCarte } from '../../../shared/utils/carte-style';
import maplibregl from 'maplibre-gl';
import type { FeatureCollection, Geometry } from 'geojson';

import { HabitationService, HabitationFiltres } from '../../../services/habitation.service';
import { Habitation, COULEURS_STATUT_EVALUATION } from '../../../shared/models/habitation.model';

/** Carte dédiée au référencement des dégâts (Le Porge et communes suivantes) -- volontairement
 * un composant autonome plutôt qu'un calque de plus dans MapComponent (déjà très chargé,
 * 1400+ lignes, pensé pour la carte générale de crise) : cette carte a un cas d'usage et un
 * cycle de vie propres (une commune/zone à la fois, rechargée à chaque changement de filtre). */
@Component({
  selector: 'app-habitation-carte',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './habitation-carte.component.html',
  styleUrl: './habitation-carte.component.scss',
})
export class HabitationCarteComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('mapContainer') mapContainer!: ElementRef;

  @Input() filtres: HabitationFiltres = {};
  @Input() center: [number, number] = [2.2137, 46.2276];
  @Input() zoom = 5;
  @Output() pointClique = new EventEmitter<Habitation>();

  habitations: Habitation[] = [];
  chargement = true;

  private map: maplibregl.Map | null = null;
  private mapPret = false;
  private geojson: FeatureCollection<Geometry> | null = null;

  constructor(private habitationService: HabitationService) {}

  ngOnInit(): void {
    this.charger();
  }

  ngAfterViewInit(): void {
    this.map = new maplibregl.Map({
      container: this.mapContainer.nativeElement,
      style: styleCarte(),
      center: this.center,
      zoom: this.zoom,
    });
    this.map.addControl(new maplibregl.NavigationControl(), 'top-right');
    this.map.on('load', () => {
      this.mapPret = true;
      if (this.geojson) this.afficherPoints();
    });
  }

  ngOnDestroy(): void {
    this.map?.remove();
  }

  recharger(filtres: HabitationFiltres): void {
    this.filtres = filtres;
    this.charger();
  }

  private charger(): void {
    this.chargement = true;
    this.habitationService.getAll(this.filtres).subscribe({
      next: (habitations) => {
        this.habitations = habitations;
        this.chargement = false;
        this.geojson = {
          type: 'FeatureCollection',
          features: habitations
            .filter(h => h.latitude != null && h.longitude != null)
            .map(h => ({
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [h.longitude as number, h.latitude as number] },
              properties: {
                id: h.id,
                adresse: h.adresse,
                statut_evaluation: h.statut_evaluation,
                statut_chantier: h.statut_chantier || '',
              },
            })),
        };
        if (this.mapPret) this.afficherPoints();
        this.centrerSurPoints();
      },
      error: () => { this.chargement = false; },
    });
  }

  private centrerSurPoints(): void {
    if (!this.map || this.habitations.length === 0) return;
    const pts = this.habitations.filter(h => h.latitude != null && h.longitude != null);
    if (pts.length === 0) return;
    const bounds = new maplibregl.LngLatBounds();
    pts.forEach(h => bounds.extend([h.longitude as number, h.latitude as number]));
    this.map.fitBounds(bounds, { padding: 60, maxZoom: 17, duration: 0 });
  }

  private afficherPoints(): void {
    if (!this.map || !this.geojson) return;
    const source = this.map.getSource('habitations') as maplibregl.GeoJSONSource | undefined;
    if (source) { source.setData(this.geojson); return; }

    this.map.addSource('habitations', { type: 'geojson', data: this.geojson });

    this.map.addLayer({
      id: 'habitations-layer',
      type: 'circle',
      source: 'habitations',
      paint: {
        'circle-color': [
          'match', ['get', 'statut_evaluation'],
          'PAS_DE_DEGATS', COULEURS_STATUT_EVALUATION.PAS_DE_DEGATS,
          'DEGATS_FAIBLES', COULEURS_STATUT_EVALUATION.DEGATS_FAIBLES,
          'DEGATS_FORTS', COULEURS_STATUT_EVALUATION.DEGATS_FORTS,
          COULEURS_STATUT_EVALUATION.NON_EVALUEE,
        ],
        'circle-radius': 8,
        'circle-stroke-width': 3,
        // Anneau vert = chantier terminé (dégâts traités) -- seule façon de distinguer d'un
        // coup d'œil, sur la carte, un point "dégâts forts en cours" d'un "dégâts forts réglés"
        // sans multiplier les couleurs (qui codent déjà l'évaluation).
        'circle-stroke-color': ['case', ['==', ['get', 'statut_chantier'], 'TERMINE'], '#166534', '#ffffff'],
      },
    });

    this.map.on('click', 'habitations-layer', (e) => {
      const id = e.features?.[0]?.properties?.['id'];
      const habitation = this.habitations.find(h => h.id === id);
      if (habitation) this.pointClique.emit(habitation);
    });
    this.map.on('mouseenter', 'habitations-layer', () => { this.map!.getCanvas().style.cursor = 'pointer'; });
    this.map.on('mouseleave', 'habitations-layer', () => { this.map!.getCanvas().style.cursor = ''; });
  }
}
