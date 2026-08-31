import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';

import { EngagementRessourceService, EngagementRessourceStatut } from '../../services/engagement-ressource.service';

const ACTION_LABELS: Record<string, string> = {
  confirmer: 'Je confirme ma venue',
  decliner: 'Je ne suis pas disponible',
  transit: 'Je suis en route',
  arrivee: 'Je suis arrivé(e)',
};

@Component({
  selector: 'app-engagement-ressource',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './engagement-ressource.component.html',
  styleUrl: './engagement-ressource.component.scss',
})
export class EngagementRessourceComponent implements OnInit {
  readonly actionLabels = ACTION_LABELS;

  statut: EngagementRessourceStatut | null = null;
  loading = true;
  notFound = false;
  submitting = false;
  errorMessage = '';

  private token = '';

  constructor(
    private route: ActivatedRoute,
    private engagementService: EngagementRessourceService,
  ) {}

  ngOnInit(): void {
    this.token = this.route.snapshot.paramMap.get('token') || '';
    this.charger();
  }

  private charger(): void {
    this.loading = true;
    this.engagementService.getByToken(this.token).subscribe({
      next: (statut) => { this.statut = statut; this.loading = false; },
      error: () => { this.notFound = true; this.loading = false; },
    });
  }

  agir(action: string): void {
    if (this.submitting) return;
    this.submitting = true;
    this.errorMessage = '';
    this.engagementService.agir(this.token, action).subscribe({
      next: (statut) => { this.statut = statut; this.submitting = false; },
      error: (err) => {
        this.errorMessage = err?.error?.error || "Cette action n'est plus disponible.";
        this.submitting = false;
      },
    });
  }
}
