import { Component, OnInit } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import {
  DecisionRevue, LigneRevueDroits, MatriceRevueDroits, RevueDroitsService,
} from '../../services/revue-droits.service';

/** Une décision en attente de confirmation dans la boîte de dialogue. */
interface DecisionEnCours {
  ligne: LigneRevueDroits;
  decision: DecisionRevue;
  affectation?: string;
  libelle: string;
  commentaire: string;
}

/**
 * Revue des droits (23/11/2026) : la matrice des droits des contacts d'une institution et de
 * ses filles, les anomalies relevées, et la revue elle-même — confirmer, ou retirer un droit,
 * daté, signé et journalisé. Voir backend/core/revue_droits.py.
 */
@Component({
  selector: 'app-revue-droits',
  standalone: true,
  imports: [DatePipe, FormsModule, RouterLink],
  templateUrl: './revue-droits.component.html',
  styleUrl: './revue-droits.component.scss',
})
export class RevueDroitsComponent implements OnInit {
  matrice: MatriceRevueDroits | null = null;
  chargement = true;
  erreur = '';
  message = '';

  institutionChoisie: string | null = null;
  filtreInstitution = '';
  filtre: 'toutes' | 'anomalies' | 'a-revoir' = 'toutes';
  recherche = '';
  voirInactives = false;

  enCours: DecisionEnCours | null = null;
  envoi = false;

  constructor(private service: RevueDroitsService) {}

  ngOnInit(): void { this.charger(); }

  charger(): void {
    this.chargement = true;
    this.erreur = '';
    this.service.matrice(this.institutionChoisie).subscribe({
      next: m => {
        this.matrice = m;
        this.institutionChoisie = m.institution.id;
        this.chargement = false;
      },
      error: e => {
        this.erreur = e?.error?.detail || e?.error?.error || 'Impossible de charger la revue des droits.';
        this.chargement = false;
      },
    });
  }

  changerInstitution(id: string): void {
    this.institutionChoisie = id;
    this.filtreInstitution = '';
    this.charger();
  }

  get lignes(): LigneRevueDroits[] {
    const q = this.recherche.trim().toLowerCase();
    return (this.matrice?.lignes ?? []).filter(l =>
      (this.voirInactives || l.actif)
      && (!this.filtreInstitution || l.institution === this.filtreInstitution)
      && (!q || l.nom.toLowerCase().includes(q) || l.email.toLowerCase().includes(q) || l.fonction.toLowerCase().includes(q))
      && (this.filtre === 'toutes'
        || (this.filtre === 'a-revoir' && this.aRevoir(l))
        || (this.filtre === 'anomalies' && this.anomalies(l).length > 0)));
  }

  aRevoir(l: LigneRevueDroits): boolean {
    return l.anomalies.some(a => a.code === 'JAMAIS_REVU' || a.code === 'REVUE_ECHUE');
  }

  /** Les anomalies hors « à revoir » (qui a sa propre colonne). */
  anomalies(l: LigneRevueDroits) {
    return l.anomalies.filter(a => a.code !== 'JAMAIS_REVU' && a.code !== 'REVUE_ECHUE');
  }

  get echeanceDepassee(): boolean {
    const e = this.matrice?.resume.prochaine_echeance;
    return !!e && new Date(e).getTime() < Date.now();
  }

  proposer(ligne: LigneRevueDroits, decision: DecisionRevue, libelle: string, affectation?: string): void {
    this.enCours = { ligne, decision, libelle, affectation, commentaire: '' };
  }

  confirmerDecision(): void {
    const d = this.enCours;
    if (!d) return;
    this.envoi = true;
    this.service.decider(d.ligne.contact, d.decision, d.commentaire, d.affectation).subscribe({
      next: r => {
        this.message = `${d.ligne.nom} : ${r.decision.toLowerCase()}.`;
        this.enCours = null;
        this.envoi = false;
        this.charger();
      },
      error: e => {
        this.message = e?.error?.error || e?.error?.detail || "La décision n'a pas été enregistrée.";
        this.envoi = false;
      },
    });
  }

  exporter(): void {
    if (!this.institutionChoisie) return;
    this.service.exporter(this.institutionChoisie).subscribe(blob => {
      const lien = document.createElement('a');
      lien.href = URL.createObjectURL(blob);
      lien.download = 'revue-des-droits.csv';
      lien.click();
      URL.revokeObjectURL(lien.href);
    });
  }
}
