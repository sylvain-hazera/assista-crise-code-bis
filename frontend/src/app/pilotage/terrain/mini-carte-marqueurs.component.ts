import {
  AfterViewInit, Component, DoCheck, ElementRef, EventEmitter, Input, OnDestroy, Output, ViewChild, signal,
} from '@angular/core';
import maplibregl from 'maplibre-gl';

import { styleCarte } from '../../shared/utils/carte-style';
import { MarqueurTerrain } from '../pilotage.service';

/** Couleur d'un marqueur selon son genre ; à traiter : cerclé de noir épais. */
export function couleurMarqueur(genre: string): string {
  switch (genre) {
    case 'FEU': case 'ROUTE_COUPEE': case 'DANGER': return '#dc2626';
    case 'PERSONNE': case 'BLESSE': case 'ROUTE_LIBEREE': return '#16a34a';
    case 'INONDATION': return '#0284c7';
    case 'REGROUPEMENT': return '#a16207';
    default: return '#f59e0b';
  }
}

/**
 * Carte des marqueurs terrain de la crise (26/11/2026). Toucher un marqueur le désigne dans la
 * liste ; en mode « poser », toucher la carte donne l'endroit du nouveau marqueur. Sans WebGL, la
 * carte s'efface : la liste suffit.
 */
@Component({
  selector: 'app-mini-carte-marqueurs',
  standalone: true,
  template: `
    @if (disponible()) {
      <div class="mini-carte" #hote role="img" [class.pose]="modePose"
           [attr.aria-label]="'Carte des marqueurs terrain : ' + marqueurs.length + ' marqueur(s)'"></div>
    } @else {
      <p class="sans-carte">Carte indisponible sur cet appareil : la liste ci-dessous suffit.</p>
    }
  `,
  styles: [`
    :host { display: block; }
    .mini-carte { height: 20rem; border-radius: 8px; overflow: hidden; border: 1px solid var(--ac-border, #d1d5db); }
    .mini-carte.pose { outline: 3px solid var(--brand-primary, #2563eb); cursor: crosshair; }
    .sans-carte { color: var(--ac-text-muted, #6b7280); font-size: .9rem; }
  `],
})
export class MiniCarteMarqueursComponent implements AfterViewInit, DoCheck, OnDestroy {
  @Input() marqueurs: MarqueurTerrain[] = [];
  @Input() modePose = false;
  @Output() choisi = new EventEmitter<string>();
  @Output() endroit = new EventEmitter<{ latitude: number; longitude: number }>();
  @ViewChild('hote') hote?: ElementRef<HTMLDivElement>;

  readonly disponible = signal(true);
  private map?: maplibregl.Map;
  private prete = false;
  private cadree = false;
  private dernierEtat = '';
  private repere?: maplibregl.Marker;

  ngAfterViewInit(): void {
    if (!this.hote) return;
    try {
      this.map = new maplibregl.Map({ container: this.hote.nativeElement, style: styleCarte(), center: [2.5, 46.5], zoom: 5,
                                      attributionControl: { compact: true } });
    } catch {
      this.disponible.set(false);
      return;
    }
    this.map.on('load', () => {
      const map = this.map!;
      map.addSource('marqueurs', { type: 'geojson', data: this.donnees() });
      map.addLayer({
        id: 'marqueurs', type: 'circle', source: 'marqueurs',
        paint: {
          'circle-radius': 9, 'circle-color': ['get', 'couleur'],
          'circle-stroke-color': ['case', ['get', 'a_traiter'], '#111827', '#ffffff'],
          'circle-stroke-width': ['case', ['get', 'a_traiter'], 3, 1.5],
        },
      });
      map.on('click', 'marqueurs', (e) => {
        if (this.modePose) return;
        const id = (e.features?.[0]?.properties as { id?: string } | undefined)?.id;
        if (id) this.choisi.emit(id);
      });
      map.on('click', (e) => {
        if (!this.modePose) return;
        this.repere?.remove();
        this.repere = new maplibregl.Marker({ color: '#2563eb' }).setLngLat(e.lngLat).addTo(map);
        this.endroit.emit({ latitude: e.lngLat.lat, longitude: e.lngLat.lng });
      });
      map.on('mouseenter', 'marqueurs', () => map.getCanvas().style.cursor = 'pointer');
      map.on('mouseleave', 'marqueurs', () => map.getCanvas().style.cursor = '');
      this.prete = true;
      this.dernierEtat = '';
      this.ngDoCheck();
    });
  }

  ngDoCheck(): void {
    if (!this.prete || !this.map) return;
    if (!this.modePose && this.repere) { this.repere.remove(); this.repere = undefined; }
    const etat = this.marqueurs.map(m => `${m.id}:${m.decision}`).join(',');
    if (etat === this.dernierEtat) return;
    this.dernierEtat = etat;
    (this.map.getSource('marqueurs') as maplibregl.GeoJSONSource | undefined)?.setData(this.donnees());
    this.cadrer();
  }

  ngOnDestroy(): void { this.map?.remove(); }

  donnees(): GeoJSON.FeatureCollection {
    return {
      type: 'FeatureCollection',
      features: this.marqueurs.map(m => ({
        type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates: [m.longitude, m.latitude] },
        properties: { id: m.id, couleur: couleurMarqueur(m.genre), a_traiter: m.decision === 'A_TRAITER' },
      })),
    };
  }

  private cadrer(): void {
    if (this.cadree || !this.map || !this.marqueurs.length) return;
    this.cadree = true;
    if (this.marqueurs.length === 1) {
      this.map.jumpTo({ center: [this.marqueurs[0].longitude, this.marqueurs[0].latitude], zoom: 14 });
      return;
    }
    const bornes = new maplibregl.LngLatBounds();
    this.marqueurs.forEach(m => bornes.extend([m.longitude, m.latitude]));
    this.map.fitBounds(bornes, { padding: 30, maxZoom: 15, duration: 0 });
  }
}
