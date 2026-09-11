import { AfterViewInit, Component, ElementRef, Input, OnChanges, OnDestroy, SimpleChanges, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import maplibregl from 'maplibre-gl';
import type { Polygon } from 'geojson';

export interface MinimapPointInteret {
  latitude: number;
  longitude: number;
  label: string;
}

const ZONE_SOURCE_ID = 'minimap-zone';

/**
 * Petite carte de localisation en lecture seule : un point + éventuellement une flèche
 * de direction (azimut EXIF capturé au moment de la photo). Volontairement séparée du
 * MapComponent partagé (clustering multi-source) et de ZoneMapComponent (dessin de
 * polygone) — ici on ne fait qu'afficher un point fixe pour donner du contexte spatial à
 * un signalement, ex: dans la visionneuse plein écran d'une photo.
 *
 * `pointsInteret` (optionnel) ajoute des repères secondaires (points opérationnels de la
 * crise pertinents pour l'intervenant : transit, regroupement, accueil, secours...) — la
 * carte se recentre alors pour tous les englober plutôt que sur le seul point principal.
 */
@Component({
  selector: 'app-minimap',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './minimap.component.html',
  styleUrls: ['./minimap.component.scss']
})
export class MinimapComponent implements AfterViewInit, OnChanges, OnDestroy {
  @ViewChild('mapContainer', { static: true }) mapContainer!: ElementRef<HTMLDivElement>;

  @Input({ required: true }) latitude!: number;
  @Input({ required: true }) longitude!: number;
  /** Azimut EXIF (0 = Nord, sens horaire), si capturé avec la photo. */
  @Input() azimuth: number | null = null;
  @Input() zoom = 15;
  @Input() pointsInteret: MinimapPointInteret[] = [];
  /** Contour précis (ex: Crisis.zone_geojson) — affiché en plus du point principal, la carte
   * s'ajuste alors pour englober tout le polygone plutôt que de rester au zoom fixe. */
  @Input() zoneGeojson: Polygon | null = null;

  private map: maplibregl.Map | null = null;
  private pointMarker: maplibregl.Marker | null = null;
  private arrowMarker: maplibregl.Marker | null = null;
  private poiMarkers: maplibregl.Marker[] = [];
  private resizeObserver: ResizeObserver | null = null;

  ngAfterViewInit(): void {
    this.initMap();
    this.observeContainerResize();
  }

  /** Même correctif que MapComponent.observeContainerResize : MapLibre ne calcule la taille
   * du canvas qu'une fois, à l'instant de la construction — si le conteneur n'a pas encore sa
   * taille finale à ce moment (ex: une minimap dans une modale dont la mise en page n'est pas
   * encore stabilisée), fitBounds/fitToZone se base sur un viewport erroné et la carte ne
   * cadre pas correctement sur la zone. On réaligne le canvas ET on refait le cadrage une fois
   * la taille réelle connue, pas juste resize() seul (qui ne corrigerait pas un fitBounds déjà
   * calculé avec de mauvaises dimensions). */
  private observeContainerResize(): void {
    if (typeof ResizeObserver === 'undefined') return;
    this.resizeObserver = new ResizeObserver(() => {
      if (!this.map) return;
      this.map.resize();
      if (this.zoneGeojson) {
        this.fitToZone(this.zoneGeojson);
      } else if (this.pointsInteret.length > 0) {
        this.fitToPoints();
      }
    });
    this.resizeObserver.observe(this.mapContainer.nativeElement);
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (!this.map) return;
    if (changes['latitude'] || changes['longitude']) {
      this.pointMarker?.setLngLat([this.longitude, this.latitude]);
      this.arrowMarker?.setLngLat([this.longitude, this.latitude]);
      if (this.zoneGeojson) {
        this.fitToZone(this.zoneGeojson);
      } else if (this.pointsInteret.length > 0) {
        this.fitToPoints();
      } else {
        this.map.setCenter([this.longitude, this.latitude]);
      }
    }
    if (changes['azimuth']) {
      this.syncArrowMarker();
    }
    if (changes['pointsInteret']) {
      this.syncPoiMarkers();
      this.fitToPoints();
    }
    if (changes['zoneGeojson']) {
      this.runWhenMapReady(() => this.syncZonePolygon());
    }
  }

  private initMap(): void {
    this.map = new maplibregl.Map({
      container: this.mapContainer.nativeElement,
      style: 'https://raw.githubusercontent.com/go2garret/maps/main/src/assets/json/openStreetMap.json',
      center: [this.longitude, this.latitude],
      zoom: this.zoom,
      attributionControl: false,
    });
    this.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');

    this.pointMarker = new maplibregl.Marker({ color: '#dc2626' })
      .setLngLat([this.longitude, this.latitude])
      .addTo(this.map);

    this.syncArrowMarker();
    this.syncPoiMarkers();
    if (this.zoneGeojson) {
      this.runWhenMapReady(() => this.syncZonePolygon());
    } else {
      this.fitToPoints();
    }
  }

  /** MapLibre ne rejoue jamais l'événement 'load' pour un listener attaché après coup — voir
   * MapComponent.runWhenMapReady, même correctif ici : addSource/addLayer exigent le style
   * chargé, contrairement aux Marker (point/flèche), ajoutables immédiatement. */
  private runWhenMapReady(cb: () => void): void {
    if (!this.map) return;
    if (this.map.isStyleLoaded()) {
      cb();
    } else {
      this.map.once('load', cb);
    }
  }

  private syncZonePolygon(): void {
    if (!this.map) return;
    const source = this.map.getSource(ZONE_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    const data: GeoJSON.Feature<Polygon> | GeoJSON.FeatureCollection = this.zoneGeojson
      ? { type: 'Feature', properties: {}, geometry: this.zoneGeojson }
      : { type: 'FeatureCollection', features: [] };

    if (source) {
      source.setData(data as any);
    } else if (this.zoneGeojson) {
      this.map.addSource(ZONE_SOURCE_ID, { type: 'geojson', data: data as any });
      this.map.addLayer({
        id: `${ZONE_SOURCE_ID}-fill`, type: 'fill', source: ZONE_SOURCE_ID,
        paint: { 'fill-color': '#dc2626', 'fill-opacity': 0.15 },
      });
      this.map.addLayer({
        id: `${ZONE_SOURCE_ID}-outline`, type: 'line', source: ZONE_SOURCE_ID,
        paint: { 'line-color': '#dc2626', 'line-width': 2 },
      });
    }

    if (this.zoneGeojson) this.fitToZone(this.zoneGeojson);
  }

  private fitToZone(polygon: Polygon): void {
    if (!this.map) return;
    const coords = polygon.coordinates[0];
    if (!coords || coords.length === 0) return;
    const bounds = coords.reduce(
      (b, [lng, lat]) => b.extend([lng, lat] as [number, number]),
      new maplibregl.LngLatBounds(coords[0] as [number, number], coords[0] as [number, number])
    );
    this.map.fitBounds(bounds, { padding: 30, maxZoom: this.zoom });
  }

  /** Sans point d'intérêt, comportement inchangé (centré sur le point principal au zoom
   * demandé) — avec, la carte s'ajuste pour tous les englober, en respectant `zoom` comme
   * niveau MAXIMUM (pas la peine de trop s'approcher si les points sont proches). */
  private fitToPoints(): void {
    if (!this.map || this.pointsInteret.length === 0) return;
    const bounds = new maplibregl.LngLatBounds([this.longitude, this.latitude], [this.longitude, this.latitude]);
    this.pointsInteret.forEach(p => bounds.extend([p.longitude, p.latitude]));
    this.map.fitBounds(bounds, { padding: 40, maxZoom: this.zoom, animate: false });
  }

  private syncPoiMarkers(): void {
    this.poiMarkers.forEach(m => m.remove());
    this.poiMarkers = [];
    if (!this.map) return;

    this.pointsInteret.forEach(p => {
      const marker = new maplibregl.Marker({ color: '#2563eb' })
        .setLngLat([p.longitude, p.latitude])
        .setPopup(new maplibregl.Popup({ offset: 12 }).setText(p.label))
        .addTo(this.map!);
      this.poiMarkers.push(marker);
    });
  }

  /** Même convention visuelle que MapComponent.addDirectionArrowLayer : flèche verte,
   * icon-rotate direct sur la valeur d'azimut (0 = Nord, sens horaire, pas de conversion). */
  private syncArrowMarker(): void {
    this.arrowMarker?.remove();
    this.arrowMarker = null;
    if (this.azimuth == null || !this.map) return;

    const el = document.createElement('div');
    el.className = 'minimap-direction-arrow';
    el.style.transform = `rotate(${this.azimuth}deg)`;
    el.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24">' +
      '<path d="M12 2 L18 20 L12 16 L6 20 Z" fill="#1b5e20" stroke="white" stroke-width="1"/>' +
      '</svg>';

    this.arrowMarker = new maplibregl.Marker({ element: el, rotationAlignment: 'map' })
      .setLngLat([this.longitude, this.latitude])
      .addTo(this.map);
  }

  ngOnDestroy(): void {
    this.resizeObserver?.disconnect();
    this.pointMarker?.remove();
    this.arrowMarker?.remove();
    this.poiMarkers.forEach(m => m.remove());
    this.map?.remove();
  }
}
