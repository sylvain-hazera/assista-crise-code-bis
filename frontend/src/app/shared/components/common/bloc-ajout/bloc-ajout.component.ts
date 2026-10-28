import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { RouterLink } from '@angular/router';

/** Un champ du formulaire d'invitation, déclaré par la page hôte.
 *
 * Déclaratif plutôt qu'un `switch` sur la destination : inviter une institution demande un nom
 * et un type, inviter un contact une fonction. Un composant qui connaîtrait les deux cas
 * devrait connaître le troisième, puis le quatrième. */
export interface ChampInvitation {
  cle: string;
  label: string;
  type?: 'text' | 'email' | 'select';
  requis?: boolean;
  placeholder?: string;
  aide?: string;
  options?: { valeur: string; libelle: string }[];
}

interface ResultatImport {
  crees?: number;
  rattaches?: number;
  erreurs?: { ligne: number; message: string }[];
}

/**
 * Les trois gestes d'ajout, au même endroit et toujours les mêmes : **à la main**, **par
 * fichier**, **par invitation**.
 *
 * Avant ce composant (28/10/2026), les trois existaient mais dispersés : le `+` sur la page, le
 * fichier sur une page d'assistant séparée absente du menu et atteignable par un seul lien
 * contextuel, et l'invitation sur deux destinations seulement — aucune destination n'avait les
 * trois. Inviter une institution n'existait même pas, de sorte qu'une mairie voisine était
 * TOUJOURS saisie par un tiers, qui ne connaît ni son type ni son référent : c'est ce qui
 * fabriquait les doublons.
 *
 * Trois partis pris :
 *
 * - **Le `+` n'ouvre rien ici**, il émet `ajoutManuel`. Les formulaires de saisie sont très
 *   différents d'une destination à l'autre (une institution a un type et une commune, un
 *   contact une fonction) et les pages en ont déjà de bons ; les absorber ici aurait produit un
 *   formulaire générique moins bon que chacun des sept qu'il remplacerait.
 * - **L'import se fait sans étape de correspondance** quand les en-têtes du fichier sont
 *   reconnues (voir `imports.mapping_depuis_entetes` côté serveur), ce qui est le cas si on a
 *   téléchargé le modèle. L'assistant en deux étapes reste là, en recours, et le refus du
 *   serveur y renvoie explicitement : c'est lui qui nomme les colonnes non reconnues.
 * - **Le modèle se télécharge avant** le sélecteur de fichier, dans cet ordre à l'écran. Un
 *   bouton d'envoi présenté en premier fait envoyer le fichier qu'on a déjà, dans son format à
 *   soi, et l'import échoue ; proposer d'abord le modèle est ce qui évite l'échec.
 */
@Component({
  selector: 'app-bloc-ajout',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './bloc-ajout.component.html',
  styleUrl: './bloc-ajout.component.scss',
})
export class BlocAjoutComponent {
  /** Ce qu'on ajoute, au singulier et avec son article : « une institution », « un contact ». */
  @Input({ required: true }) quoi = '';

  /** Libellé du bouton de saisie manuelle. Par défaut « Ajouter <quoi> ». */
  @Input() libelleManuel = '';

  @Input() urlExemple?: string;
  @Input() nomFichierExemple = 'modele.csv';
  @Input() urlImport?: string;
  /** Champs postés avec le fichier (ex: `{institution: '<uuid>'}`, `{point_id: '<uuid>'}`). */
  @Input() champsImportSupplementaires: Record<string, string> = {};
  /** Assistant de correspondance, en recours quand les en-têtes ne sont pas reconnues. */
  @Input() routeAssistant?: string;
  @Input() parametresAssistant: Record<string, string> = {};

  @Input() urlInvitation?: string;
  @Input() champsInvitation: ChampInvitation[] = [];
  @Input() champsInvitationSupplementaires: Record<string, string> = {};
  /** Phrase expliquant ce que recevra le destinataire — propre à chaque destination. */
  @Input() aideInvitation = '';

  /** Pourquoi un geste n'est pas proposé ici, le cas échéant. Affiché tel quel : **dire qu'un
   * geste ne s'applique pas vaut mieux que le laisser manquer**, sinon on cherche un bouton qui
   * n'existe pas et on conclut que la page est incomplète. Les deux cas réels aujourd'hui : un
   * interlocuteur PCS est un service extérieur qu'on prévient et non un compte à créer ; les
   * membres d'une équipe se composent depuis l'annuaire, où l'import a déjà eu lieu. */
  @Input() invitationImpossible = '';
  @Input() importImpossible = '';

