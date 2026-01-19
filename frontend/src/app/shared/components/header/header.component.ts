import { Component } from '@angular/core';
import { Router, RouterModule } from '@angular/router';
import { AuthService } from '../../../auth/auth.service';

@Component({
  selector: 'app-header',
  imports: [
    RouterModule
  ],
  templateUrl: './header.component.html',
  styleUrl: './header.component.scss'
})
export class HeaderComponent {
  constructor(public authService: AuthService, private router: Router) {}

  get userName(): string | null {
    return this.authService.userName;
  }

  get isAdmin(): boolean {
    return this.authService.isAdmin;
  }

  handleUserAction() {
    if (this.authService.isConnected) {
      if(this.authService.isAdmin) {
        this.router.navigate(['/admin/dashboard']);
      } else {
        this.router.navigate(['/account', this.userName]);
      }
    } else {
      this.router.navigate(['/login']);
    }
  }
}
