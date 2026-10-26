import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ImportApercu, ImportResultat, ImportService, SaisiePersonne } from '../../services/import.service';

const CHAMPS = ['prenom', 'nom', 'email', 'telephone', 'fonction'] as const;
type Champ = typeof CHAMPS[number];

const LABELS: Record<Champ, string> = {
  prenom: 'Prénom',
  nom: 'Nom',
  email: 'Email',
  telephone: 'Téléphone',
  fonction: 'Fonction',
};

const CHAMPS_OBLIGATOIRES: Champ[] = ['nom', 'email'];

/** En-têtes reconnues pour chaque champ cible, dans l'ordre de préférence. Liste explicite
 * plutôt qu'un `includes()` sur le nom du champ : « Prénom » normalisé contient « nom », donc
 * la colonne Prénom était pré-sélectionnée pour le champ Nom — tout le monde se retrouvait
 * importé avec son prénom en guise de nom de famille s'il ne corrigeait pas à la main. */
const SYNONYMES: Record<Champ, string[]> = {
  prenom: ['prenom', 'firstname', 'first name', 'first_name'],
  nom: ['nom de famille', 'nom', 'lastname', 'last name', 'last_name', 'patronyme'],
  email: ['email', 'e-mail', 'mail', 'courriel', 'adresse mail'],
  telephone: ['telephone', 'tel', 'portable', 'mobile', 'phone'],
  fonction: ['fonction', 'poste', 'role', 'qualite', 'titre'],
};

type Etape = 'selection' | 'correspondance' | 'resultat';

/** Une ligne du tableau de saisie à la main. */
interface LigneSaisie {
  prenom: string;
  nom: string;
  email: string;
  telephone: string;
  fonction: string;
  inviter: boolean;
}

@Component({
  selector: 'app-import-personnel',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './import-personnel.component.html',
  styleUrls: ['./import-personnel.component.scss'],
})
export class ImportPersonnelComponent {
  readonly champs = CHAMPS;
  readonly labels = LABELS;
  readonly champsObligatoires = CHAMPS_OBLIGATOIRES;

  etape: Etape = 'selection';
  fichier: File | null = null;
  apercu: ImportApercu | null = null;
  mapping: Record<Champ, string> = { prenom: '', nom: '', email: '', telephone: '', fonction: '' };
  resultat: ImportResultat | null = null;

  isLoading = false;
  errorMessage = '';

  constructor(private importService: ImportService) {}

