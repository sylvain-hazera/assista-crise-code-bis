import { Component, OnInit, effect, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { PilotageService } from '../pilotage.service';
import { AuthService } from '../../auth/services/auth.service';
import { ContactInstitutionService } from '../../services/contact-institution.service';
import {
  ActionCellule, CellulePilotageService, DecisionCellule, InstantaneReleve, NouvelleAction, ReleveCellule, StatutAction,
} from '../../services/cellule-pilotage.service';

type Onglet = 'decisions' | 'actions' | 'releve';

/**
 * Décisions et actions de la cellule, et relève (23/11/2026) : « qui fait quoi, pour quand ».
 * Un journal des décisions distinct de la main courante ; chaque décision porte ses actions
 * (responsable, échéance, état) ; la relève passe l'état à l'équipe suivante, qui la reprend.
 */
@Component({
  selector: 'app-pilotage-decisions',
  standalone: true,
  imports: [DatePipe, FormsModule],
  templateUrl: './pilotage-decisions.component.html',
  styleUrl: './pilotage-decisions.component.scss',
})
export class PilotageDecisionsComponent implements OnInit {
  readonly pilotage = inject(PilotageService);
  private readonly service = inject(CellulePilotageService);
  private readonly auth = inject(AuthService);
  private readonly contacts = inject(ContactInstitutionService);

  onglet: Onglet = 'decisions';
  decisions: DecisionCellule[] = [];
  actions: ActionCellule[] = [];
  seulementMiennes = false;
  releves: ReleveCellule[] = [];
  apercu: InstantaneReleve | null = null;
  pointsVigilance = '';
  membres: { id: string; nom: string }[] = [];
  erreur = '';
  message = '';

  // Nouvelle décision
  texte = '';
  nouvelles: NouvelleAction[] = [];
  envoi = false;

  readonly statuts: { valeur: StatutAction; libelle: string }[] = [
    { valeur: 'A_FAIRE', libelle: 'À faire' }, { valeur: 'EN_COURS', libelle: 'En cours' },
    { valeur: 'FAIT', libelle: 'Fait' }, { valeur: 'ABANDONNEE', libelle: 'Abandonnée' },
  ];

  constructor() {
    // Changer de crise dans la barre du haut recharge l'écran.
    effect(() => { if (this.pilotage.criseId()) this.charger(); });
  }

  ngOnInit(): void {
    const institution = this.auth.getCurrentUser()?.institution_id;
    if (institution) {
      this.contacts.getForInstitution(institution).subscribe({
        next: cs => this.membres = cs.filter(c => c.actif && c.utilisateur)
          .map(c => ({ id: c.utilisateur, nom: c.utilisateur_nom || c.utilisateur_email || 'Membre' }))
          .sort((a, b) => a.nom.localeCompare(b.nom)),
        error: () => { this.membres = []; },
      });
    }
  }

  get crise(): string | null { return this.pilotage.criseId(); }

  charger(): void {
    const crise = this.crise;
    if (!crise) return;
    this.erreur = '';
    this.service.decisions(crise).subscribe({ next: d => this.decisions = d, error: e => this.erreur = this.texteErreur(e) });
    this.service.actions(crise, this.seulementMiennes).subscribe({ next: a => this.actions = a, error: () => {} });
    this.service.releves(crise).subscribe({ next: r => this.releves = r, error: () => {} });
  }

  changerOnglet(o: Onglet): void {
    this.onglet = o;
    if (o === 'releve' && this.crise) this.service.apercuReleve(this.crise).subscribe({ next: a => this.apercu = a, error: () => {} });
  }

  ajouterAction(): void { this.nouvelles.push({ intitule: '', responsable: null, responsable_libre: '', echeance: null }); }
  retirerAction(i: number): void { this.nouvelles.splice(i, 1); }

  decider(): void {
    const crise = this.crise;
    if (!crise || !this.texte.trim() || this.envoi) return;
    this.envoi = true;
    const actions = this.nouvelles.filter(a => a.intitule.trim()).map(a => ({
      intitule: a.intitule.trim(), responsable: a.responsable || null,
      responsable_libre: a.responsable ? '' : (a.responsable_libre || '').trim(),
      echeance: a.echeance ? new Date(a.echeance).toISOString() : null,
    }));
    this.service.decider(crise, this.texte.trim(), actions).subscribe({
      next: d => {
        this.decisions = [d, ...this.decisions];
        this.texte = ''; this.nouvelles = []; this.envoi = false;
        this.message = `Décision enregistrée${actions.length ? `, ${actions.length} action(s)` : ''}.`;
        this.service.actions(crise, this.seulementMiennes).subscribe(a => this.actions = a);
      },
      error: e => { this.envoi = false; this.erreur = this.texteErreur(e); },
    });
  }

  changerStatut(a: ActionCellule, statut: StatutAction): void {
    this.service.modifierAction(a.id, { statut }).subscribe({
      next: maj => {
        Object.assign(a, maj);
        this.decisions.forEach(d => d.actions.forEach(x => { if (x.id === maj.id) Object.assign(x, maj); }));
      },
      error: e => this.erreur = this.texteErreur(e),
    });
  }

  basculerMiennes(): void {
    this.seulementMiennes = !this.seulementMiennes;
    if (this.crise) this.service.actions(this.crise, this.seulementMiennes).subscribe(a => this.actions = a);
  }

  get enRetard(): number { return this.actions.filter(a => a.en_retard).length; }

  rediger(): void {
    if (!this.crise) return;
    this.service.rediger(this.crise, this.pointsVigilance).subscribe({
      next: r => { this.releves = [r, ...this.releves]; this.pointsVigilance = ''; this.message = 'Relève rédigée : elle attend d’être reprise par la personne qui arrive.'; },
      error: e => this.erreur = this.texteErreur(e),
    });
  }

  reprendre(r: ReleveCellule): void {
    this.service.reprendre(r.id).subscribe({
      next: maj => { Object.assign(r, maj); this.message = 'Relève reprise.'; },
      error: e => this.erreur = this.texteErreur(e),
    });
  }

  imprimer(): void { window.print(); }

  private texteErreur(e: { error?: { error?: string; detail?: string } }): string {
    return e?.error?.error || e?.error?.detail || 'Action impossible.';
  }
}
