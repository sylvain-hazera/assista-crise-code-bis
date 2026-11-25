import { Component, Input, OnChanges, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { TeamService } from '../../../services/team.service';
import { NoeudEquipe, Team } from '../../../shared/models/team.model';

/**
 * Nœuds radio dédiés de l'équipe (25/11/2026, vision d'Olivier F4GLD) : des boîtiers qui ne
 * servent qu'à elle, configurés (canaux d'urgence 5 crise, 6 équipe, 7 commune) avant d'être
 * confiés aux intervenants — par Bluetooth depuis l'application, ou à distance par la
 * passerelle pour un nœud Meshtastic dont la clé d'admin autorise la passerelle.
 */
@Component({
  selector: 'app-noeuds-equipe',
  standalone: true,
  imports: [FormsModule, DatePipe],
  template: `
    <div class="detail-section">
      <div class="section-header">
        <h3><span class="material-icons">settings_input_antenna</span> Nœuds de l'équipe</h3>
      </div>
      <p class="page-hint">
        Boîtiers dédiés à l'équipe. Pour les configurer : application Assista-Crise, Compte &gt; Radio &gt;
        « Préparer un nœud dédié de l'équipe » (Bluetooth), ou « Configurer à distance » ci-dessous
        (Meshtastic 2.5 et plus : la clé publique de la passerelle de la structure doit figurer dans
        la clé d'admin du nœud).
      </p>
      @if (!noeuds.length) { <p class="no-missions">Aucun nœud dédié pour l'instant.</p> }
      @for (n of noeuds; track n.id) {
        <div class="noeud-ligne" [attr.data-noeud]="n.identifiant">
          <div class="noeud-titre">
            <strong>{{ n.nom || n.identifiant }}</strong>
            <span class="pastille">{{ n.protocole === 'MESHTASTIC' ? 'Meshtastic' : 'MeshCore' }}</span>
            <span class="pastille" [class.ok]="n.etat === 'CONFIE'">{{ n.etat_libelle }}{{ n.confie_a_nom ? ' : ' + n.confie_a_nom : '' }}</span>
            <span class="pastille" [class.ok]="n.a_jour" [class.alerte]="!n.a_jour">{{ n.a_jour ? 'canaux à jour' : (n.configure_le ? 'canaux à mettre à jour' : 'jamais configuré') }}</span>
          </div>
          @if (n.configure_le) {
            <div class="noeud-detail">Configuré le {{ n.configure_le | date:'dd/MM/yyyy HH:mm' }} ({{ n.moyen_configuration === 'A_DISTANCE' ? 'à distance' : 'Bluetooth' }})</div>
          }
          <div class="canal-actions">
            @if (n.protocole === 'MESHTASTIC') {
              <button class="btn-secondary sm" type="button" (click)="aDistance(n)" [disabled]="occupe">Configurer à distance</button>
            }
            @if (n.etat === 'CONFIE') {
              <button class="btn-secondary sm" type="button" (click)="etat(n, null)" [disabled]="occupe">Rendu</button>
            } @else {
              <select [ngModel]="''" (ngModelChange)="etat(n, $event)" [attr.aria-label]="'Confier ' + (n.nom || n.identifiant)">
                <option value="">Confier à…</option>
                @for (m of membres(); track m.id) { <option [value]="m.id">{{ m.nom }}</option> }
              </select>
            }
            <button class="btn-secondary sm" type="button" (click)="horsService(n)" [disabled]="occupe">
              {{ n.etat === 'HORS_SERVICE' ? 'Remettre en réserve' : 'Hors service' }}
            </button>
            <button class="btn-danger sm" type="button" (click)="retirer(n)" [disabled]="occupe">Retirer</button>
          </div>
        </div>
      }
      <form class="noeud-ajout" (ngSubmit)="ajouter()">
        <select name="protocole" [(ngModel)]="protocole" aria-label="Protocole du nœud">
          <option value="MESHTASTIC">Meshtastic</option>
          <option value="MESHCORE">MeshCore</option>
        </select>
        <input name="identifiant" [(ngModel)]="identifiant" required autocomplete="off"
               [placeholder]="protocole === 'MESHTASTIC' ? 'n° de nœud (!a1b2c3d4)' : 'clé publique (hex)'" aria-label="Identifiant du nœud"/>
        <input name="nom" [(ngModel)]="nom" maxlength="40" placeholder="Nom (facultatif)" aria-label="Nom du nœud"/>
        <button class="btn-secondary sm" type="submit" [disabled]="occupe || !identifiant.trim()">Ajouter</button>
      </form>
      @if (message) { <p class="canal-message" role="status">{{ message }}</p> }
      @if (erreur) { <p class="canal-erreur" role="alert">{{ erreur }}</p> }
    </div>
  `,
  styles: [`
    .noeud-ligne { padding: .5rem 0; border-top: 1px solid var(--ac-border, #e5e7eb); }
    .noeud-titre { display: flex; flex-wrap: wrap; gap: .4rem; align-items: center; }
    .pastille { font-size: .75rem; padding: .05rem .5rem; border-radius: 999px; background: var(--ac-surface-2, #eef2f7); }
    .pastille.ok { background: #dcfce7; color: #166534; }
    .pastille.alerte { background: #fef3c7; color: #92400e; }
    .noeud-detail { font-size: .85rem; color: var(--ac-text-muted, #6b7280); }
    .canal-actions, .noeud-ajout { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .4rem; align-items: center; }
    .canal-erreur { color: #b91c1c; } .canal-message { color: #15803d; }
  `],
})
export class NoeudsEquipeComponent implements OnChanges {
  @Input({ required: true }) equipe!: Team;
  private readonly teams = inject(TeamService);
  noeuds: NoeudEquipe[] = [];
  protocole: 'MESHTASTIC' | 'MESHCORE' = 'MESHTASTIC';
  identifiant = '';
  nom = '';
  occupe = false;
  message = '';
  erreur = '';

  ngOnChanges(): void {
    if (!this.equipe?.id) return;
    this.teams.noeuds(this.equipe.id).subscribe({ next: (r) => this.noeuds = r.noeuds, error: () => this.noeuds = [] });
  }

  membres(): { id: string; nom: string }[] {
    return this.equipe.members_info ?? [];
  }

  ajouter(): void {
    if (!this.equipe.id) return;
    this.occupe = true; this.erreur = '';
    this.teams.ajouterNoeud(this.equipe.id, { protocole: this.protocole, identifiant: this.identifiant.trim(), nom: this.nom.trim() || undefined })
      .subscribe({
        next: (r) => { this.noeuds = r.noeuds; this.identifiant = this.nom = ''; this.occupe = false; this.message = 'Nœud ajouté.'; },
        error: (e) => this.echec(e),
      });
  }

  etat(n: NoeudEquipe, confieA: string | null): void {
    if (!this.equipe.id || (confieA === '')) return;
    this.maj(n, { confie_a: confieA });
  }

  horsService(n: NoeudEquipe): void {
    this.maj(n, { etat: n.etat === 'HORS_SERVICE' ? 'EN_RESERVE' : 'HORS_SERVICE' });
  }

  private maj(n: NoeudEquipe, corps: Partial<{ etat: string; confie_a: string | null }>): void {
    this.occupe = true; this.erreur = '';
    this.teams.modifierNoeud(this.equipe.id!, n.id, corps).subscribe({
      next: (r) => { this.noeuds = this.noeuds.map(x => x.id === r.id ? r : x); this.occupe = false; },
      error: (e) => this.echec(e),
    });
  }

  retirer(n: NoeudEquipe): void {
    if (!confirm(`Retirer ${n.nom || n.identifiant} des nœuds de l'équipe ? Le boîtier garde ses canaux.`)) return;
    this.occupe = true;
    this.teams.retirerNoeud(this.equipe.id!, n.id).subscribe({
      next: () => { this.noeuds = this.noeuds.filter(x => x.id !== n.id); this.occupe = false; },
      error: (e) => this.echec(e),
    });
  }

  aDistance(n: NoeudEquipe): void {
    this.occupe = true; this.erreur = '';
    this.teams.configurerNoeudADistance(this.equipe.id!, n.id).subscribe({
      next: (r) => {
        this.occupe = false;
        this.message = `${r.taches} canal(aux) envoyé(s) par la passerelle ${r.passerelle}. ${r.prerequis}`;
        this.ngOnChanges();
      },
      error: (e) => this.echec(e),
    });
  }

  private echec(e: { error?: { error?: string } }): void {
    this.occupe = false;
    this.erreur = e?.error?.error ?? 'Opération impossible.';
  }
}
