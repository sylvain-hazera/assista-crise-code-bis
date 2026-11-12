import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { CrisisService } from '../../services/crisis.service';
import { RelogementService } from '../../services/relogement.service';
import { Crisis } from '../../shared/models/crisis.model';
import {
  DossierRelogement, LIBELLES_STATUT_RELOGEMENT, LIBELLES_TITRE_OCCUPATION,
  LIBELLES_TYPE_SOLUTION, StatutDossierRelogement, SyntheseRelogement, TitreOccupation,
  TypeSolutionRelogement,
} from '../../shared/models/relogement.model';

/** Tri de la liste. Tous portent sur une décision réelle : qui est le plus en danger de se
 * retrouver sans rien, et qui attend depuis le plus longtemps. */
export type TriRelogement = 'urgence' | 'nom' | 'terme' | 'personnes' | 'ouverture';

/** Suivi des familles à reloger après une crise.
 *
 * Pendant de « Logement intervenants », pour les sinistrés. Demande de Sylvain du 12/11/2026.
 *
 * **L'écran est construit autour de trois chiffres, pas autour d'un tableau.** Un suivi de
 * relogement se lit en répondant à « qui n'a rien ce soir ? », « qui sort bientôt ? » et
 * « combien tiennent vraiment ? ». Le tableau sert ensuite à agir ; les bandeaux du haut
 * servent à savoir où regarder, et ils viennent du serveur, calculés sur toute la crise (voir
 * `core/relogement.py`) : un total recompté sur les lignes affichées changerait avec les
 * filtres, et deux personnes annonceraient deux chiffres différents en réunion.
 */
@Component({
  selector: 'app-relogement-familles',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './relogement-familles.component.html',
  styleUrl: './relogement-familles.component.scss',
})
export class RelogementFamillesComponent implements OnInit {
  crises: Crisis[] = [];
  criseChoisie: string | null = null;

  dossiers: DossierRelogement[] = [];
  synthese: SyntheseRelogement | null = null;

  chargement = true;
  erreur = '';
  message = '';

  // ── Recherche, filtres et tri ──────────────────────────────────────────────
  recherche = '';
  tri: TriRelogement = 'urgence';
  filtreStatut: '' | StatutDossierRelogement = '';
  filtreTypeSolution: '' | TypeSolutionRelogement = '';
  filtreSansSolution = false;
  filtreTermeProche = false;
  filtreVulnerables = false;
  filtreAnimaux = false;
  filtrePmr = false;

  // ── Fiches dépliées ────────────────────────────────────────────────────────
  detailsOuverts = new Set<string>();

  // ── Saisie ─────────────────────────────────────────────────────────────────
  formulaireOuvert = false;
  nouveauDossier = this.dossierVierge();
  dossierSolution: DossierRelogement | null = null;
  nouvelleSolution = this.solutionVierge();
  enregistrement = false;

  readonly LIBELLES_STATUT = LIBELLES_STATUT_RELOGEMENT;
  readonly LIBELLES_TYPE = LIBELLES_TYPE_SOLUTION;
  readonly LIBELLES_TITRE = LIBELLES_TITRE_OCCUPATION;
  readonly STATUTS = Object.keys(LIBELLES_STATUT_RELOGEMENT) as StatutDossierRelogement[];
  readonly TYPES = Object.keys(LIBELLES_TYPE_SOLUTION) as TypeSolutionRelogement[];
  readonly TITRES = Object.keys(LIBELLES_TITRE_OCCUPATION) as TitreOccupation[];

  constructor(
    private crisisService: CrisisService,
    private relogementService: RelogementService,
  ) {}

  ngOnInit(): void {
    this.crisisService.getAll().subscribe({
      next: (liste) => {
        this.crises = (liste ?? []).filter(c => c.is_open !== false);
        this.criseChoisie = this.crises[0]?.id ?? null;
        this.chargement = false;
        if (this.criseChoisie) { this.charger(); }
      },
      error: () => {
        this.erreur = 'Impossible de charger les crises.';
        this.chargement = false;
      },
    });
  }

  changerCrise(): void {
    this.dossiers = [];
    this.synthese = null;
    this.detailsOuverts.clear();
    this.charger();
  }

  charger(): void {
    if (!this.criseChoisie) { return; }
    const crise = this.criseChoisie;
    this.chargement = true;
    this.relogementService.getAll(crise).subscribe({
      next: (liste) => { this.dossiers = liste ?? []; this.chargement = false; },
      error: () => {
        this.erreur = 'Impossible de charger les dossiers de relogement.';
        this.chargement = false;
      },
    });
    this.relogementService.synthese(crise).subscribe({
      // Silencieuse : sans dossier sur la crise le serveur répond 404, et ce n'est pas une
      // erreur à afficher — c'est une page vide, que l'écran sait dire autrement.
      next: (s) => this.synthese = s,
      error: () => this.synthese = null,
    });
  }

