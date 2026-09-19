import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { TeamService } from '../../services/team.service';
import { RessourceMobilisee } from '../../shared/models/ressource-mobilisee.model';

type TypeFilter = 'ALL' | 'personne' | 'materiel';

// Nombre de couleurs de cadre distinctes pour les groupes équipe — au-delà, ça recommence à
// tourner (cyclique) plutôt que d'en ajouter indéfiniment, une répétition occasionnelle sur une
// longue liste reste sans ambiguïté puisque le nom de l'équipe est toujours affiché en tête.
const NB_COULEURS_EQUIPE = 6;

/** Une "unité" = une personne ET, si elle en a apporté, le(s) matériel(s) qu'elle a apportés
 * (couple indissociable, voir Offer.presence_physique) — ou un matériel seul déposé par
 * quelqu'un qui n'est pas (ou plus) membre de l'équipe, avec son propriétaire toujours visible
 * pour qu'on puisse le retrouver facilement. */
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

/** Récap des ressources mobilisées (personnes ET matériel), où (institution/centre/crise) et
 * avec quoi (compétence ou matériel précis) — voir TeamViewSet.ressources_mobilisees. Groupé
 * par équipe par défaut (demande explicite du 2026-09-19) : chaque collectivité ne voit que ses
 * propres ressources (restriction appliquée côté serveur, sauf pour un administrateur
 * plateforme), et une personne apparaît regroupée avec le matériel qu'elle a elle-même apporté
 * (indissociable) plutôt que mélangée sans lien visible dans une liste plate. */
@Component({
  selector: 'app-ressources-mobilisees',
  standalone: true,
  imports: [CommonModule, FormsModule],
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

  /** Respecte la recherche/le filtre de type — base commune à l'export CSV (toujours à plat)
   * et au regroupement par équipe (voir `groupes` ci-dessous). */
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

  /** Regroupe filteredRows par équipe, puis à l'intérieur de chaque équipe fusionne chaque
   * membre avec le(s) matériel(s) qu'il a lui-même apportés (`materiel.proprietaire_id ===
   * personne.user_id`) — un matériel dont le propriétaire n'est pas membre de cette équipe (ou
   * n'a pas de propriétaire identifié) reste une unité à part, mais garde son propriétaire
   * visible (voir le template) pour rester facilement retrouvable. */
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

      // Les unités d'un même dépôt groupé (association/entreprise, voir Offer.groupe_id)
      // restent visuellement adjacentes, plutôt que dispersées dans la liste au hasard de
      // l'ordre alphabétique — sans quoi le lien entre elles ne serait visible que dans les
      // données, jamais à l'écran.
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
