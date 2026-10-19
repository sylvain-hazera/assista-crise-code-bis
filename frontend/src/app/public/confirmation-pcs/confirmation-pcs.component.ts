import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { AccuserReceptionPCSService, AccuseReceptionPCS } from '../../services/accuser-reception-pcs.service';
import { ReponseContactPCS } from '../../shared/models/notification-alerte-pcs.model';

/** Accusé de réception public d'une alerte PCS/PICS (lien du mail,
 * core.alertes_pcs._lien_accuse_reception) : évite un appel de relance. */
@Component({
  selector: 'app-confirmation-pcs',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './confirmation-pcs.component.html',
  styleUrl: './confirmation-pcs.component.scss',
})
export class ConfirmationPcsComponent implements OnInit {

  accuse: AccuseReceptionPCS | null = null;
  loading = true;
  notFound = false;
  submitting = false;
  errorMessage = '';

  commentaire = '';

  private token = '';

  constructor(
    private route: ActivatedRoute,
    private service: AccuserReceptionPCSService,
  ) {}

  ngOnInit(): void {
    this.token = this.route.snapshot.paramMap.get('token') || '';
    this.charger();
  }

  private charger(): void {
    this.loading = true;
    this.service.getByToken(this.token).subscribe({
      next: (accuse) => { this.accuse = accuse; this.loading = false; },
      error: () => { this.notFound = true; this.loading = false; },
    });
  }

  repondre(reponse: ReponseContactPCS): void {
    if (this.submitting) return;
    this.submitting = true;
    this.errorMessage = '';
    this.service.repondre(this.token, reponse, this.commentaire.trim()).subscribe({
      next: (accuse) => { this.accuse = accuse; this.submitting = false; },
      error: (err) => {
        this.errorMessage = err?.error?.detail || "Impossible d'enregistrer votre réponse.";
        this.submitting = false;
      },
    });
  }
}