  // ══ Liste ═════════════════════════════════════════════════════════════════

  get dossiersAffiches(): DossierRelogement[] {
    const texte = this.recherche.trim().toLowerCase();
    const filtres = this.dossiers.filter(d => {
      if (this.filtreStatut && d.statut !== this.filtreStatut) { return false; }
      if (this.filtreSansSolution && d.solution_courante) { return false; }
      if (this.filtreVulnerables && !d.personnes_vulnerables) { return false; }
      if (this.filtreAnimaux && !d.animaux) { return false; }
      if (this.filtrePmr && !d.besoin_pmr) { return false; }
      if (this.filtreTypeSolution
          && d.solution_courante?.type_solution !== this.filtreTypeSolution) { return false; }
      if (this.filtreTermeProche && !this.termeProche(d)) { return false; }
      if (texte && !this.texteDe(d).includes(texte)) { return false; }
      return true;
    });
    return this.trier(filtres);
  }

  /** Tout ce sur quoi la recherche libre porte : on cherche une famille par son nom, sa
   * commune, son hébergeur ou le titre de son occupation, sans choisir un champ d'abord. */
  private texteDe(d: DossierRelogement): string {
    const courante = d.solution_courante;
    return [
      d.nom_referent, d.commune_origine_nom, d.statut_libelle,
      courante?.type_solution_libelle, courante?.titre_occupation_libelle,
      courante?.commune_nom, courante?.hebergeur, courante?.point_nom, courante?.offre_titre,
    ].filter(Boolean).join(' ').toLowerCase();
  }

  private trier(liste: DossierRelogement[]): DossierRelogement[] {
    const copie = [...liste];
    switch (this.tri) {
      case 'nom':
        return copie.sort((a, b) => a.nom_referent.localeCompare(b.nom_referent, 'fr'));
      case 'personnes':
        return copie.sort((a, b) => b.nombre_personnes - a.nombre_personnes);
      case 'ouverture':
        return copie.sort((a, b) => a.date_ouverture.localeCompare(b.date_ouverture));
      case 'terme':
        return copie.sort((a, b) =>
          this.joursRestants(a) - this.joursRestants(b));
      case 'urgence':
      default:
        // L'ordre de l'écran par défaut EST une hiérarchie d'urgence : sans solution d'abord,
        // puis terme dépassé, puis terme proche, puis le reste. Trier par nom par défaut
        // ferait ouvrir la page sur une liste alphabétique où rien ne ressort.
        return copie.sort((a, b) => this.rangUrgence(a) - this.rangUrgence(b)
          || this.joursRestants(a) - this.joursRestants(b));
    }
  }

  private rangUrgence(d: DossierRelogement): number {
    if (!d.solution_courante) {
      return d.statut === 'CLOS_SANS_SUITE' || d.statut === 'RETOUR_DOMICILE' ? 4 : 0;
    }
    const jours = d.solution_courante.jours_restants;
    if (jours != null && jours < 0) { return 1; }
    if (jours != null && jours <= (this.synthese?.jours_alerte_terme ?? 30)) { return 2; }
    return 3;
  }

  /** Jours avant le terme, ou l'infini quand il n'y en a pas : un hébergement sans terme ne
   * doit pas remonter devant celui qui finit la semaine prochaine. */
  joursRestants(d: DossierRelogement): number {
    const jours = d.solution_courante?.jours_restants;
    return jours == null ? Number.MAX_SAFE_INTEGER : jours;
  }

  termeProche(d: DossierRelogement): boolean {
    const jours = d.solution_courante?.jours_restants;
    return jours != null && jours <= (this.synthese?.jours_alerte_terme ?? 30);
  }

  termeDepasse(d: DossierRelogement): boolean {
    const jours = d.solution_courante?.jours_restants;
    return jours != null && jours < 0;
  }

  viderFiltres(): void {
    this.recherche = '';
    this.filtreStatut = '';
    this.filtreTypeSolution = '';
    this.filtreSansSolution = false;
    this.filtreTermeProche = false;
    this.filtreVulnerables = false;
    this.filtreAnimaux = false;
    this.filtrePmr = false;
  }

  basculerDetail(id: string): void {
    if (this.detailsOuverts.has(id)) { this.detailsOuverts.delete(id); }
    else { this.detailsOuverts.add(id); }
  }

  detailOuvert(id: string): boolean {
    return this.detailsOuverts.has(id);
  }

  // ══ Saisie ════════════════════════════════════════════════════════════════

