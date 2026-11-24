import {
  AfterViewInit, Component, DoCheck, ElementRef, EventEmitter, Input, OnDestroy, Output, ViewChild, signal,
} from '@angular/core';
import maplibregl from 'maplibre-gl';

import { styleCarte } from '../../shared/utils/carte-style';
import { ActivationPointEau, CircuitEau } from '../pilotage.service';

type Candidat = NonNullable<CircuitEau['candidats']>[number];

/** Les couleurs de la mini-carte, les mêmes que la carte du CODIS pour les points ouverts. */
export const COULEURS_MINI_CARTE: Record<string, string> = {
  candidat: '#2563eb', choisi: '#ea580c', DEMANDE: '#f59e0b', EN_ROUTE: '#f59e0b', ACTIF: '#15803d', FERME: '#9ca3af',
};

/**
 * Mini-carte de l'onglet Eau (24/11/2026) : les points d'eau autour du feu, ceux qu'on coche et
 * ceux déjà ouverts. Toucher un point candidat le coche ou le décoche, comme dans la liste. Sans
 * WebGL, la carte s'efface : la liste suffit.
 */
@Component({
  selector: 'app-mini-carte-points-eau',
  standalone: true,
  template: `
    @if (disponible()) {
      <div class="mini-carte" #hote role="img"
           [attr.aria-label]="'Carte des points d’eau : ' + candidats.length + ' à proximité, ' + activations.length + ' ouverts'"></div>
      <ul class="legende" aria-hidden="true">
        <li><span [style.background]="couleurs['candidat']"></span>à proximité (toucher pour cocher)</li>
        <li><span [style.background]="couleurs['choisi']"></span>coché</li>
        <li><span [style.background]="couleurs['DEMANDE']"></span>demandé / en route</li>
        <li><span [style.background]="couleurs['ACTIF']"></span>actif</li>
        <li><span [style.background]="couleurs['FERME']"></span>fermé</li>
      </ul>
    }
  `,
  styles: [`
    :host { display: block; }
    .mini-carte { height: 18rem; border-radius: 8px; overflow: hidden; border: 1px solid var(--ac-border, #374151); }
    .legende { display: flex; flex-wrap: wrap; gap: .3rem .9rem; list-style: none; padding: 0; margin: .4rem 0 0;
               font-size: .78rem; color: var(--ac-text-muted, #9ca3af); }
    .legende li { display: inline-flex; align-items: center; gap: .3rem; }
    .legende span { width: .7rem; height: .7rem; border-radius: 50%; border: 1px solid #fff; display: inline-block; }
  `],
})
export class MiniCartePointsEauComponent implements AfterViewInit, DoCheck, OnDestroy {
  @Input() candidats: Candidat[] = [];
  @Input() activations: ActivationPointEau[] = [];
  @Input() choix: Record<number, boolean> = {};
  /** Le point touché sur la carte (un candidat) : à cocher ou décocher. */
  @Output() basculer = new EventEmitter<number>();
  @ViewChild('hote') hote?: ElementRef<HTMLDivElement>;

  readonly couleurs = COULEURS_MINI_CARTE;
  /** Signal : passé à faux après la vue (pas de WebGL), sans erreur de détection. */
  readonly disponible = signal(true);
  private map?: maplibregl.Map;
  private prete = false;
  private cadree = false;
  private dernierEtat = '';

  ngAfterViewInit(): void {
    if (!this.hote) return;
    try {
      this.map = new maplibregl.Map({ container: this.hote.nativeElement, style: styleCarte(), center: [2.5, 46.5], zoom: 5,
                                      attributionControl: { compact: true } });
    } catch {
      this.disponible.set(false);   // pas de WebGL
      return;
    }
    this.map.on('load', () => {
      const map = this.map!;
      map.addSource('points-eau', { type: 'geojson', data: this.donnees() });
      map.addLayer({
        id: 'points-eau', type: 'circle', source: 'points-eau',
        paint: {
          'circle-radius': ['case', ['==', ['get', 'genre'], 'candidat'], 6, 8],
          'circle-color': ['get', 'couleur'],
          'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.5,
        },
      });
      map.on('click', 'points-eau', (e) => {
        const p = e.features?.[0]?.properties as { id?: number; genre?: string; nom?: string } | undefined;
        if (!p) return;
        if (p.genre === 'activation') {
          new maplibregl.Popup().setLngLat(e.lngLat).setText(p.nom ?? '').addTo(map);
        } else if (p.id !== undefined) {
          this.basculer.emit(Number(p.id));
        }
      });
      map.on('mouseenter', 'points-eau', () => map.getCanvas().style.cursor = 'pointer');
      map.on('mouseleave', 'points-eau', () => map.getCanvas().style.cursor = '');
      this.prete = true;
      this.dernierEtat = '';
      this.ngDoCheck();
    });
  }

  /** Redessine seulement quand ce qui est montré change (points, cases cochées, états). */
  ngDoCheck(): void {
    if (!this.prete || !this.map) return;
    const etat = this.candidats.map(c => `${c.id}${this.choix[c.id] ? '*' : ''}`).join(',') + '|'
      + this.activations.map(a => `${a.id}:${a.statut}`).join(',');
    if (etat === this.dernierEtat) return;
    this.dernierEtat = etat;
    (this.map.getSource('points-eau') as maplibregl.GeoJSONSource | undefined)?.setData(this.donnees());
    this.cadrer();
  }

  ngOnDestroy(): void { this.map?.remove(); }

  donnees(): GeoJSON.FeatureCollection {
    const ouverts = new Set(this.activations.map(a => a.pei).filter(p => p !== null));
    const candidats = this.candidats.filter(c => !ouverts.has(c.id)).map(c => ({
      type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates: [c.longitude, c.latitude] },
      properties: { id: c.id, genre: 'candidat', nom: c.nom || c.type_libelle,
                    couleur: this.choix[c.id] ? this.couleurs['choisi'] : this.couleurs['candidat'] },
    }));
    const activations = this.activations.filter(a => a.statut !== 'ANNULE').map(a => ({
      type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates: [a.longitude, a.latitude] },
      properties: { genre: 'activation', nom: `${a.nom} — ${a.statut_libelle}`, couleur: this.couleurs[a.statut] ?? '#f59e0b' },
    }));
    return { type: 'FeatureCollection', features: [...candidats, ...activations] };
  }

  private cadrer(): void {
    if (this.cadree || !this.map) return;
    const points = [...this.candidats.slice(0, 40), ...this.activations];
    if (!points.length) return;
    this.cadree = true;
    if (points.length === 1) {
      this.map.jumpTo({ center: [points[0].longitude, points[0].latitude], zoom: 14 });
      return;
    }
    const bornes = new maplibregl.LngLatBounds();
    points.forEach(p => bornes.extend([p.longitude, p.latitude]));
    this.map.fitBounds(bornes, { padding: 30, maxZoom: 15, duration: 0 });
  }
}
