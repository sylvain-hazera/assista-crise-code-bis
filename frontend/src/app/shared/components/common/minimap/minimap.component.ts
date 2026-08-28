import { AfterViewInit, Component, ElementRef, Input, OnChanges, OnDestroy, SimpleChanges, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import maplibregl from 'maplibre-gl';

/**
 * Petite carte de localisation en lecture seule : un point + éventuellement une flèche
 * de direction (azimut EXIF capturé au moment de la photo). Volontairement séparée du
 * MapComponent partagé (clustering multi-source) et de ZoneMapComponent (dessin de
 * polygone) — ici on ne fait qu'afficher un point fixe pour donner du contexte spatial à
 * un signalement, ex: dans la visionneuse plein écran d'une photo.
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

  private map: maplibregl.Map | null = null;
  private pointMarker: maplibregl.Marker | null = null;
  private arrowMarker: maplibregl.Marker | null = null;

  ngAfterViewInit(): void {
    this.initMap();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (!this.map) return;
    if (changes['latitude'] || changes['longitude']) {
      this.map.setCenter([this.longitude, this.latitude]);
      this.pointMarker?.setLngLat([this.longitude, this.latitude]);
      this.arrowMarker?.setLngLat([this.longitude, this.latitude]);
    }
    if (changes['azimuth']) {
      this.syncArrowMarker();
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
    this.pointMarker?.remove();
    this.arrowMarker?.remove();
    this.map?.remove();
  }
}
