import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ImportApercu, ImportResultat, ImportService } from '../../services/import.service';

const CHAMPS = ['nom', 'type', 'description', 'telephone', 'email', 'adresse'] as const;
type Champ = typeof CHAMPS[number];

const LABELS: Record<Champ, string> = {
  nom: 'Nom de l\'institution',
  type: 'Type (libellé exact déjà existant, ex: Mairie)',
  description: 'Description',
  telephone: 'Téléphone',
  email: 'Email',
  adresse: 'Adresse',
};

const CHAMPS_OBLIGATOIRES: Champ[] = ['nom', 'type'];

type Etape = 'selection' | 'correspondance' | 'resultat';

@Component({
  selector: 'app-import-institutions',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './import-institutions.component.html',
  styleUrls: ['./import-institutions.component.scss'],
})
export class ImportInstitutionsComponent {
  readonly champs = CHAMPS;
  readonly labels = LABELS;
  readonly champsObligatoires = CHAMPS_OBLIGATOIRES;

  etape: Etape = 'selection';
  fichier: File | null = null;
  apercu: ImportApercu | null = null;
  mapping: Record<Champ, string> = { nom: '', type: '', description: '', telephone: '', email: '', adresse: '' };
  resultat: ImportResultat | null = null;

  isLoading = false;
  errorMessage = '';

  constructor(private importService: ImportService) {}

  telechargerExemple(): void {
    this.importService.telechargerExempleInstitutions().subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'exemple-institutions.csv';
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

  // Même logique que ImportPersonnelComponent : pré-sélectionne une colonne dont le nom
  // ressemble au champ cible, jamais imposé, reste modifiable.
  private preselectionnerColonnes(): void {
    if (!this.apercu) return;
    const normalise = (s: string) => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    for (const champ of CHAMPS) {
      const trouve = this.apercu.colonnes.find(c => normalise(c).includes(normalise(champ)));
      if (trouve) this.mapping[champ] = trouve;
    }
  }

  get mappingValide(): boolean {
    return CHAMPS_OBLIGATOIRES.every(champ => !!this.mapping[champ]);
  }

  lancerImport(): void {
    if (!this.fichier || !this.mappingValide) return;
    this.isLoading = true;
    this.errorMessage = '';
    this.importService.importerInstitutions(this.fichier, this.mapping).subscribe({
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
    this.mapping = { nom: '', type: '', description: '', telephone: '', email: '', adresse: '' };
  }
}
