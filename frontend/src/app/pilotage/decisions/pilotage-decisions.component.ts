import { Component, OnInit, effect, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { PilotageService } from '../pilotage.service';
import { AuthService } from '../../auth/services/auth.service';
import { ContactInstitutionService } from '../../services/contact-institution.service';
import {
  ActionCellule, CellulePilotageService, DecisionCellule, EtatPoints, InstantaneReleve, JalonChronologie, NouvelleAction,
  ReleveCellule, Retex, StatutAction,
} from '../../services/cellule-pilotage.service';
import { ActivatedRoute } from '@angular/router';

type Onglet = 'decisions' | 'actions' | 'releve' | 'chronologie' | 'points' | 'retex';

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

  // Chronologie, points de situation, RETEX (lot D)
  chronologie: JalonChronologie[] = [];
  nouveauJalon = '';
  points: EtatPoints | null = null;
  apercuPoint: Record<string, any> | null = null;
  textePoint = '';
  cadence: number | null = null;
  retex: Retex | null = null;
  retexSaisie = { ce_qui_a_marche: '', ce_qui_a_manque: '', ameliorations: '' };
  private readonly route = inject(ActivatedRoute);

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
    const demande = this.route.snapshot?.queryParamMap?.get('onglet') as Onglet | null;
    if (demande) this.changerOnglet(demande);
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
    const crise = this.crise;
    if (!crise) return;
    if (o === 'releve') this.service.apercuReleve(crise).subscribe({ next: a => this.apercu = a, error: () => {} });
    if (o === 'chronologie') this.service.chronologie(crise).subscribe({ next: c => this.chronologie = c, error: e => this.erreur = this.texteErreur(e) });
    if (o === 'points') {
      this.service.points(crise).subscribe({ next: p => { this.points = p; this.cadence = p.cadence_h; }, error: e => this.erreur = this.texteErreur(e) });
      this.service.apercuPoint(crise).subscribe({ next: a => this.apercuPoint = a, error: () => {} });
    }
    if (o === 'retex') this.service.retex(crise).subscribe({
      next: r => {
        this.retex = r;
        if (r.retex) this.retexSaisie = { ce_qui_a_marche: r.retex.ce_qui_a_marche, ce_qui_a_manque: r.retex.ce_qui_a_manque, ameliorations: r.retex.ameliorations };
      },
      error: e => this.erreur = this.texteErreur(e),
    });
  }

  ajouterJalon(): void {
    if (!this.crise || !this.nouveauJalon.trim()) return;
    this.service.ajouterJalon(this.crise, this.nouveauJalon.trim()).subscribe({
      next: () => { this.nouveauJalon = ''; this.changerOnglet('chronologie'); },
      error: e => this.erreur = this.texteErreur(e),
    });
  }

  diffuserPoint(): void {
    if (!this.crise) return;
    this.service.diffuserPoint(this.crise, this.textePoint).subscribe({
      next: () => { this.textePoint = ''; this.message = 'Point de situation diffusé.'; this.pilotage.rafraichirTerrain(); this.changerOnglet('points'); },
      error: e => this.erreur = this.texteErreur(e),
    });
  }

  fixerCadence(): void {
    if (!this.crise) return;
    this.service.cadence(this.crise, this.cadence || null).subscribe({
      next: r => { this.message = r.cadence_h ? `Rappel d’un point de situation toutes les ${r.cadence_h} h.` : 'Plus de rappel de point de situation.';
                   this.pilotage.rafraichirTerrain(); this.changerOnglet('points'); },
      error: e => this.erreur = this.texteErreur(e),
    });
  }

  enregistrerRetex(): void {
    if (!this.crise) return;
    this.service.enregistrerRetex(this.crise, this.retexSaisie).subscribe({
      next: () => { this.message = 'Retour d’expérience enregistré.'; this.changerOnglet('retex'); },
      error: e => this.erreur = this.texteErreur(e),
    });
  }

  /** « 1 h 25 » pour un délai en minutes. */
  duree(min: number | null): string {
    if (min === null || min === undefined) return '—';
    return min >= 60 ? `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, '0')}` : `${min} min`;
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
