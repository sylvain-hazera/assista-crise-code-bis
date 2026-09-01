import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { DossierService } from '../../services/dossier.service';
import { DossierCommentaireService } from '../../services/dossier-commentaire.service';
import { DocumentService } from '../../services/document.service';
import { Dossier } from '../../shared/models/dossier.model';
import { DossierCommentaire } from '../../shared/models/dossier-commentaire.model';
import { DossierDocument } from '../../shared/models/dossier-document.model';

const STATUT_LABELS: Record<string, string> = {
  EN_ATTENTE_DISTRIBUTION: 'En attente de prise en charge',
  NOUVEAU: 'Pris en compte',
  EN_ATTENTE_AFFECTATION: "En attente d'affectation",
  AFFECTE: 'Affecté à une équipe',
  EN_COURS: 'En cours',
  RESOLU: 'En attente de clôture',
  CLOTURE: 'Terminé',
};

const MAX_PHOTO_SIZE = 5 * 1024 * 1024;
const VALID_PHOTO_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'];

@Component({
  selector: 'app-dossier-suivi',
  standalone: true,
  imports: [CommonModule, FormsModule, DatePipe],
  templateUrl: './dossier-suivi.component.html',
  styleUrls: ['./dossier-suivi.component.scss']
})
export class DossierSuiviComponent implements OnInit, OnDestroy {

  dossier: Dossier | null = null;
  commentaires: DossierCommentaire[] = [];
  documents: DossierDocument[] = [];
  previews: Record<string, string> = {};

  loading = true;
  notFound = false;
  nouveauCommentaire = '';
  sendingCommentaire = false;
  uploadingPhoto = false;
  uploadError = '';
  markingImportant = false;

  private dossierId = '';

  constructor(
    private route: ActivatedRoute,
    private dossierService: DossierService,
    private commentaireService: DossierCommentaireService,
    private documentService: DocumentService
  ) {}

  ngOnInit(): void {
    this.dossierId = this.route.snapshot.paramMap.get('id') || '';
    if (!this.dossierId) {
      this.notFound = true;
      this.loading = false;
      return;
    }
    this.load();
    this.dossierService.markViewed(this.dossierId).subscribe();
  }

  ngOnDestroy(): void {
    Object.values(this.previews).forEach(url => URL.revokeObjectURL(url));
  }

  statutLabel(statut: string): string {
    return STATUT_LABELS[statut] || statut;
  }

  private load(): void {
    this.loading = true;

    this.dossierService.getById(this.dossierId).subscribe({
      next: dossier => {
        this.dossier = dossier;
        this.loading = false;
      },
      error: () => {
        this.notFound = true;
        this.loading = false;
      }
    });

    this.commentaireService.getAll().subscribe(data => {
      this.commentaires = data
        .filter(c => c.dossier === this.dossierId)
        .sort((a, b) => a.date_creation.localeCompare(b.date_creation));
    });

    this.documentService.getAll().subscribe(data => {
      this.documents = data.filter(d => d.dossier === this.dossierId);
      this.documents.forEach(d => this.loadPreview(d));
    });
  }

  private loadPreview(doc: DossierDocument): void {
    if (this.previews[doc.id]) {
      return;
    }
    this.documentService.preview(doc.id).subscribe({
      next: blob => {
        this.previews[doc.id] = URL.createObjectURL(blob);
      },
      error: () => {}
    });
  }

  marquerImportant(): void {
    if (!this.dossierId || this.markingImportant) {
      return;
    }
    this.markingImportant = true;
    this.dossierService.marquerImportant(this.dossierId).subscribe({
      next: dossier => {
        this.dossier = dossier;
        this.markingImportant = false;
      },
      error: () => {
        this.markingImportant = false;
      }
    });
  }

  addCommentaire(): void {
    const texte = this.nouveauCommentaire.trim();
    if (!texte || !this.dossierId) {
      return;
    }
    this.sendingCommentaire = true;
    this.commentaireService.create({ dossier: this.dossierId, commentaire: texte }).subscribe({
      next: commentaire => {
        this.commentaires = [...this.commentaires, commentaire];
        this.nouveauCommentaire = '';
        this.sendingCommentaire = false;
      },
      error: () => {
        this.sendingCommentaire = false;
      }
    });
  }

  onCameraPhotoSelected(event: Event): void {
    this.handleFileSelected(event);
  }

  onGalleryPhotoSelected(event: Event): void {
    this.handleFileSelected(event);
  }

  private handleFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files && input.files[0];
    input.value = '';

    if (!file) {
      return;
    }

    if (!VALID_PHOTO_TYPES.includes(file.type)) {
      this.uploadError = 'Veuillez sélectionner une image valide (JPEG, PNG, GIF, WEBP).';
      return;
    }

    if (file.size > MAX_PHOTO_SIZE) {
      this.uploadError = "L'image ne doit pas dépasser 5 Mo.";
      return;
    }

    this.uploadError = '';
    this.uploadPhoto(file);
  }

  private uploadPhoto(file: File): void {
    if (!this.dossierId) {
      return;
    }
    this.uploadingPhoto = true;

    const formData = new FormData();
    formData.append('fichier', file);
    formData.append('dossier', this.dossierId);
    formData.append('commentaire', '');

    this.documentService.create(formData).subscribe({
      next: doc => {
        this.documents = [...this.documents, doc];
        this.loadPreview(doc);
        this.uploadingPhoto = false;
      },
      error: () => {
        this.uploadError = "L'envoi de la photo a échoué, merci de réessayer.";
        this.uploadingPhoto = false;
      }
    });
  }
}
