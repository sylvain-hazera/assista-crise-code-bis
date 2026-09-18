import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';

import { ConflitSynchronisationService } from '../../services/conflit-synchronisation.service';
import { ConflitSynchronisation } from '../../shared/models/conflit-synchronisation.model';

/** Arbitrage des conflits de synchronisation local -> central (satellites, voir le cadrage
 * "Chantier B") : un Dossier/Mission modifié des deux côtés pendant une coupure ne s'écrase
 * jamais silencieusement — un ConflitSynchronisation est créé côté central et attend ici un
 * choix explicite entre la version centrale et celle proposée par le satellite. Voir
 * ConflitSynchronisationViewSet côté backend (pas encore de page dédiée avant ce jour,
 * 2026-09-18). */
@Component({
  selector: 'app-conflits-synchronisation',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './conflits-synchronisation.component.html',
  styleUrl: './conflits-synchronisation.component.scss',
})
export class ConflitsSynchronisationComponent implements OnInit {

  conflits: ConflitSynchronisation[] = [];
  loading = true;
  errorMessage = '';

  detailOuvert: string | null = null;
  actionEnCours: string | null = null;

  constructor(private service: ConflitSynchronisationService) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading = true;
    this.errorMessage = '';
    this.service.getAll().subscribe({
      next: (data) => { this.conflits = data; this.loading = false; },
      error: () => { this.errorMessage = 'Impossible de charger les conflits de synchronisation.'; this.loading = false; },
    });
  }

  toggleDetail(conflit: ConflitSynchronisation): void {
    this.detailOuvert = this.detailOuvert === conflit.id ? null : conflit.id;
  }

  // payload_local ne porte que les champs réellement proposés par le satellite (voir
  // sync_outbox.py côté backend) — comparer uniquement ceux-là suffit à montrer ce qui
  // changerait, pas besoin d'un diff générique sur l'objet entier.
  champsModifies(conflit: ConflitSynchronisation): string[] {
    return Object.keys(conflit.payload_local ?? {});
  }

  resoudre(conflit: ConflitSynchronisation, choix: 'GARDE_CENTRAL' | 'GARDE_LOCAL'): void {
    const libelle = choix === 'GARDE_CENTRAL' ? 'la version centrale' : 'la version locale (satellite)';
    if (!confirm(`Confirmer : conserver ${libelle} pour ce ${conflit.modele_libelle.toLowerCase()} ?`)) return;
    this.actionEnCours = conflit.id;
    this.errorMessage = '';
    this.service.resoudre(conflit.id, choix).subscribe({
      next: () => { this.actionEnCours = null; this.detailOuvert = null; this.load(); },
      error: (err) => {
        this.actionEnCours = null;
        this.errorMessage = err.error?.error || 'Impossible de résoudre ce conflit.';
      },
    });
  }

  statutClass(conflit: ConflitSynchronisation): string {
    return conflit.statut === 'EN_ATTENTE' ? 'statut-attention' : 'statut-ok';
  }

  statutLabel(conflit: ConflitSynchronisation): string {
    if (conflit.statut === 'EN_ATTENTE') return "En attente d'arbitrage";
    if (conflit.statut === 'RESOLU_GARDE_CENTRAL') return 'Résolu — version centrale conservée';
    return 'Résolu — version locale appliquée';
  }
}
