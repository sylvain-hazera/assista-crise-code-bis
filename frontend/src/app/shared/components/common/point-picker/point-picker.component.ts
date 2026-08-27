import { AfterViewInit, Component, ElementRef, EventEmitter, Input, OnChanges, OnDestroy, Output, SimpleChanges, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import maplibregl from 'maplibre-gl';

/**
 * Carte minimale pour placer/ajuster un point GPS unique (marker draggable) — volontairement
 * distincte de <app-zone-map> (TerraDraw, dessin de polygone) : responsabilité différente,
 * pas besoin de tout son appareillage de dessin pour un simple point. Utilisée en complément
 * de <app-address-picker> : l'adresse résout une position de départ, ce composant permet un
 * ajustement fin optionnel du marker avant sauvegarde.
 */
@Component({
  selector: 'app-point-picker',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './point-picker.component.html',
  styleUrls: ['./point-picker.component.scss']
})
export class PointPickerComponent implements AfterViewInit, OnChanges, OnDestroy {
  @ViewChild('mapContainer', { static: true }) mapContainer!: ElementRef<HTMLDivElement>;

  @Input() latitude: number | null = null;
  @Input() longitude: number | null = null;
  @Input() zoom = 14;

  @Output() positionChange = new EventEmitter<{ latitude: number; longitude: number }>();

  private map: maplibregl.Map | null = null;
  private marker: maplibregl.Marker | null = null;

  ngOnChanges(changes: SimpleChanges): void {
    if ((changes['latitude'] || changes['longitude']) && this.map && this.latitude != null && this.longitude != null) {
      this.setMarkerPosition(this.longitude, this.latitude, !changes['latitude']?.firstChange);
    }
  }

  ngAfterViewInit(): void {
    const center: [number, number] = this.longitude != null && this.latitude != null
      ? [this.longitude, this.latitude]
      : [2.2137, 46.2276]; // France, par défaut si aucune position de départ

    this.map = new maplibregl.Map({
      container: this.mapContainer.nativeElement,
      style: 'https://raw.githubusercontent.com/go2garret/maps/main/src/assets/json/openStreetMap.json',
      center,
      zoom: this.zoom,
    });

    this.map.addControl(new maplibregl.NavigationControl(), 'top-right');

    if (this.longitude != null && this.latitude != null) {
      this.setMarkerPosition(this.longitude, this.latitude, false);
    }

    // Un clic sur la carte replace directement le marker (plus rapide qu'un drag précis).
    this.map.on('click', (e) => {
      this.setMarkerPosition(e.lngLat.lng, e.lngLat.lat, false);
      this.positionChange.emit({ latitude: e.lngLat.lat, longitude: e.lngLat.lng });
    });
  }

  private setMarkerPosition(lng: number, lat: number, recenter: boolean): void {
    if (!this.map) return;
    if (!this.marker) {
      this.marker = new maplibregl.Marker({ draggable: true })
        .setLngLat([lng, lat])
        .addTo(this.map);
      this.marker.on('dragend', () => {
        const pos = this.marker!.getLngLat();
        this.positionChange.emit({ latitude: pos.lat, longitude: pos.lng });
      });
    } else {
      this.marker.setLngLat([lng, lat]);
    }
    if (recenter) {
      this.map.setCenter([lng, lat]);
    }
  }

  ngOnDestroy(): void {
    this.marker?.remove();
    this.map?.remove();
  }
}
