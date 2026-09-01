import { Component, EventEmitter, Input, Output, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';

interface PickedPhoto {
  file: File;
  url: string;
  principale: boolean;
}

/**
 * Sélecteur de galerie photo (jusqu'à `maxFiles`, 10 par défaut) mutualisé entre les
 * formulaires publics d'offre et de demande d'aide — remplace le simple `<input type=file>`
 * mono-photo dupliqué dans chacun. Une des photos sélectionnées est désignée "principale"
 * (la première ajoutée par défaut, mais l'utilisateur peut en choisir une autre) : elle est
 * toujours renvoyée en tête du tableau émis par `selectionChanged`, pour que l'appelant puisse
 * l'envoyer telle quelle dans le champ `photo` existant de l'offre/demande (inchangé), et
 * poster les suivantes séparément vers la galerie (OfferPhoto/RequestPhoto).
 */
@Component({
  selector: 'app-photo-gallery-picker',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './photo-gallery-picker.component.html',
  styleUrl: './photo-gallery-picker.component.scss',
})
export class PhotoGalleryPickerComponent implements OnDestroy {
  @Input() maxFiles = 10;
  @Output() selectionChanged = new EventEmitter<File[]>();

  photos: PickedPhoto[] = [];
  errorMessage = '';

  private static readonly VALID_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif'];
  private static readonly MAX_SIZE = 5 * 1024 * 1024;

  onFilesSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = input.files ? Array.from(input.files) : [];
    input.value = ''; // permet de resélectionner le même fichier plus tard si retiré

    this.errorMessage = '';
    for (const file of files) {
      if (this.photos.length >= this.maxFiles) {
        this.errorMessage = `Maximum ${this.maxFiles} photos.`;
        break;
      }
      if (!PhotoGalleryPickerComponent.VALID_TYPES.includes(file.type)) {
        this.errorMessage = 'Veuillez sélectionner des images valides (JPEG, PNG, GIF).';
        continue;
      }
      if (file.size > PhotoGalleryPickerComponent.MAX_SIZE) {
        this.errorMessage = "Une image ne doit pas dépasser 5MB.";
        continue;
      }
      this.photos.push({
        file,
        url: URL.createObjectURL(file),
        principale: this.photos.length === 0, // la toute première ajoutée devient principale par défaut
      });
    }
    this.emitSelection();
  }

  setPrincipale(index: number): void {
    this.photos.forEach((p, i) => p.principale = i === index);
    this.emitSelection();
  }

  remove(index: number): void {
    const wasPrincipale = this.photos[index].principale;
    URL.revokeObjectURL(this.photos[index].url);
    this.photos.splice(index, 1);
    if (wasPrincipale && this.photos.length > 0) {
      this.photos[0].principale = true;
    }
    this.emitSelection();
  }

  private emitSelection(): void {
    const principale = this.photos.find(p => p.principale);
    const autres = this.photos.filter(p => !p.principale);
    const ordered = principale ? [principale, ...autres] : autres;
    this.selectionChanged.emit(ordered.map(p => p.file));
  }

  ngOnDestroy(): void {
    this.photos.forEach(p => URL.revokeObjectURL(p.url));
  }
}