  @Output() ajoutManuel = new EventEmitter<void>();
  /** Quelque chose a été créé : la page hôte recharge sa liste. */
  @Output() ajoute = new EventEmitter<void>();

  panneau: 'aucun' | 'csv' | 'invitation' = 'aucun';

  fichier: File | null = null;
  enCours = false;
  errorMessage = '';
  successMessage = '';
  /** Vrai quand le refus vient d'en-têtes non reconnues : on propose alors l'assistant. */
  mappingAFaire = false;
  resultat: ResultatImport | null = null;

  invitation: Record<string, string> = {};

  constructor(private http: HttpClient) {}

  get libelleBoutonManuel(): string {
    return this.libelleManuel || `Ajouter ${this.quoi}`;
  }

  ouvrir(panneau: 'csv' | 'invitation'): void {
    this.panneau = this.panneau === panneau ? 'aucun' : panneau;
    this.reinitialiser();
  }

  private reinitialiser(): void {
    this.fichier = null;
    this.errorMessage = '';
    this.successMessage = '';
    this.mappingAFaire = false;
    this.resultat = null;
    this.invitation = {};
  }

  // ── Fichier ────────────────────────────────────────────────────────────────

  telechargerModele(): void {
    if (!this.urlExemple) return;
    this.errorMessage = '';
    this.http.get(this.urlExemple, { responseType: 'blob' }).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const lien = document.createElement('a');
        lien.href = url;
        lien.download = this.nomFichierExemple;
        lien.click();
        URL.revokeObjectURL(url);
      },
      error: () => this.errorMessage = "Impossible de télécharger le modèle.",
    });
  }

  onFichierChoisi(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.fichier = input.files?.[0] ?? null;
    this.errorMessage = '';
    this.mappingAFaire = false;
    this.resultat = null;
  }

  importer(): void {
    if (!this.fichier || !this.urlImport || this.enCours) return;
    this.enCours = true;
    this.errorMessage = '';
    this.successMessage = '';
    this.mappingAFaire = false;

    const fd = new FormData();
    fd.append('fichier', this.fichier);
    Object.entries(this.champsImportSupplementaires).forEach(([cle, valeur]) => {
      if (valeur) fd.append(cle, valeur);
    });

    this.http.post<ResultatImport>(this.urlImport, fd).subscribe({
      next: (resultat) => {
        this.enCours = false;
        this.resultat = resultat;
        const crees = resultat.crees ?? 0;
        const rattaches = resultat.rattaches ?? 0;
        this.successMessage = `${crees} créé(s)`
          + (rattaches ? `, ${rattaches} rattaché(s)` : '')
          + (resultat.erreurs?.length ? `, ${resultat.erreurs.length} ligne(s) en erreur` : '.');
        this.fichier = null;
        this.ajoute.emit();
      },
      error: (err) => {
        this.enCours = false;
        const message = err?.error?.error || err?.error?.detail
          || "L'import a échoué.";
        this.errorMessage = message;
        // Le serveur nomme les colonnes non reconnues : c'est exactement le cas où
        // l'assistant de correspondance sert à quelque chose.
        this.mappingAFaire = /non reconnue/i.test(String(message)) && !!this.routeAssistant;
      },
    });
  }

  // ── Invitation ─────────────────────────────────────────────────────────────

  get invitationValide(): boolean {
    return this.champsInvitation
      .filter(c => c.requis)
      .every(c => (this.invitation[c.cle] || '').trim().length > 0);
  }

  inviter(): void {
    if (!this.urlInvitation || !this.invitationValide || this.enCours) return;
    this.enCours = true;
    this.errorMessage = '';
    this.successMessage = '';

    const corps: Record<string, string> = { ...this.champsInvitationSupplementaires };
    this.champsInvitation.forEach(champ => {
      const valeur = (this.invitation[champ.cle] || '').trim();
      if (valeur) corps[champ.cle] = valeur;
    });

    this.http.post<{ detail?: string }>(this.urlInvitation, corps).subscribe({
      next: (reponse) => {
        this.enCours = false;
        this.successMessage = reponse?.detail || 'Invitation envoyée.';
        this.invitation = {};
        this.ajoute.emit();
      },
      error: (err) => {
        this.enCours = false;
        this.errorMessage = err?.error?.error || err?.error?.detail
          || "L'invitation n'a pas pu être envoyée.";
      },
    });
  }
}
