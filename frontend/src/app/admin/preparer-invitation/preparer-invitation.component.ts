import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import {
  ApercuInvitation, CampagneInvitation, DelegationGestionService, PreparationInvitation,
} from '../../services/delegation-gestion.service';

/**
 * « Préparer l'invitation » (22/11/2026) : la fenêtre de rédaction des invitations aux
 * collectivités, dans le style de la relecture avant envoi. Un texte relu une fois, à champs
 * remplis pour chaque collectivité, un aperçu exact, et le choix du connecteur d'envoi (Brevo,
 * SMTP de l'association, SMTP de la plateforme) avec l'adresse qui sera utilisée. Rien ne part
 * sans confirmation ; l'envoi se fait ensuite en tâche de fond, suivi dans l'historique.
 */
@Component({
  selector: 'app-preparer-invitation',
  standalone: true,
  imports: [FormsModule, DatePipe],
  templateUrl: './preparer-invitation.component.html',
  styleUrls: ['../../shared/components/common/relecture-envoi/relecture-envoi.component.scss', './preparer-invitation.component.scss'],
})
export class PreparerInvitationComponent implements OnInit {
  @Input({ required: true }) delegationId!: string;
  @Input({ required: true }) institutions: string[] = [];
  @Output() fermee = new EventEmitter<void>();
  @Output() lancee = new EventEmitter<CampagneInvitation>();

  preparation: PreparationInvitation | null = null;
  sujet = '';
  corps = '';
  connecteur = '';
  apercuPour = '';
  apercu: ApercuInvitation | null = null;
  erreur = '';
  enCours = false;

  constructor(private service: DelegationGestionService) {}

  ngOnInit(): void {
    this.service.preparerInvitation(this.delegationId, this.institutions).subscribe({
      next: p => {
        this.preparation = p;
        this.sujet = p.sujet;
        this.corps = p.corps;
        this.connecteur = p.connecteurs[0]?.cle ?? '';
        this.apercuPour = p.pretes[0]?.id ?? '';
      },
      error: e => this.erreur = e?.error?.error ?? 'Préparation impossible.',
    });
  }

  get nombre(): number { return this.preparation?.pretes.length ?? 0; }

  get lienPresent(): boolean { return this.corps.includes('[LIEN]'); }

  voirApercu(): void {
    if (!this.apercuPour) return;
    this.service.apercuInvitation(this.delegationId, this.apercuPour, this.sujet, this.corps, this.connecteur).subscribe({
      next: a => { this.apercu = a; this.erreur = ''; },
      error: e => this.erreur = e?.error?.error ?? 'Aperçu impossible.',
    });
  }

  envoyer(): void {
    const choisi = this.preparation?.connecteurs.find(c => c.cle === this.connecteur);
    if (!choisi || !this.nombre) return;
    if (!window.confirm(`Envoyer maintenant le courriel à ${this.nombre} collectivité(s), par ${choisi.libelle} (${choisi.adresse}) ? `
      + 'Un courriel envoyé ne peut pas être rappelé.')) return;
    this.enCours = true;
    const ids = this.preparation!.pretes.map(p => p.id);
    this.service.lancerCampagne(this.delegationId, ids, this.sujet, this.corps, this.connecteur).subscribe({
      next: c => { this.enCours = false; this.lancee.emit(c); },
      error: e => { this.enCours = false; this.erreur = e?.error?.error ?? 'Envoi impossible.'; },
    });
  }
}
