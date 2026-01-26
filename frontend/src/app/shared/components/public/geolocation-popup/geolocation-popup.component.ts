import { Component, EventEmitter, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { GeolocationService } from '../../../../services/geolocation.service';

@Component({
  selector: 'app-geolocation-popup',
  templateUrl: './geolocation-popup.component.html',
  styleUrls: ['./geolocation-popup.component.scss'],
  imports: [
    CommonModule, 
    // FormsModule
  ],
})

export class GeolocationPopupComponent {
  @Output() close = new EventEmitter<void>();
  
  loading = false;
  error: string | null = null;

  constructor(private geolocationService: GeolocationService) {}

  async allowGeolocation(): Promise<void> {
    this.loading = true;
    this.error = null;

    try {
      await this.geolocationService.requestLocation();
      this.close.emit();
    } catch (err: any) {
      this.error = err.message;
    } finally {
      this.loading = false;
    }
  }

  denyGeolocation(): void {
    this.close.emit();
  }
}