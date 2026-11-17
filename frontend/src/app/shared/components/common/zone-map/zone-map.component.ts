import { AfterViewInit, Component, ElementRef, EventEmitter, Input, OnChanges, OnDestroy, Output, SimpleChanges, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { styleCarte } from '../../../utils/carte-style';
import maplibregl from 'maplibre-gl';
import { TerraDraw, TerraDrawPolygonMode, TerraDrawSelectMode } from 'terra-draw';
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter';
import type { FeatureCollection, MultiPolygon, Polygon, Position } from 'geojson';

import { aimanter, segmentsDe } from '../../../utils/aimantation.util';

const COMMUNES_SOURCE_ID = 'zone-map-communes';
const REPERES_SOURCE_ID = 'zone-map-reperes';

/** Carte de dessin de zone (polygone), séparée de MapComponent. Émet du WKT
 * (`"POLYGON ((lng lat, ...))"`) consommable directement par l'API. */
@Component({
  selector: 'app-zone-map',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './zone-map.component.html',
  styleUrls: ['./zone-map.component.scss']
})
export class ZoneMapComponent implements AfterViewInit, OnChanges, OnDestroy {
  @ViewChild('mapContainer', { static: true }) mapContainer!: ElementRef<HTMLDivElement>;

  @Input() center: [number, number] = [2.2137, 46.2276]; // France, par défaut
  @Input() zoom = 11;
  @Input() initialZone: Polygon | null = null;
  /** Contours des communes (calque de référence sous l'outil de dessin). */
  @Input() communesGeojson: FeatureCollection<Polygon | MultiPolygon> | null = null;
  /** Géométrie sur laquelle CADRER la carte (ajustement aux limites, pas un simple centrage).
   *
   * `[center]`/`[zoom]` ne suffisent pas : un niveau de zoom fixe cadre mal une commune, qui
   * peut faire deux kilomètres comme quarante. On ajuste donc aux limites réelles. */
  @Input() cadrerSur: Polygon | MultiPolygon | null = null;

  /** Zones déjà en place (zone initiale, secteurs, zones ajoutées par d'autres) : affichées
   * sous le tracé, non modifiables, et le tracé s'y aimante. C'est ce qui permet de dessiner
   * une zone EN PLUS, bord à bord avec l'existant, sans trou ni recouvrement. */
  @Input() reperes: (Polygon | MultiPolygon)[] = [];
  /** Aimantation sur les contours existants (repères et communes). Débrayable : on veut
   * parfois passer volontairement près d'un contour sans s'y coller. */
  aimantation = true;

  @Output() zoneChange = new EventEmitter<string | null>();

  hasZone = false;

  private map: maplibregl.Map | null = null;
  private draw: TerraDraw | null = null;

  ngOnChanges(changes: SimpleChanges): void {
    // this.map est null au premier ngOnChanges (avant ngAfterViewInit) : appel ignoré.
    // flyTo pour recentrer et zoomer.
    if (!this.map) return;
    if (changes['center'] || changes['zoom']) {
      this.map.flyTo({ center: this.center, zoom: this.zoom });
    }
    if (changes['communesGeojson']) {
      this.syncCommunesLayer();
    }
    if (changes['cadrerSur'] && this.cadrerSur) {
      this.cadrer(this.cadrerSur);
    }
    if (changes['reperes']) {
      this.syncReperesLayer();
    }
    if (changes['reperes'] || changes['communesGeojson']) {
      this.segmentsAimants = null;
    }
  }

  /** Segments de tous les contours aimantés, calculés à la demande puis gardés : la fonction
   * d'aimantation est appelée à chaque mouvement de souris. */
  private segmentsAimants: [Position, Position][] | null = null;

  private aimanterSurLExistant(lng: number, lat: number): Position | undefined {
    if (!this.aimantation || !this.map) return undefined;
    if (this.segmentsAimants === null) {
      const communes = (this.communesGeojson?.features ?? []).map(f => f.geometry);
      this.segmentsAimants = segmentsDe([...this.reperes, ...communes]);
    }
    if (!this.segmentsAimants.length) return undefined;
    const carte = this.map;
    return aimanter(lng, lat, this.segmentsAimants, (x, y) => carte.project([x, y]));
  }

  /** Les zones existantes, en calque de référence d'une couleur distincte du tracé. */
  private syncReperesLayer(): void {
    if (!this.map || !this.map.isStyleLoaded()) return;
    const data: FeatureCollection = {
      type: 'FeatureCollection',
      features: this.reperes.map(geometry => ({ type: 'Feature', properties: {}, geometry })),
    };
    const source = this.map.getSource(REPERES_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(data as any);
      return;
    }
    if (!this.reperes.length) return;
    this.map.addSource(REPERES_SOURCE_ID, { type: 'geojson', data: data as any });
    this.map.addLayer({
      id: `${REPERES_SOURCE_ID}-fill`, type: 'fill', source: REPERES_SOURCE_ID,
      paint: { 'fill-color': '#b45309', 'fill-opacity': 0.12 },
    });
    this.map.addLayer({
      id: `${REPERES_SOURCE_ID}-outline`, type: 'line', source: REPERES_SOURCE_ID,
      paint: { 'line-color': '#b45309', 'line-width': 2, 'line-dasharray': [2, 1] },
    });
  }

  /** Ajuste la vue aux limites d'une géométrie. Gère le MultiPolygon : une commune insulaire ou
   * discontinue en est un, et ne lire que `coordinates[0]` cadrerait sur un seul morceau. */
  private cadrer(geometrie: Polygon | MultiPolygon): void {
    if (!this.map) return;
    const anneaux: number[][][] = geometrie.type === 'Polygon'
      ? geometrie.coordinates
      : geometrie.coordinates.flat();
    const points = anneaux.flat();
    if (!points.length) return;
    const bounds = points.reduce(
      (b, [lng, lat]) => b.extend([lng, lat] as [number, number]),
      new maplibregl.LngLatBounds(points[0] as [number, number], points[0] as [number, number]),
    );
    this.map.fitBounds(bounds, { padding: 40, maxZoom: 14 });
  }

  ngAfterViewInit(): void {
    this.initMap();
  }

  /** Vrai quand le navigateur n'a pas pu fournir de contexte WebGL (voir MapComponent, même
   * garde et même raison). */
  carteIndisponible = false;

  private initMap(): void {
    // Même garde que MapComponent : sans WebGL, le constructeur de MapLibre lève et
    // l'exception traverse ngAfterViewInit — c'est le FORMULAIRE entier de déclaration de
    // crise qui ne s'affiche plus, alors que seule la sélection de zone a besoin de la carte.
    try {
      this.map = new maplibregl.Map({
        container: this.mapContainer.nativeElement,
        style: styleCarte(),
        center: this.center,
        zoom: this.zoom,
      });
    } catch (erreur) {
      console.warn('Sélection de zone indisponible : contexte WebGL impossible.', erreur);
      // Au tour suivant : on est dans ngAfterViewInit, l'écrire tout de suite déclenche NG0100.
      Promise.resolve().then(() => this.carteIndisponible = true);
      return;
    }

    this.map.addControl(new maplibregl.NavigationControl(), 'top-right');

    this.map.on('load', () => {
      // Calque de référence ajouté avant TerraDraw : reste dessous, sans capter les clics.
      this.syncCommunesLayer();
      this.syncReperesLayer();
      if (this.reperes.length && !this.initialZone && !this.cadrerSur) {
        this.cadrer({ type: 'MultiPolygon', coordinates: this.reperes.flatMap(
          g => g.type === 'Polygon' ? [g.coordinates] : g.coordinates) });
      }

      this.draw = new TerraDraw({
        adapter: new TerraDrawMapLibreGLAdapter({ map: this.map as any }),
        modes: [
          new TerraDrawPolygonMode({
            // « Magnétisme » : le point en cours se colle au sommet ou au bord le plus proche
            // d'un contour existant. `toCustom` et non `toLine`/`toCoordinate`, qui ne
            // connaissent que les formes dessinées dans l'outil lui-même.
            snapping: { toCustom: (event) => this.aimanterSurLExistant(event.lng, event.lat) },
          }),
          new TerraDrawSelectMode(),
        ],
      });
      this.draw.start();

      this.draw.on('finish', (id: string | number) => {
        // Une seule zone à la fois : on retire tout polygone précédemment dessiné.
        const snapshot = this.draw!.getSnapshot();
        const others = snapshot.filter(f => f.id !== id).map(f => f.id as string | number);
        if (others.length) {
          this.draw!.removeFeatures(others);
        }

        const feature = snapshot.find(f => f.id === id);
        if (feature && feature.geometry.type === 'Polygon') {
          this.hasZone = true;
          this.zoneChange.emit(this.polygonToWkt(feature.geometry as Polygon));
        }
      });

      if (this.initialZone) {
        this.loadInitialZone(this.initialZone);
      }
    });
  }

  /** Contours communaux en calque transparent, d'une couleur distincte du polygone dessiné.
   * Sans effet tant que la carte n'est pas chargée. */
  private syncCommunesLayer(): void {
    if (!this.map || !this.map.isStyleLoaded()) return;
    const data: FeatureCollection = this.communesGeojson ?? { type: 'FeatureCollection', features: [] };

    const source = this.map.getSource(COMMUNES_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(data as any);
      return;
    }
    if (!this.communesGeojson) return;
    this.map.addSource(COMMUNES_SOURCE_ID, { type: 'geojson', data: data as any });
    this.map.addLayer({
      id: `${COMMUNES_SOURCE_ID}-fill`, type: 'fill', source: COMMUNES_SOURCE_ID,
      paint: { 'fill-color': '#2563eb', 'fill-opacity': 0.15 },
    });
    this.map.addLayer({
      id: `${COMMUNES_SOURCE_ID}-outline`, type: 'line', source: COMMUNES_SOURCE_ID,
      paint: { 'line-color': '#2563eb', 'line-width': 1.5 },
    });
  }

  private loadInitialZone(polygon: Polygon): void {
    if (!this.draw) return;
    this.draw.addFeatures([{
      type: 'Feature',
      properties: { mode: 'polygon' },
      geometry: polygon,
    } as any]);
    this.hasZone = true;

    const coords = polygon.coordinates[0];
    const bounds = coords.reduce(
      (b, [lng, lat]) => b.extend([lng, lat]),
      new maplibregl.LngLatBounds(coords[0] as [number, number], coords[0] as [number, number])
    );
    this.map?.fitBounds(bounds, { padding: 40 });
  }

  startDrawing(): void {
    this.draw?.setMode('polygon');
  }

  clearZone(): void {
    this.draw?.clear();
    this.hasZone = false;
    this.zoneChange.emit(null);
  }

  private polygonToWkt(polygon: Polygon): string {
    const rings = polygon.coordinates
      .map(ring => `(${ring.map(([lng, lat]) => `${lng} ${lat}`).join(', ')})`)
      .join(', ');
    return `POLYGON (${rings})`;
  }

  ngOnDestroy(): void {
    this.draw?.stop();
    this.map?.remove();
  }
}
