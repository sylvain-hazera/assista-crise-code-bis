import { Component } from '@angular/core';
import { Router, RouterModule } from '@angular/router';
import { AuthService } from '../../../../auth/services/auth.service';
import { User } from '../../../models/user.model';

@Component({
  selector: 'app-header',
  imports: [
    RouterModule
  ],
  templateUrl: './header.component.html',
  styleUrl: './header.component.scss'
})
export class HeaderComponent {
  private connectedUser: User | null = null;
  constructor(public authService: AuthService, private router: Router) {
    this.authService.currentUser$.subscribe(user => {
      this.connectedUser = user;
    });
  }

  get userName(): string | null {
    return this.connectedUser? this.connectedUser['pseudo'] || this.connectedUser['firstName'] || null : null;
  }

  get isAdmin(): boolean {
    return this.connectedUser ? this.connectedUser['userType'] !== 'individual' : true;
  }

  handleUserAction() {
    if (this.authService.isLoggedIn()) {
      if(this.isAdmin) {
        this.router.navigate(['/admin/dashboard']);
      } else {
        this.router.navigate(['/account', this.userName]);
      }
    } else {
      this.router.navigate(['/login']);
    }
  }
}
