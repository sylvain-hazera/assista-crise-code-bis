import { CommonModule } from '@angular/common';
import { Component, Input, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { DossierPcsService } from '../../services/dossier-pcs.service';
import { RisqueCommunalService, RisqueMajeurTypeService } from '../../services/risque-majeur.service';
import { RisqueCommunal, RisqueMajeurType, SuggestionGeorisques } from '../../shared/models/risque-majeur.model';

/**
 * Paragraphe 1.1 du plan communal de sauvegarde : les risques de la commune.
 *
 * Ces risques se saisissaient déjà, mais au fond de la fiche Institution, côté Administration :
 * un paragraphe du plan sans entrée de menu ne se remplit pas. Même données, mêmes services
 * (`RisqueCommunalService`) — cet écran ne crée rien de nouveau, il met le paragraphe à sa place.
 *
 * Un risque déclaré sert ensuite : on le rattache aux dispositifs qu'il déclenche, et son état
 * des lieux et ses enjeux sont repris tels quels dans le document du plan.
 */
@Component({
  selector: 'app-pcs-risques',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './pcs-risques.component.html',
  styleUrl: '../pcs-annuaire/pcs-paragraphe.scss',
})
export class PcsRisquesComponent implements OnInit {
  /** Renseigné quand la page est affichée DANS la fiche d'une institution (onglet) : on tient
   * alors les risques de cette institution-là, et non de celle de la personne. Une seule
   * implémentation pour les deux endroits — il y en avait deux, sous deux noms (18/11/2026). */
  @Input() institution: string | null = null;
  @Input() nomInstitution = '';
  get integre(): boolean { return !!this.institution; }

  institutionId = '';
  commune = '';
  sansCollectivite = false;
  chargement = true;
  erreur = '';

  risques: RisqueCommunal[] = [];
  types: RisqueMajeurType[] = [];
  suggestions: SuggestionGeorisques[] = [];
  suggestionsErreur = '';
  typeAjoute = '';
  /** Identifiant du risque en cours d'enregistrement, pour griser son seul bouton. */
  enregistrement: string | null = null;
  enregistre: string | null = null;

  constructor(
    private dossier: DossierPcsService,
    private risqueService: RisqueCommunalService,
    private typeService: RisqueMajeurTypeService,
  ) {}

  ngOnInit(): void {
    const suite = (d: { institution: string; commune: { nom: string } }) => {
        this.institutionId = d.institution;
        this.commune = d.commune.nom;
        this.charger();
        this.typeService.getAll().subscribe({ next: (types) => { this.types = types.filter(t => t.actif); }, error: () => {} });
        this.risqueService.suggestionsGeorisques(this.institutionId).subscribe({
          next: ({ suggestions }) => { this.suggestions = suggestions; },
          error: () => { this.suggestionsErreur = 'Géorisques ne répond pas pour cette commune : la saisie reste possible.'; },
        });
    };
    if (this.institution) { suite({ institution: this.institution, commune: { nom: this.nomInstitution } }); return; }
    this.dossier.lire().subscribe({
      next: suite,
      error: (e) => { this.chargement = false; this.sansCollectivite = e?.status === 403; if (!this.sansCollectivite) this.erreur = 'Impossible de lire les risques.'; },
    });
  }

  private charger(): void {
    this.risqueService.getForInstitution(this.institutionId).subscribe({
      next: (risques) => { this.risques = risques.filter(r => r.actif); this.chargement = false; },
      error: () => { this.chargement = false; this.erreur = 'Impossible de lire les risques.'; },
    });
  }

  /** Les risques du catalogue que la commune n'a pas encore déclarés. */
  get typesDisponibles(): RisqueMajeurType[] {
    const declares = new Set(this.risques.map(r => r.risque_type));
    return this.types.filter(t => !declares.has(t.id));
  }

  get suggestionsADeclarer(): SuggestionGeorisques[] {
    return this.suggestions.filter(s => !s.deja_declare);
  }

  declarer(): void {
    if (!this.typeAjoute) return;
    this.risqueService.create({ institution: this.institutionId, risque_type: this.typeAjoute }).subscribe({
      next: () => { this.typeAjoute = ''; this.charger(); },
      error: () => { this.erreur = "Le risque n'a pas pu être déclaré."; },
    });
  }

  /** Réutilise ou crée le type de risque (dédoublonné par le serveur), puis le déclare. */
  accepter(suggestion: SuggestionGeorisques): void {
    this.typeService.create({ nom: suggestion.libelle }).subscribe({
      next: (type) => this.risqueService.create({ institution: this.institutionId, risque_type: type.id }).subscribe({
        next: () => { suggestion.deja_declare = true; this.charger(); },
        error: () => { this.erreur = "Le risque n'a pas pu être déclaré."; },
      }),
      error: () => { this.erreur = "Le risque n'a pas pu être déclaré."; },
    });
  }

  enregistrer(risque: RisqueCommunal): void {
    this.enregistrement = risque.id;
    this.enregistre = null;
    this.risqueService.update(risque.id, { etat_des_lieux: risque.etat_des_lieux, enjeux: risque.enjeux }).subscribe({
      next: () => { this.enregistrement = null; this.enregistre = risque.id; },
      error: () => { this.enregistrement = null; this.erreur = "L'enregistrement a échoué."; },
    });
  }

  retirer(risque: RisqueCommunal): void {
    if (!confirm(`Retirer le risque « ${risque.risque_nom} » du plan de la commune ?`)) return;
    this.risqueService.delete(risque.id).subscribe({ next: () => this.charger(), error: () => { this.erreur = 'Le retrait a échoué.'; } });
  }
}
