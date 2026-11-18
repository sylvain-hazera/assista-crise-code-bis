import { CommonModule } from '@angular/common';
import { Component, Input, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { DossierPcsService } from '../../services/dossier-pcs.service';
import { InterlocuteurAlertePCSService } from '../../services/interlocuteur-alerte-pcs.service';
import {
  CATEGORIES_INTERLOCUTEUR_PCS, CategorieInterlocuteurPCS, InterlocuteurAlertePCS, MODES_ALERTE_PCS, ModeAlertePCS,
} from '../../shared/models/interlocuteur-alerte-pcs.model';

/** Sans eux, l'annuaire ne permet pas de prévenir ceux qui doivent l'être en premier (même liste
 * que `CATEGORIES_ATTENDUES` côté serveur, core/document_pcs.py). */
const CATEGORIES_ATTENDUES: CategorieInterlocuteurPCS[] = ['PREFECTURE', 'SDIS', 'GENDARMERIE_POLICE'];

interface Saisie {
  categorie: CategorieInterlocuteurPCS; nom: string; organisme: string;
  telephone: string; email: string; mode_alerte: ModeAlertePCS;
}

/**
 * Paragraphes 2.4 et 4.1 du plan communal de sauvegarde : l'annuaire de crise.
 *
 * Il se saisissait déjà, mais au fond de la fiche Institution, côté Administration. Mêmes
 * données, même service (`InterlocuteurAlertePCSService`) : cet écran met le paragraphe à sa
 * place, sous son nom.
 *
 * L'annuaire sert à l'ouverture d'une crise : ses interlocuteurs sont proposés pour être
 * prévenus, par courriel, par Matrix ou au téléphone, et l'on suit qui a accusé réception.
 */
@Component({
  selector: 'app-pcs-annuaire',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './pcs-annuaire.component.html',
  styleUrl: './pcs-paragraphe.scss',
})
export class PcsAnnuaireComponent implements OnInit {
  readonly categories = CATEGORIES_INTERLOCUTEUR_PCS;
  readonly modes = MODES_ALERTE_PCS.filter(m => m.disponible);

  /** Renseigné quand la page est affichée DANS la fiche d'une institution (onglet) : on tient
   * alors l'annuaire de cette institution-là, et non de celle de la personne. Une seule
   * implémentation pour les deux endroits — il y en avait deux, sous deux noms (18/11/2026). */
  @Input() institution: string | null = null;
  @Input() nomInstitution = '';
  get integre(): boolean { return !!this.institution; }

  institutionId = '';
  commune = '';
  sansCollectivite = false;
  chargement = true;
  erreur = '';

  interlocuteurs: InterlocuteurAlertePCS[] = [];
  saisie: Saisie = this.saisieVide();
  /** Identifiant de la fiche en cours de modification, ou `null` pour un ajout. */
  enModification: string | null = null;
  formulaireOuvert = false;
  enregistrement = false;

  constructor(private dossier: DossierPcsService, private service: InterlocuteurAlertePCSService) {}

  ngOnInit(): void {
    if (this.institution) { this.institutionId = this.institution; this.commune = this.nomInstitution; this.charger(); return; }
    this.dossier.lire().subscribe({
      next: (d) => { this.institutionId = d.institution; this.commune = d.commune.nom; this.charger(); },
      error: (e) => { this.chargement = false; this.sansCollectivite = e?.status === 403; if (!this.sansCollectivite) this.erreur = "Impossible de lire l'annuaire."; },
    });
  }

  private saisieVide(): Saisie {
    return { categorie: 'PREFECTURE', nom: '', organisme: '', telephone: '', email: '', mode_alerte: 'TELEPHONE' };
  }

  private charger(): void {
    this.service.getForInstitution(this.institutionId).subscribe({
      next: (liste) => { this.interlocuteurs = liste.filter(i => i.actif !== false); this.chargement = false; },
      error: () => { this.chargement = false; this.erreur = "Impossible de lire l'annuaire."; },
    });
  }

  /** L'annuaire rangé par catégorie, dans l'ordre du plan ; les catégories vides n'apparaissent pas. */
  get parCategorie(): { libelle: string; fiches: InterlocuteurAlertePCS[] }[] {
    return this.categories
      .map(c => ({ libelle: c.label, fiches: this.interlocuteurs.filter(i => i.categorie === c.value) }))
      .filter(groupe => groupe.fiches.length);
  }

  /** Les interlocuteurs de première heure qui manquent encore. */
  get categoriesManquantes(): string[] {
    const presentes = new Set(this.interlocuteurs.map(i => i.categorie));
    return this.categories.filter(c => CATEGORIES_ATTENDUES.includes(c.value) && !presentes.has(c.value)).map(c => c.label);
  }

  libelleMode(mode: ModeAlertePCS): string {
    return MODES_ALERTE_PCS.find(m => m.value === mode)?.label ?? mode;
  }

  ouvrirAjout(categorie?: CategorieInterlocuteurPCS): void {
    this.saisie = { ...this.saisieVide(), ...(categorie ? { categorie } : {}) };
    this.enModification = null;
    this.formulaireOuvert = true;
  }

  modifier(fiche: InterlocuteurAlertePCS): void {
    this.saisie = {
      categorie: fiche.categorie, nom: fiche.nom, organisme: fiche.organisme || '',
      telephone: fiche.telephone || '', email: fiche.email || '', mode_alerte: fiche.mode_alerte,
    };
    this.enModification = fiche.id;
    this.formulaireOuvert = true;
  }

  enregistrer(): void {
    if (!this.saisie.nom.trim()) { this.erreur = 'Indiquez au moins un nom.'; return; }
    this.enregistrement = true;
    this.erreur = '';
    const donnees = {
      ...this.saisie, nom: this.saisie.nom.trim(),
      telephone: this.saisie.telephone.trim() || null, email: this.saisie.email.trim() || null,
    };
    const appel = this.enModification ? this.service.update(this.enModification, donnees) : this.service.create(donnees);
    appel.subscribe({
      next: () => { this.enregistrement = false; this.formulaireOuvert = false; this.charger(); },
      error: (e) => {
        this.enregistrement = false;
        const detail = e?.error && typeof e.error === 'object' ? Object.values(e.error).flat().join(' ') : '';
        this.erreur = detail || "L'enregistrement a échoué.";
      },
    });
  }

  /** Retire le contact de l'annuaire de CETTE commune. La fiche est partagée : une autre commune
   * du département peut l'avoir rattachée, elle n'est donc jamais supprimée d'ici. */
  retirer(fiche: InterlocuteurAlertePCS): void {
    if (!confirm(`Retirer « ${fiche.nom} » de l'annuaire de crise de la commune ?`)) return;
    this.service.detacher(fiche.id).subscribe({ next: () => this.charger(), error: () => { this.erreur = 'Le retrait a échoué.'; } });
  }
}
