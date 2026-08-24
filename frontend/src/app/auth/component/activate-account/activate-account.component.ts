import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { AuthService } from '../../services/auth.service';

type ActivationState = 'loading' | 'success' | 'error';

@Component({
  selector: 'app-activate-account',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './activate-account.component.html',
  styleUrls: ['./activate-account.component.scss']
})
export class ActivateAccountComponent implements OnInit {
  state: ActivationState = 'loading';
  errorMessage = '';
  successMessage = '';
  returnUrl = '/accueil';

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private authService: AuthService
  ) {}

  ngOnInit(): void {
    const { uidb64, token } = this.route.snapshot.params;

    if (!uidb64 || !token) {
      this.state = 'error';
      this.errorMessage = "Lien d'activation incomplet.";
      return;
    }

    this.authService.activateAccount(uidb64, token).subscribe({
      next: (response) => {
        this.state = 'success';
        this.successMessage = response.message || 'Compte activé avec succès.';
      },
      error: (error) => {
        this.state = 'error';
        this.errorMessage = error.message || "Ce lien d'activation est invalide ou a expiré";
      }
    });
  }

  goToDashboard(): void {
    this.router.navigate([this.returnUrl]);
  }
}