  telechargerExemple(): void {
    this.importService.telechargerExemplePersonnelCommunal().subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'exemple-personnel-communal.csv';
        a.click();
        URL.revokeObjectURL(url);
      },
      error: () => { this.errorMessage = "Impossible de télécharger le fichier d'exemple."; },
    });
  }

  onFichierChoisi(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.fichier = input.files?.[0] ?? null;
  }

  analyserFichier(): void {
    if (!this.fichier) return;
    this.isLoading = true;
    this.errorMessage = '';
    this.importService.apercu(this.fichier).subscribe({
      next: (apercu) => {
        this.apercu = apercu;
        this.preselectionnerColonnes();
        this.etape = 'correspondance';
        this.isLoading = false;
      },
      error: (err) => {
        this.errorMessage = err?.error?.error || 'Impossible de lire ce fichier.';
        this.isLoading = false;
      },
    });
  }

  // Pré-sélectionne une colonne dont le nom ressemble au champ cible (ex: "E-mail" -> email),
  // pour éviter à l'utilisateur de tout mapper à la main quand les en-têtes sont déjà explicites
  // — reste modifiable ensuite, jamais imposé. Une colonne déjà retenue pour un champ n'est
  // jamais reproposée pour un autre : sinon « Prénom » servait à la fois de prénom et de nom.
  private preselectionnerColonnes(): void {
    if (!this.apercu) return;
    const normalise = (s: string) => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim();
    const dejaPrises = new Set<string>();
    // Dans l'ordre de SYNONYMES : un synonyme exact d'abord, un simple début de nom ensuite.
    for (const champ of CHAMPS) {
      const candidats = SYNONYMES[champ];
      const trouve =
        this.apercu.colonnes.find(c => !dejaPrises.has(c) && candidats.includes(normalise(c)))
        ?? this.apercu.colonnes.find(c => !dejaPrises.has(c) && candidats.some(syn => normalise(c).startsWith(syn)));
      if (trouve) {
        this.mapping[champ] = trouve;
        dejaPrises.add(trouve);
      }
    }
  }

  // ══ Saisie à la main ═══════════════════════════════════════════════════════
  // Pour deux ou trois agents, fabriquer un CSV n'a pas de sens : un « + » ajoute une ligne
  // vide à compléter directement (demande Nicolas Larvor du 26/10/2026). Mêmes champs et
  // mêmes comptes créés que l'import de fichier — c'est le même endpoint côté métier.

  lignesSaisie: LigneSaisie[] = [];
  saisieEnCours = false;
  saisieErreur = '';
  resultatSaisie: ImportResultat | null = null;

  ajouterLigne(): void {
    this.lignesSaisie = [
      ...this.lignesSaisie,
      { prenom: '', nom: '', email: '', telephone: '', fonction: '', inviter: true },
    ];
    this.resultatSaisie = null;
  }

  retirerLigne(ligne: LigneSaisie): void {
    this.lignesSaisie = this.lignesSaisie.filter(l => l !== ligne);
  }

  /** Une ligne entièrement vide est simplement ignorée (on a cliqué « + » une fois de trop) ;
   * une ligne commencée doit être complète, sinon le serveur la rejetterait ligne par ligne. */
  private get lignesRenseignees(): LigneSaisie[] {
    return this.lignesSaisie.filter(l =>
      !!(l.prenom.trim() || l.nom.trim() || l.email.trim() || l.telephone.trim() || l.fonction.trim()));
  }

  ligneIncomplete(ligne: LigneSaisie): boolean {
    const commencee = !!(ligne.prenom.trim() || ligne.nom.trim() || ligne.email.trim()
      || ligne.telephone.trim() || ligne.fonction.trim());
    return commencee && !(ligne.nom.trim() && this.emailValide(ligne.email));
  }

  private emailValide(email: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
  }

  get saisieValide(): boolean {
    const lignes = this.lignesRenseignees;
    return lignes.length > 0 && !lignes.some(l => this.ligneIncomplete(l));
  }

  enregistrerSaisie(): void {
    if (!this.saisieValide) return;
    const personnes: SaisiePersonne[] = this.lignesRenseignees.map(l => ({
      prenom: l.prenom.trim(), nom: l.nom.trim(), email: l.email.trim(),
      telephone: l.telephone.trim(), fonction: l.fonction.trim(), inviter: l.inviter,
    }));
    this.saisieEnCours = true;
    this.saisieErreur = '';
    this.importService.saisirPersonnelCommunal(personnes).subscribe({
      next: (resultat) => {
        this.resultatSaisie = resultat;
        this.saisieEnCours = false;
        // Les lignes en erreur restent à l'écran pour être corrigées ; les autres partent.
        const enErreur = new Set(resultat.erreurs.map(e => e.ligne));
        const renseignees = this.lignesRenseignees;
        this.lignesSaisie = renseignees.filter((_l, i) => enErreur.has(i + 1));
      },
      error: (err) => {
        this.saisieErreur = err?.error?.error || "Impossible d'enregistrer ces personnes.";
        this.saisieEnCours = false;
      },
    });
  }

  get mappingValide(): boolean {
    return CHAMPS_OBLIGATOIRES.every(champ => !!this.mapping[champ]);
  }

  lancerImport(): void {
    if (!this.fichier || !this.mappingValide) return;
    this.isLoading = true;
    this.errorMessage = '';
    this.importService.importerPersonnelCommunal(this.fichier, this.mapping).subscribe({
      next: (resultat) => {
        this.resultat = resultat;
        this.etape = 'resultat';
        this.isLoading = false;
      },
      error: (err) => {
        this.errorMessage = err?.error?.error || "Erreur lors de l'import.";
        this.isLoading = false;
      },
    });
  }

  recommencer(): void {
    this.etape = 'selection';
    this.fichier = null;
    this.apercu = null;
    this.resultat = null;
    this.errorMessage = '';
    this.mapping = { prenom: '', nom: '', email: '', telephone: '', fonction: '' };
  }
}
