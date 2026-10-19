import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { TeamService } from '../../services/team.service';
import { RessourceMobilisee } from '../../shared/models/ressource-mobilisee.model';
import { AffecterLogementResultat } from '../../shared/models/logement-intervenant.model';
import { LogementPickerModalComponent } from '../../shared/components/common/logement-picker-modal/logement-picker-modal.component';
import { FicheIntervenantModalComponent } from '../../shared/components/common/fiche-intervenant-modal/fiche-intervenant-modal.component';
import { FicheMaterielModalComponent } from '../../shared/components/common/fiche-materiel-modal/fiche-materiel-modal.component';

type TypeFilter = 'ALL' | 'personne' | 'materiel';

// Couleurs de cadre des groupes équipe, réutilisées en cycle.
const NB_COULEURS_EQUIPE = 6;

/** Unité = une personne et le matériel qu'elle a apporté, ou un matériel seul (propriétaire affiché). */
interface UniteRessource {
  cle: string;
  personne: RessourceMobilisee | null;
  materiels: RessourceMobilisee[];
}

interface GroupeEquipe {
  equipe_id: string;
  equipe_nom: string;
  institution: string | null;
  unites: UniteRessource[];
  couleurIndex: number;
}

/** Ressources mobilisées (personnes et matériel), groupées par équipe
 * (TeamViewSet.ressources_mobilisees, scopé côté serveur). */
@Component({
  selector: 'app-ressources-mobilisees',
  standalone: true,
  imports: [CommonModule, FormsModule, LogementPickerModalComponent, FicheIntervenantModalComponent, FicheMaterielModalComponent],
  templateUrl: './ressources-mobilisees.component.html',
  styleUrl: './ressources-mobilisees.component.scss',
})
export class RessourcesMobiliseesComponent implements OnInit {
  rows: RessourceMobilisee[] = [];
  loading = true;
  errorMessage = '';

  typeFilter: TypeFilter = 'ALL';
  searchQuery = '';
  triNomAsc = true;

  // ── Besoin hébergement : sélection groupée + affectation ─────────────────────
  selection = new Set<string>();
  pickerOuvert = false;
  pickerIntervenantIds: string[] = [];
  pickerCriseId: string | null = null;