  private dossierVierge(): Partial<DossierRelogement> {
    return {
      nom_referent: '', telephone_referent: '', email_referent: '',
      nombre_adultes: 1, nombre_enfants: 0, personnes_vulnerables: false,
      animaux: false, besoin_pmr: false, commune_origine_nom: '', accompagnement: '',
    };
  }

  private solutionVierge(): Record<string, unknown> {
    return {
      type_solution: 'URGENCE', titre_occupation: 'CENTRE',
      date_debut: new Date().toISOString().slice(0, 10),
      date_fin_prevue: '', adresse: '', commune_nom: '', hebergeur: '',
      hebergeur_contact: '', loyer_mensuel: null, reste_a_charge: null,
      prise_en_charge_par: '', commentaire: '',
    };
  }

  ouvrirFormulaire(): void {
    this.nouveauDossier = this.dossierVierge();
    this.formulaireOuvert = true;
  }

  fermerFormulaire(): void {
    this.formulaireOuvert = false;
  }

  creer(): void {
    if (!this.criseChoisie || !(this.nouveauDossier.nom_referent || '').trim()) { return; }
    this.enregistrement = true;
    this.relogementService.creer({
      ...this.nouveauDossier, crise: this.criseChoisie,
    }).subscribe({
      next: () => {
        this.enregistrement = false;
        this.formulaireOuvert = false;
        this.message = 'Dossier de relogement ouvert.';
        this.erreur = '';
        this.charger();
      },
      error: (err) => {
        this.enregistrement = false;
        this.erreur = err?.error?.error || "Impossible d'ouvrir ce dossier.";
      },
    });
  }

  ouvrirSolution(dossier: DossierRelogement): void {
    this.dossierSolution = dossier;
    this.nouvelleSolution = this.solutionVierge();
  }

  fermerSolution(): void {
    this.dossierSolution = null;
  }

  enregistrerSolution(): void {
    if (!this.dossierSolution) { return; }
    this.enregistrement = true;
    // Les champs vides partent absents plutôt que vides : une date vide ferait une erreur de
    // validation, et un loyer à zéro n'est pas « pas de loyer renseigné ».
    const corps: Record<string, unknown> = {};
    for (const [cle, valeur] of Object.entries(this.nouvelleSolution)) {
      if (valeur !== '' && valeur !== null && valeur !== undefined) { corps[cle] = valeur; }
    }
    this.relogementService.ajouterSolution(this.dossierSolution.id, corps).subscribe({
      next: () => {
        this.enregistrement = false;
        this.dossierSolution = null;
        this.message = 'Hébergement enregistré.';
        this.erreur = '';
        this.charger();
      },
      error: (err) => {
        this.enregistrement = false;
        this.erreur = err?.error?.error || "Impossible d'enregistrer cet hébergement.";
      },
    });
  }

  cloturer(dossier: DossierRelogement): void {
    this.relogementService.cloturerSolution(dossier.id).subscribe({
      next: () => { this.message = 'Hébergement clos.'; this.charger(); },
      error: (err) => this.erreur = err?.error?.error || "Impossible de clore cet hébergement.",
    });
  }

  // ══ Bilan ═════════════════════════════════════════════════════════════════

  /** Le bilan en texte, prêt à coller dans un point de situation. Même source que les
   * bandeaux : un rapport qui diverge de l'écran ne vaut rien. */
  get bilanTexte(): string {
    const s = this.synthese;
    if (!s) { return ''; }
    const lignes = [
      `Relogement — ${s.crise_nom} — situation au ${this.dateFr(s.date_arrete)}`,
      `${s.foyers} foyer(s) suivi(s), soit ${s.personnes} personne(s) `
        + `(${s.adultes} adulte(s), ${s.enfants} enfant(s)).`,
      `${s.relogees_durablement} foyer(s) relogé(s) durablement.`,
      `${s.sans_solution} foyer(s) sans solution d'hébergement.`,
      `${s.arrivent_a_terme} hébergement(s) arrivent à leur terme sous `
        + `${s.jours_alerte_terme} jours.`,
      `${s.termes_depasses} hébergement(s) dont le terme est dépassé sans sortie enregistrée.`,
      `${s.foyers_avec_personnes_vulnerables} foyer(s) comportent une personne vulnérable.`,
    ];
    return lignes.join('\n');
  }

  private dateFr(iso: string): string {
    return new Date(iso + 'T00:00:00').toLocaleDateString('fr-FR');
  }

  copierBilan(): void {
    const texte = this.bilanTexte;
    if (!texte) { return; }
    navigator.clipboard?.writeText(texte).then(
      () => this.message = 'Bilan copié.',
      () => this.erreur = 'Copie impossible : sélectionnez le texte à la main.',
    );
  }
}
