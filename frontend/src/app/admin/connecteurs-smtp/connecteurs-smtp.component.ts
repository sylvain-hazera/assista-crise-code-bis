import { Component, Input, OnChanges } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { ConnecteurSMTP, ConnecteursSmtpService } from '../../services/connecteurs-smtp.service';

/**
 * Connecteurs SMTP d'une institution, dans l'onglet « Envois » de sa fiche, sous Brevo
 * (22/11/2026). Proposés au moment d'envoyer une campagne d'invitation, avec leur adresse.
 */
@Component({
  selector: 'app-connecteurs-smtp',
  standalone: true,
  imports: [FormsModule, DatePipe],
  templateUrl: './connecteurs-smtp.component.html',
  styleUrl: './connecteurs-smtp.component.scss',
})
export class ConnecteursSmtpComponent implements OnChanges {
  @Input({ required: true }) institutionId!: string;

  connecteurs: ConnecteurSMTP[] = [];
  saisie: ConnecteurSMTP | null = null;
  message = '';
  erreur = '';

  constructor(private service: ConnecteursSmtpService) {}

  ngOnChanges(): void { this.charger(); }

  charger(): void {
    if (!this.institutionId) return;
    this.service.lister(this.institutionId).subscribe({ next: l => this.connecteurs = l, error: () => this.connecteurs = [] });
  }

  nouveau(): void {
    this.saisie = { institution: this.institutionId, nom: '', hote: '', port: 587, chiffrement: 'STARTTLS', identifiant: '',
                    mot_de_passe: '', expediteur_email: '', expediteur_nom: '', actif: true };
  }

  modifier(c: ConnecteurSMTP): void { this.saisie = { ...c, identifiant: '', mot_de_passe: '' }; }

  /** Le port suit le chiffrement tant qu'on ne l'a pas changé soi-même. */
  changerChiffrement(ch: ConnecteurSMTP['chiffrement']): void {
    if (!this.saisie) return;
    if ([587, 465, 25].includes(this.saisie.port)) this.saisie.port = ch === 'SSL' ? 465 : ch === 'STARTTLS' ? 587 : 25;
    this.saisie.chiffrement = ch;
  }

  enregistrer(): void {
    const s = this.saisie;
    if (!s) return;
    const appel = s.id ? this.service.modifier(s.id, s) : this.service.creer(s);
    appel.subscribe({
      next: () => { this.message = 'Connecteur enregistré.'; this.erreur = ''; this.saisie = null; this.charger(); },
      error: e => this.erreur = this.texte(e),
    });
  }

  supprimer(c: ConnecteurSMTP): void {
    if (!c.id || !window.confirm(`Supprimer le connecteur « ${c.nom} » ?`)) return;
    this.service.supprimer(c.id).subscribe({ next: () => this.charger(), error: e => this.erreur = this.texte(e) });
  }

  essayer(c: ConnecteurSMTP): void {
    if (!c.id) return;
    this.message = ''; this.erreur = '';
    this.service.essai(c.id).subscribe({
      next: r => { this.message = r.message ?? 'Essai envoyé.'; this.charger(); },
      error: e => { this.erreur = this.texte(e); this.charger(); },
    });
  }

  private texte(e: any): string {
    const corps = e?.error;
    if (!corps) return 'Action impossible.';
    if (typeof corps === 'string') return corps;
    return corps.error ?? corps.detail ?? Object.values(corps).flat().join(' ');
  }
}
