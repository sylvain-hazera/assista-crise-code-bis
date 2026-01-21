import { Component, OnInit } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { GeolocationPopupComponent } from "./shared/components/geolocation-popup/geolocation-popup.component";
import { GeolocationService } from './shared/service/geolocation.service';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-root',
  imports: [
    RouterOutlet, 
    GeolocationPopupComponent, 
    CommonModule
  ],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss'
})
export class AppComponent implements OnInit{
  title = 'assista-crise-front';
  showGeolocationPopup = false;

  constructor(private geolocationService: GeolocationService) {}

  ngOnInit(): void {
    // Afficher le popup si la permission n'est pas déjà accordée
    setTimeout(() => {
      if (!this.geolocationService.hasPermission()) {
        this.showGeolocationPopup = true;
      }
    }, 0);
  }

  closePopup(): void {
    this.showGeolocationPopup = false;
  }

  showPopup(): void {
    this.showGeolocationPopup = true;
  }
}
