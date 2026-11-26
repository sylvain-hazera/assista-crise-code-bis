import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { environment } from '../../../environments/environment';

export interface ReglagesBenevolat {
  annee: number;
  taux_horaire: string | null;
  tarif_km_voiture: string | null;
  tarif_km_deux_roues: string | null;
  recus_fiscaux: boolean;
  fondement_recus: string;
  signataire_nom: string;
  signataire_qualite: string;
  dernier_recu: number;
}

export interface AbandonFrais {
  id: string; utilisateur: string; nom: string; annee: number; statut: string; statut_libelle: string;
  montant: string | null; kilometres: number | null; deplacements: number; numero_recu: string;
  date_recu: string | null; motif_refus: string; date_demande: string;
}

export interface Valorisation {
  annee: number;
  reglages: ReglagesBenevolat;
  heures: string; kilometres: string; frais: string;
  valorisation_heures: string | null;
  benevoles: { utilisateur: string; nom: string; heures: string; kilometres: string; frais: string; valorisation: string | null }[];
  activites: { genre: string; nom: string; date: string; heures: string; benevoles: number }[];
  mois: { mois: string; heures: string }[];
  lignes_a_valider: number;
  abandons: AbandonFrais[];
  associations_organisees: { id: string; nom: string }[];
  taux_reduction_informatif: number;
}

/**
 * Le bénévolat d'une association, pour son bureau (26/11/2026, après l'annonce de FCBA 33) : les
 * heures et kilomètres VALIDÉS de l'année, leur valorisation aux taux que l'association retient,
 * les exports pour le comptable, et les renonciations au remboursement de frais avec leur reçu
 * fiscal.
 *
 * Aucun barème n'est imposé : il n'existe plus de barème kilométrique propre aux bénévoles depuis
 * 2022 et le barème fiscal dépend du véhicule et du kilométrage annuel ; c'est au trésorier de
 * reporter ce qu'il applique.
 */
@Component({
  selector: 'app-benevolat',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './benevolat.component.html',
  styleUrl: './benevolat.component.scss',
})
export class BenevolatComponent implements OnInit {
  associations: { id: string; nom: string }[] = [];
  institution = '';
  annee = new Date().getFullYear();
  donnees: Valorisation | null = null;
  reglages: ReglagesBenevolat | null = null;
  erreur = '';
  message = '';
  aRefuser: AbandonFrais | null = null;
  motif = '';
  /** Jusqu'où l'association intervient (26/11/2026) : échelon compté depuis son siège. */
  etendue: { echelon: string; echelons: { code: string; libelle: string; territoire: string }[]; modifiable: boolean; concernee: boolean } | null = null;

  private readonly url = `${environment.apiUrl}/benevolat/`;

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    this.http.get<{ associations_organisees: { id: string; nom: string }[] }>(this.url).subscribe({
      next: (r) => {
        this.associations = r.associations_organisees;
        this.institution = this.associations[0]?.id ?? '';
        if (this.institution) this.charger();
      },
      error: (err) => this.erreur = err?.error?.detail || 'La page n\'a pas pu être chargée.',
    });
  }

  get annees(): number[] {
    const courante = new Date().getFullYear();
    return [courante + 1, courante, courante - 1, courante - 2];
  }

  chargerEtendue(): void {
    this.http.get<BenevolatComponent['etendue']>(`${environment.apiUrl}/associations/${this.institution}/echelon/`).subscribe({
      next: (e) => this.etendue = e, error: () => this.etendue = null,
    });
  }

  changerEtendue(echelon: string): void {
    this.http.put<BenevolatComponent['etendue']>(`${environment.apiUrl}/associations/${this.institution}/echelon/`, { echelon }).subscribe({
      next: (e) => { this.etendue = e; this.message = 'Étendue d\'intervention enregistrée.'; },
      error: (err) => this.erreur = err?.error?.detail || 'L\'étendue n\'a pas pu être changée.',
    });
  }

  charger(): void {
    this.chargerEtendue();
    this.erreur = '';
    this.http.get<Valorisation>(this.url, { params: { institution: this.institution, annee: String(this.annee) } }).subscribe({
      next: (d) => { this.donnees = d; this.reglages = { ...d.reglages }; },
      error: (err) => this.erreur = err?.error?.detail || 'Le bénévolat n\'a pas pu être chargé.',
    });
  }

  enregistrerReglages(): void {
    const r = this.reglages;
    if (!r) return;
    if (r.recus_fiscaux && !r.signataire_nom.trim()) { this.erreur = 'Indiquez qui signe les reçus fiscaux.'; return; }
    this.erreur = '';
    this.http.put<ReglagesBenevolat>(`${this.url}reglages/`, { ...r, institution: this.institution, annee: this.annee }).subscribe({
      next: () => { this.message = 'Réglages de l\'année enregistrés.'; this.charger(); },
      error: (err) => this.erreur = err?.error?.detail || 'Les réglages n\'ont pas pu être enregistrés.',
    });
  }

  exporter(fichier: 'csv' | 'xlsx'): void {
    this.http.get(`${this.url}export/`, { params: { institution: this.institution, annee: String(this.annee), fichier }, responseType: 'blob' }).subscribe({
      next: (contenu) => this.enregistrerFichier(contenu, `benevolat-${this.annee}.${fichier}`),
      error: () => this.erreur = 'L\'export n\'a pas pu être téléchargé.',
    });
  }

  traiter(a: AbandonFrais, geste: 'accepter' | 'refuser'): void {
    if (geste === 'refuser' && !this.motif.trim()) { this.erreur = 'Dites pourquoi vous refusez.'; return; }
    if (geste === 'accepter' && !confirm(`Accepter la renonciation de ${a.nom} et émettre son reçu fiscal ?`)) return;
    this.erreur = '';
    this.http.post<AbandonFrais>(`${this.url}abandons/${a.id}/`, { geste, motif: this.motif.trim() }).subscribe({
      next: (r) => {
        this.aRefuser = null;
        this.motif = '';
        this.message = r.numero_recu ? `Reçu n° ${r.numero_recu} émis : ${a.nom} est prévenu.` : 'Demande refusée.';
        this.charger();
      },
      error: (err) => this.erreur = err?.error?.detail || 'La demande n\'a pas pu être traitée.',
    });
  }

  telechargerRecu(a: AbandonFrais): void {
    this.http.get(`${this.url}abandons/${a.id}/recu/`, { responseType: 'blob' }).subscribe({
      next: (pdf) => this.enregistrerFichier(pdf, `recu-${a.numero_recu}.pdf`),
      error: () => this.erreur = 'Le reçu n\'a pas pu être téléchargé.',
    });
  }

  private enregistrerFichier(contenu: Blob, nom: string): void {
    const lien = document.createElement('a');
    lien.href = URL.createObjectURL(contenu);
    lien.download = nom;
    lien.click();
    URL.revokeObjectURL(lien.href);
  }

  /** Hauteur relative d'une barre du graphique mensuel. */
  part(heures: string): number {
    const maxi = Math.max(...(this.donnees?.mois ?? []).map(m => Number(m.heures)), 1);
    return Math.round((Number(heures) / maxi) * 100);
  }
}
