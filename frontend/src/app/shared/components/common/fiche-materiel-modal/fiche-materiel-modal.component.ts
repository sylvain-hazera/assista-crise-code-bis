import { Component, EventEmitter, Input, OnChanges, OnDestroy, Output, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { OfferService } from '../../../../services/offer.service';
import { DocumentService } from '../../../../services/document.service';
import { FicheMaterielService } from '../../../../services/fiche-materiel.service';
import { FicheMateriel, EtatMateriel } from '../../../models/fiche-materiel.model';
import { DossierDocument } from '../../../models/dossier-document.model';

/** Fiche détaillée d'une offre de matériel (24/09, pendant matériel de la fiche intervenant) :
 * infos + photos de la source, propriétaire, état/maintenance (nouveau -- rien de tel n'existait
 * avant), documents (facture réparateur, photo de la panne...), historique d'activité.
 * Photos/documents réutilisent tels quels les endpoints déjà existants (OfferViewSet.preview,
 * OfferPhotoViewSet, DocumentViewSet, tous déjà génériques) -- pas de nouveau mécanisme
 * d'upload/preview, juste les services déjà là. */
import { TelephonePipe } from '../../../../shared/pipes/telephone.pipe';

@Component({
  selector: 'app-fiche-materiel-modal',
  standalone: true,
  imports: [TelephonePipe, CommonModule, FormsModule],
  templateUrl: './fiche-materiel-modal.component.html',
  styleUrl: './fiche-materiel-modal.component.scss',
})
export class FicheMaterielModalComponent implements OnChanges, OnDestroy {
  @Input({ required: true }) offreId!: string;

  @Output() closed = new EventEmitter<void>();

  fiche: FicheMateriel | null = null;
  documents: DossierDocument[] = [];
  photoUrl: string | null = null;
  galeriePhotos: { id: string; url: string }[] = [];

  chargement = true;
  erreur = '';

  // Nouvel événement de suivi
  ajoutEnCours = false;
  nouvelEtat: EtatMateriel = 'DISPONIBLE';
  nouveauCommentaire = '';
  nouveauReparateurNom = '';
  nouveauReparateurContact = '';
  nouveauLieuReparation = '';
  nouvelleDateReparation = '';
  nouveauCout: number | null = null;

  // Upload document
  fichierAEnvoyer: File | null = null;
  commentaireDocument = '';
  uploadEnCours = false;

  private objectUrls: string[] = [];

  constructor(
    private offerService: OfferService,
    private documentService: DocumentService,
    private ficheMaterielService: FicheMaterielService,
  ) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['offreId'] && this.offreId) this.charger();
  }

  ngOnDestroy(): void {
    this.objectUrls.forEach(u => URL.revokeObjectURL(u));
  }

  private charger(): void {
    this.chargement = true;
    this.erreur = '';
    this.objectUrls.forEach(u => URL.revokeObjectURL(u));
    this.objectUrls = [];
    this.photoUrl = null;
    this.galeriePhotos = [];

    forkJoin({
      fiche: this.ficheMaterielService.get(this.offreId),
      documents: this.documentService.getAll({ offre: this.offreId }).pipe(catchError(() => of([]))),
      photos: this.offerService.getPhotos(this.offreId).pipe(catchError(() => of([]))),
    }).subscribe({
      next: ({ fiche, documents, photos }) => {
        this.fiche = fiche;
        this.documents = documents;
        this.nouvelEtat = fiche.etat_actuel?.etat ?? 'DISPONIBLE';
        this.chargement = false;

        if (fiche.identite.has_photo) {
          this.offerService.preview(this.offreId).subscribe({
            next: (blob) => { this.photoUrl = this.creerObjectUrl(blob); },
            error: () => {},
          });
        }
        for (const p of photos) {
          this.offerService.previewPhoto(p.id).subscribe({
            next: (blob) => { this.galeriePhotos.push({ id: p.id, url: this.creerObjectUrl(blob) }); },
            error: () => {},
          });
        }
      },
      error: () => {
        this.erreur = 'Impossible de charger la fiche de ce matériel.';
        this.chargement = false;
      },
    });
  }

  private creerObjectUrl(blob: Blob): string {
    const url = URL.createObjectURL(blob);
    this.objectUrls.push(url);
    return url;
  }

  ajouterEvenement(): void {
    if (!this.offreId) return;
    this.ajoutEnCours = true;
    this.ficheMaterielService.ajouterEvenement({
      offre: this.offreId,
      etat: this.nouvelEtat,
      commentaire: this.nouveauCommentaire || undefined,
      reparateur_nom: this.nouveauReparateurNom || undefined,
      reparateur_contact: this.nouveauReparateurContact || undefined,
      lieu_reparation: this.nouveauLieuReparation || undefined,
      date_reparation: this.nouvelleDateReparation || undefined,
      cout_reparation: this.nouveauCout ?? undefined,
    }).subscribe({
      next: () => {
        this.ajoutEnCours = false;
        this.nouveauCommentaire = '';
        this.nouveauReparateurNom = '';
        this.nouveauReparateurContact = '';
        this.nouveauLieuReparation = '';
        this.nouvelleDateReparation = '';
        this.nouveauCout = null;
        this.charger();
      },
      error: () => { this.ajoutEnCours = false; this.erreur = "Échec de l'enregistrement."; },
    });
  }

  onFichierChoisi(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.fichierAEnvoyer = input.files?.[0] ?? null;
  }

  envoyerDocument(): void {
    if (!this.fichierAEnvoyer || !this.offreId) return;
    this.uploadEnCours = true;
    const fd = new FormData();
    fd.append('offre', this.offreId);
    fd.append('fichier', this.fichierAEnvoyer);
    if (this.commentaireDocument) fd.append('commentaire', this.commentaireDocument);
    this.documentService.create(fd).subscribe({
      next: (doc) => {
        this.documents = [...this.documents, doc];
        this.fichierAEnvoyer = null;
        this.commentaireDocument = '';
        this.uploadEnCours = false;
      },
      error: () => { this.uploadEnCours = false; this.erreur = "Échec de l'envoi du document."; },
    });
  }

  telechargerDocument(doc: DossierDocument): void {
    this.documentService.preview(doc.id).subscribe(blob => {
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    });
  }
}
