import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { AuthService } from '../../services/auth.service';

type MagicLoginState = 'loading' | 'success' | 'error';

@Component({
  selector: 'app-magic-login',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './magic-login.component.html',
  styleUrls: ['./magic-login.component.scss']
})
export class MagicLoginComponent implements OnInit {
  state: MagicLoginState = 'loading';
  errorMessage = '';

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private authService: AuthService
  ) {}

  ngOnInit(): void {
    const { uidb64, token } = this.route.snapshot.params;

    if (!uidb64 || !token) {
      this.state = 'error';
      this.errorMessage = 'Lien de connexion incomplet.';
      return;
    }

    this.authService.magicLogin(uidb64, token).subscribe({
      next: () => {
        this.state = 'success';
        const next = this.route.snapshot.queryParamMap.get('next') || '/accueil';
        this.router.navigateByUrl(next);
      },
      error: (error) => {
        this.state = 'error';
        this.errorMessage = error.message || 'Ce lien de connexion est invalide ou a expiré';
      }
    });
  }
}
