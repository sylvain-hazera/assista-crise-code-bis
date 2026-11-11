import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';

import { AuthService } from '../../auth/services/auth.service';
import {
  VerdictMobilisation, VerificationMobilisationService,
} from '../../services/verification-mobilisation.service';
import { VerdictMobilisationComponent } from '../../shared/components/common/verdict-mobilisation/verdict-mobilisation.component';

/**
 * Page ouverte par le QR code d'une attestation de mobilisation.
 *
 * C'est **le chemin de l'iPhone** (demande de Sylvain du 11/11/2026) : l'appareil photo natif
 * lit l'URL imprimée dans le QR, ouvre cette page, et l'application réutilise la session déjà
 * en place — sans rien installer, sans décodeur JavaScript, et sur n'importe quel téléphone.
 * Le scanner intégré reste utile quand on contrôle plusieurs personnes à la suite.
 *
 * **La route n'est pas gardée, et c'est voulu.** Un garde d'authentification renverrait un
 * contrôleur extérieur vers une page de connexion qu'il ne peut pas franchir, alors que le
 * serveur sait très bien lui répondre : il rend l'authenticité et le statut, sans le nom du
 * destinataire ni le lieu. C'est le serveur qui décide du niveau de détail, pas la route — et
 * c'est le bon endroit pour en décider, parce qu'une garde côté navigateur ne protège rien.
 *
 * Qui n'est pas connecté se voit proposer de l'être, avec retour sur cette même page : c'est
 * un geste, pas une impasse.
 */
@Component({
  selector: 'app-verification-mobilisation',
  standalone: true,
  imports: [CommonModule, VerdictMobilisationComponent],
  templateUrl: './verification-mobilisation.component.html',
  styleUrl: './verification-mobilisation.component.scss',
})
export class VerificationMobilisationComponent implements OnInit {

  chargement = true;
  erreur = '';
  verdict: VerdictMobilisation | null = null;
  connecte = false;

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private service: VerificationMobilisationService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    this.connecte = !!this.authService.getToken();
    const jeton = this.route.snapshot.paramMap.get('jeton');
    if (!jeton) {
      this.chargement = false;
      this.erreur = "Ce lien de vérification est incomplet.";
      return;
    }
    this.service.verifier(jeton).subscribe({
      next: (verdict) => {
        this.verdict = verdict;
        this.chargement = false;
      },
      error: () => {
        this.chargement = false;
        // Distinct d'une attestation invalide, et la nuance décide d'une conduite à tenir :
        // « révoquée » veut dire non ; « je n'ai pas pu joindre le serveur » ne veut rien
        // dire du tout.
        this.erreur = 'Vérification impossible : le serveur est injoignable. '
          + 'Ne concluez rien de cet échec.';
      },
    });
  }

  /** Se connecter puis revenir ICI, sur le même verdict. */
  seConnecter(): void {
    this.router.navigate(['/login'], {
      queryParams: { returnUrl: this.router.url },
    });
  }
}
