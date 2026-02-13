import { Component } from '@angular/core';
import { MapComponent } from "../../shared/components/common/map/map.component";
import { FormsModule } from '@angular/forms';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';

@Component({
  selector: 'app-home',
  standalone: true,
  templateUrl: './home.component.html',
  styleUrls: ['./home.component.scss'],
  imports: [
    CommonModule,
    FormsModule,
    MapComponent,
  ],
  providers: [
  ]
})
export class HomeComponent  {
  constructor(private router: Router){}

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