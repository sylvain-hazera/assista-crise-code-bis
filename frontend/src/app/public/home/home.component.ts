import { Component, OnInit } from '@angular/core';
import { MapComponent } from "../../shared/components/common/map/map.component";
import { FormsModule } from '@angular/forms';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { AuthService } from '../../auth/services/auth.service';

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
export class HomeComponent implements OnInit {
  searchQuery = '';
  canDeclareCrisis = false;

  constructor(
    private router: Router,
    private authService: AuthService
  ) {}

  ngOnInit(): void {
    this.authService.currentUser$.subscribe(user => {
      if (user) {
        const allowedRoles = ['ADMIN', 'AUT_LOCALE', 'SECOURS'];
        // Le backend envoie 'type' pas 'userType'
        const userRole = (user as any).type || user.userType;
        this.canDeclareCrisis = allowedRoles.includes(userRole as string);
        console.log('User role:', userRole, 'Can declare crisis:', this.canDeclareCrisis);
      } else {
        this.canDeclareCrisis = false;
      }
    });
  }

  onSearch(): void {
    console.log('Recherche:', this.searchQuery);
    // Implémenter la logique de recherche
  }

  navigateTo(route: string): void {
    console.log('Navigation vers :', route);
    this.router.navigate([route]);
  }

}