import { Component, OnInit } from '@angular/core';
import { GeolocationService } from '../../shared/service/geolocation.service';
import { MapComponent } from "../../shared/components/map/map.component";
import { FormsModule } from '@angular/forms';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';

@Component({
  selector: 'app-home',
  templateUrl: './home.component.html',
  styleUrls: ['./home.component.scss'],
  imports: [
    CommonModule,
    FormsModule,
    MapComponent,
  ],
  providers: [
    GeolocationService
  ]
})
export class HomeComponent  {
  constructor(private geolocationService: GeolocationService, private router: Router){}

  searchQuery = '';

  onSearch(): void {
    console.log('Recherche:', this.searchQuery);
    // Implémenter la logique de recherche
  }

  navigateTo(route: string): void {
    console.log('Navigation vers :', route);
    this.router.navigate([route]);
  }

}