import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { AuthService } from '../../auth/services/auth.service';
import { RecherchePersonneService } from '../../services/recherche-personne.service';
import { RecherchePersonneCommentaireService } from '../../services/recherche-personne-commentaire.service';
import { RecherchePersonneCommentairePhotoService } from '../../services/recherche-personne-commentaire-photo.service';

@Component({
  selector: 'app-recherche-personne-detail',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule
  ],
  templateUrl: './recherche-personne-detail.component.html',
  styleUrls: ['./recherche-personne-detail.component.scss']
})

export class RecherchePersonneDetailComponent
implements OnInit, OnDestroy {

  recherche: any;
  currentUser: any;
  commentaires: any[] = [];
  photosCommentaires: any[] = [];
  photosCommentaire: File[] = [];
  nouveauCommentaire = '';
  mainPhotoUrl: string | null = null;
  photoUrls: Record<string, string> = {};

  constructor(
    private route: ActivatedRoute,
    private authService: AuthService,
    private rechercheService: RecherchePersonneService,
    private commentaireService: RecherchePersonneCommentaireService,
    private commentairePhotoService: RecherchePersonneCommentairePhotoService
  ) {}

  getPhotosCommentaire(
    commentaireId: string
  ): any[] {

    return this.photosCommentaires.filter(
      p => p.commentaire === commentaireId
    );
  }


  ngOnInit(): void {

    const id = this.route.snapshot.paramMap.get('id');

    if (id) {

      this.rechercheService
        .getById(id)
        .subscribe(data => {

          this.recherche = data;

          this.rechercheService
            .lecture(id)
            .subscribe();

          if (data.has_photo) {
            this.rechercheService.preview(id).subscribe({
              next: (blob) => { this.mainPhotoUrl = URL.createObjectURL(blob); },
              error: () => {},
            });
          }

          this.loadCommentaires();
          this.loadPhotosCommentaires();
          this.currentUser =
            this.authService.getCurrentUser();

        });

    }

  }

  loadCommentaires(): void {

    this.commentaireService
      .getAll()
      .subscribe(data => {

        this.commentaires = data.filter(
          c => c.recherche === this.recherche.id
        );

      });

  }

  loadPhotosCommentaires(): void {

    this.commentairePhotoService
      .getAll()
      .subscribe(data => {

        this.photosCommentaires = data;

        data.filter((photo: any) => !this.photoUrls[photo.id]).forEach((photo: any) => {
          this.commentairePhotoService.preview(photo.id).subscribe({
            next: (blob) => { this.photoUrls[photo.id] = URL.createObjectURL(blob); },
            error: () => {},
          });
        });

      });

  }


  onPhotosSelected(
    event: any
  ): void {

    this.photosCommentaire =
      Array.from(
        event.target.files
      ) as File[];

  }


  ajouterCommentaire(): void {

    if (!this.nouveauCommentaire.trim()) {
      return;
    }

    this.commentaireService
      .create({
        recherche: this.recherche.id,
        commentaire: this.nouveauCommentaire
      })
      .subscribe((commentaire: any) => {

        if (
          this.photosCommentaire.length === 0
        ) {

          this.nouveauCommentaire = '';

          this.loadCommentaires();
          this.loadPhotosCommentaires();
          return;

        }

        this.photosCommentaire.forEach(
          photo => {

            const formData =
              new FormData();

            formData.append(
              'commentaire',
              commentaire.id
            );

            formData.append(
              'fichier',
              photo
            );

            this.commentairePhotoService
              .create(formData)
              .subscribe();

          }
        );

        this.nouveauCommentaire = '';

        this.photosCommentaire = [];

        this.loadCommentaires();
        this.loadPhotosCommentaires();
    });

  }


  archiverRecherche(): void {

    if (
      !confirm(
        'Archiver cette recherche ?'
      )
    ) {
      return;
    }

    this.rechercheService
      .archiver(
        this.recherche.id
      )
      .subscribe(() => {

        this.recherche.statut =
          'ARCHIVEE';

      });

  }

  retrouverRecherche(): void {

    if (
      !confirm(
        'Déclarer cette personne retrouvée ?'
      )
    ) {
      return;
    }

    this.rechercheService
      .retrouver(
        this.recherche.id
      )
      .subscribe(() => {

        this.recherche.statut =
          'RETROUVEE';

      });

  }

  acquitter(): void {

    this.rechercheService
      .acquitter(
        this.recherche.id
      )
      .subscribe();

  }

  ouvrirPhoto(
    url: string
  ): void {

    window.open(
      url,
      '_blank'
    );

  }

  ngOnDestroy(): void {
    if (this.mainPhotoUrl) {
      URL.revokeObjectURL(this.mainPhotoUrl);
    }
    Object.values(this.photoUrls).forEach(url => URL.revokeObjectURL(url));
  }

}

