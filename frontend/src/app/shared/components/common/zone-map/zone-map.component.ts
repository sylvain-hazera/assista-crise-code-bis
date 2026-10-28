import { AfterViewInit, Component, ElementRef, EventEmitter, Input, OnChanges, OnDestroy, Output, SimpleChanges, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { styleCarte } from '../../../utils/carte-style';
import maplibregl from 'maplibre-gl';
import { TerraDraw, TerraDrawPolygonMode, TerraDrawSelectMode } from 'terra-draw';
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter';
import type { FeatureCollection, MultiPolygon, Polygon } from 'geojson';

const COMMUNES_SOURCE_ID = 'zone-map-communes';

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

      this.draw = new TerraDraw({
        adapter: new TerraDrawMapLibreGLAdapter({ map: this.map as any }),
        modes: [new TerraDrawPolygonMode(), new TerraDrawSelectMode()],
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
