import { AfterViewInit, Component, ElementRef, EventEmitter, Input, OnChanges, OnDestroy, Output, SimpleChanges, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import maplibregl from 'maplibre-gl';
import { TerraDraw, TerraDrawPolygonMode, TerraDrawSelectMode } from 'terra-draw';
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter';
import type { Polygon } from 'geojson';

/**
 * Carte de dessin de zone (polygone), autonome et volontairement séparée du MapComponent
 * partagé (déjà volumineux et multi-usage crises/demandes/offres). Émet la zone dessinée
 * en WKT (`"POLYGON ((lng lat, ...))"`), directement consommable par l'API (champ `zone`
 * de Crisis), sans dépendance de parsing WKT côté frontend.
 */
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

  @Output() zoneChange = new EventEmitter<string | null>();

  hasZone = false;

  private map: maplibregl.Map | null = null;
  private draw: TerraDraw | null = null;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['center'] && this.map && !changes['center'].firstChange) {
      this.map.setCenter(this.center);
    }
  }

  ngAfterViewInit(): void {
    this.initMap();
  }

  private initMap(): void {
    this.map = new maplibregl.Map({
      container: this.mapContainer.nativeElement,
      style: 'https://raw.githubusercontent.com/go2garret/maps/main/src/assets/json/openStreetMap.json',
      center: this.center,
      zoom: this.zoom,
    });

    this.map.addControl(new maplibregl.NavigationControl(), 'top-right');

    this.map.on('load', () => {
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
