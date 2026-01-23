import { Component, OnInit } from '@angular/core';
import { RouterOutlet } from "@angular/router";
import { FooterComponent } from "../../shared/components/public/footer/footer.component";
import { HeaderComponent } from '../../shared/components/public/header/header.component';
import { GeolocationPopupComponent } from '../../shared/components/public/geolocation-popup/geolocation-popup.component';
import { GeolocationService } from '../../services/geolocation.service';

@Component({
  selector: 'app-public-layout',
  imports: [
    HeaderComponent, 
    GeolocationPopupComponent,
    RouterOutlet, 
    FooterComponent
  ],
  templateUrl: './public-layout.component.html',
  styleUrl: './public-layout.component.scss'
})
export class PublicLayoutComponent implements OnInit {
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