  constructor(private teamService: TeamService) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading = true;
    this.errorMessage = '';
    this.teamService.ressourcesMobilisees().subscribe({
      next: (rows) => { this.rows = rows; this.loading = false; },
      error: () => { this.errorMessage = 'Impossible de charger les ressources mobilisées.'; this.loading = false; },
    });
  }

  estSelectionne(userId: string | undefined): boolean {
    return !!userId && this.selection.has(userId);
  }

  basculerSelection(userId: string | undefined): void {
    if (!userId) return;
    if (this.selection.has(userId)) this.selection.delete(userId);
    else this.selection.add(userId);
  }

  /** Sélectionne ou désélectionne toute l'équipe (arrivées groupées d'une association). */
  basculerSelectionEquipe(groupe: GroupeEquipe): void {
    const ids = groupe.unites.map(u => u.personne?.user_id).filter((id): id is string => !!id);
    const toutSelectionne = ids.length > 0 && ids.every(id => this.selection.has(id));
    for (const id of ids) {
      if (toutSelectionne) this.selection.delete(id);
      else this.selection.add(id);
    }
  }

  equipeEntierementSelectionnee(groupe: GroupeEquipe): boolean {
    const ids = groupe.unites.map(u => u.personne?.user_id).filter((id): id is string => !!id);
    return ids.length > 0 && ids.every(id => this.selection.has(id));
  }

  get nombreSelectionnes(): number {
    return this.selection.size;
  }

  /** Sélecteur de logement pour une personne (il lui faut au moins une crise). */
  ouvrirPickerPourPersonne(personne: RessourceMobilisee): void {
    if (!personne.user_id || !personne.crise_ids.length) return;
    this.pickerIntervenantIds = [personne.user_id];
    this.pickerCriseId = personne.crise_ids[0];
    this.pickerOuvert = true;
  }

  /** Sélecteur de logement pour la sélection ; la crise est celle de la première personne. */
  ouvrirPickerPourSelection(): void {
    const personnes = this.filteredRows.filter(
      r => r.type === 'personne' && r.user_id && this.selection.has(r.user_id)
    );
    if (!personnes.length) return;
    const premiereAvecCrise = personnes.find(p => p.crise_ids.length > 0);
    if (!premiereAvecCrise) return;
    this.pickerIntervenantIds = personnes.map(p => p.user_id!).filter(Boolean);
    this.pickerCriseId = premiereAvecCrise.crise_ids[0];
    this.pickerOuvert = true;
  }

  fermerPicker(): void {
    this.pickerOuvert = false;
  }

  onLogementAffecte(_resultat: AffecterLogementResultat): void {
    this.pickerOuvert = false;
    this.selection.clear();
    this.load();
  }

  // ── Fiche intervenant ───────────────────────────────────────────────────────────
  ficheOuverte = false;
  ficheUserId: string | null = null;
  ficheCriseId: string | null = null;
  ficheEquipeId: string | null = null;
  ficheEquipeNom: string | null = null;

  ouvrirFiche(personne: RessourceMobilisee): void {
    if (!personne.user_id) return;
    this.ficheUserId = personne.user_id;
    this.ficheCriseId = personne.crise_ids[0] ?? null;
    this.ficheEquipeId = personne.equipe_id;
    this.ficheEquipeNom = personne.equipe_nom;
    this.ficheOuverte = true;
  }

  fermerFiche(): void {
    this.ficheOuverte = false;
  }

  // ── Fiche matériel ──────────────────────────────────────────────────────────────
  ficheMaterielOuverte = false;
  ficheMaterielOffreId: string | null = null;

  ouvrirFicheMateriel(offreId: string): void {
    this.ficheMaterielOffreId = offreId;
    this.ficheMaterielOuverte = true;
  }

  fermerFicheMateriel(): void {
    this.ficheMaterielOuverte = false;
  }

  /** Recherche/filtre de type, base de l'export CSV et du regroupement. */
  get filteredRows(): RessourceMobilisee[] {
    const q = this.searchQuery.trim().toLowerCase();
    let list = this.rows;
    if (this.typeFilter !== 'ALL') list = list.filter(r => r.type === this.typeFilter);
    if (q) {
      list = list.filter(r =>
        r.nom.toLowerCase().includes(q) ||
        r.equipe_nom.toLowerCase().includes(q) ||
        (r.institution ?? '').toLowerCase().includes(q) ||
        (r.detail ?? '').toLowerCase().includes(q) ||
        (r.proprietaire_nom ?? '').toLowerCase().includes(q) ||
        (r.organisation_nom ?? '').toLowerCase().includes(q) ||
        r.centres.some(c => c.toLowerCase().includes(q)) ||
        r.crises.some(c => c.toLowerCase().includes(q))
      );
    }
    const dir = this.triNomAsc ? 1 : -1;
    return [...list].sort((a, b) => a.nom.localeCompare(b.nom) * dir);
  }

  toggleTriNom(): void {
    this.triNomAsc = !this.triNomAsc;
  }

  /** Groupe par équipe, puis rattache à chaque membre le matériel qu'il a apporté. */
  get groupes(): GroupeEquipe[] {
    const parEquipe = new Map<string, RessourceMobilisee[]>();
    for (const r of this.filteredRows) {
      const liste = parEquipe.get(r.equipe_id) ?? [];
      liste.push(r);
      parEquipe.set(r.equipe_id, liste);
    }

    const groupes: GroupeEquipe[] = [];
    let index = 0;
    for (const [equipe_id, lignes] of parEquipe) {
      const personnes = lignes.filter(l => l.type === 'personne');
      const materiels = lignes.filter(l => l.type === 'materiel');
      const materielsParProprietaire = new Map<string, RessourceMobilisee[]>();
      const materielsRestants: RessourceMobilisee[] = [];
      for (const m of materiels) {
        if (m.proprietaire_id && personnes.some(p => p.user_id === m.proprietaire_id)) {
          const liste = materielsParProprietaire.get(m.proprietaire_id) ?? [];
          liste.push(m);
          materielsParProprietaire.set(m.proprietaire_id, liste);
        } else {
          materielsRestants.push(m);
        }
      }

      const unites: UniteRessource[] = [
        ...personnes.map(p => ({
          cle: `p-${p.user_id}`,
          personne: p,
          materiels: (p.user_id && materielsParProprietaire.get(p.user_id)) || [],
        })),
        ...materielsRestants.map((m, i) => ({ cle: `m-${i}-${m.nom}`, personne: null, materiels: [m] })),
      ];

      // Les unités d'un même dépôt groupé (Offer.groupe_id) restent adjacentes.
      unites.sort((a, b) => {
        const gA = a.materiels[0]?.groupe_id || '';
        const gB = b.materiels[0]?.groupe_id || '';
        if (gA !== gB) return gA.localeCompare(gB);
        const nomA = a.personne?.nom || a.materiels[0]?.nom || '';
        const nomB = b.personne?.nom || b.materiels[0]?.nom || '';
        return nomA.localeCompare(nomB);
      });

      groupes.push({
        equipe_id,
        equipe_nom: lignes[0].equipe_nom,
        institution: lignes[0].institution,
        unites,
        couleurIndex: index % NB_COULEURS_EQUIPE,
      });
      index++;
    }

    const dir = this.triNomAsc ? 1 : -1;
    return groupes.sort((a, b) => a.equipe_nom.localeCompare(b.equipe_nom) * dir);
  }

  get countPersonnes(): number {
    return this.rows.filter(r => r.type === 'personne').length;
  }

  get countMateriel(): number {
    return this.rows.filter(r => r.type === 'materiel').length;
  }

  exportCSV(): void {
    const rows = this.filteredRows;
    const headers = [
      'Type', 'Nom', 'Équipe', 'Institution', 'Crise(s)', 'Centre(s)', 'Compétence / Matériel', 'Statut',
      'Propriétaire (matériel)', 'Présence physique', 'Organisation (dépôt groupé)',
    ];
    const lines = rows.map(r => [
      r.type === 'personne' ? 'Personne' : 'Matériel',
      r.nom, r.equipe_nom, r.institution ?? '',
      r.crises.join(' / '), r.centres.join(' / '),
      r.detail ?? '', r.statut ?? '',
      r.proprietaire_nom ?? '',
      r.presence_physique == null ? '' : (r.presence_physique ? 'Oui' : 'Non'),
      r.organisation_nom ?? '',
    ].map(v => `"${String(v).replace(/"/g, '""')}"`).join(','));

    const csv = [headers.join(','), ...lines].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' }));
    a.download = `ressources_mobilisees_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }
}
