import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { AuthService } from '../../auth/services/auth.service';
import { RecherchePersonneService } from '../../services/recherche-personne.service';
import { RecherchePersonneCommentaireService } from '../../services/recherche-personne-commentaire.service';
import { RecherchePersonneCommentairePhotoService } from '../../services/recherche-personne-commentaire-photo.service';
import { SecteurRechercheService } from '../../services/secteur-recherche.service';
import { TeamService } from '../../services/team.service';
import { SecteurRecherche, StatutSecteurRecherche } from '../../shared/models/secteur-recherche.model';
import { Team, teamDisplayName } from '../../shared/models/team.model';
import { ZoneMapComponent } from '../../shared/components/common/zone-map/zone-map.component';
import { QuiAConsulteComponent } from '../../shared/components/qui-a-consulte/qui-a-consulte.component';

@Component({
  selector: 'app-recherche-personne-detail',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ZoneMapComponent,
    QuiAConsulteComponent,
  ],
  templateUrl: './recherche-personne-detail.component.html',
  styleUrls: ['./recherche-personne-detail.component.scss']
})

export class RecherchePersonneDetailComponent
implements OnInit, OnDestroy {

  teamDisplayName = teamDisplayName;

  recherche: any;
  currentUser: any;
  commentaires: any[] = [];
  photosCommentaires: any[] = [];
  photosCommentaire: File[] = [];
  nouveauCommentaire = '';
  mainPhotoUrl: string | null = null;
  photoUrls: Record<string, string> = {};

  // ══ Secteurs de recherche (méthode SAR) ══════════════════════
  secteurs: SecteurRecherche[] = [];
  equipes: Team[] = [];
  ajoutSecteurOuvert = false;
  nouveauSecteurNom = '';
  nouveauSecteurEquipeId = '';
  nouveauSecteurWkt: string | null = null;
  creatingSecteur = false;
  secteurErreur = '';

  constructor(
    private route: ActivatedRoute,
    private authService: AuthService,
    private rechercheService: RecherchePersonneService,
    private commentaireService: RecherchePersonneCommentaireService,
    private commentairePhotoService: RecherchePersonneCommentairePhotoService,
    private secteurRechercheService: SecteurRechercheService,
    private teamService: TeamService,
  ) {}

  get peutGererSecteurs(): boolean {
    return this.authService.isInstitutionalEffective();
  }

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

          if (this.peutGererSecteurs) {
            this.loadSecteurs();
            this.teamService.getAll().subscribe(data => { this.equipes = data; });
          }

        });

    }

  }

  // ══ Secteurs de recherche (méthode SAR) ══════════════════════

  loadSecteurs(): void {
    this.secteurRechercheService.getPourRecherche(this.recherche.id).subscribe({
      next: (data) => { this.secteurs = data; },
      error: () => {},
    });
  }

  nomEquipe(equipeId: string | null): string {
    if (!equipeId) return '—';
    return this.equipes.find(e => e.id === equipeId)?.name || '—';
  }

  onNouveauSecteurZoneChange(wkt: string | null): void {
    this.nouveauSecteurWkt = wkt;
  }

  creerSecteur(): void {
    if (!this.nouveauSecteurNom.trim() || !this.nouveauSecteurWkt) {
      this.secteurErreur = 'Donnez un nom et dessinez le secteur sur la carte avant d\'enregistrer.';
      return;
    }
    this.creatingSecteur = true;
    this.secteurErreur = '';
    this.secteurRechercheService.create({
      recherche_personne: this.recherche.id,
      nom: this.nouveauSecteurNom.trim(),
      polygone: this.nouveauSecteurWkt,
      equipe: this.nouveauSecteurEquipeId || null,
    }).subscribe({
      next: (secteur) => {
        this.secteurs = [...this.secteurs, secteur];
        this.creatingSecteur = false;
        this.ajoutSecteurOuvert = false;
        this.nouveauSecteurNom = '';
        this.nouveauSecteurEquipeId = '';
        this.nouveauSecteurWkt = null;
      },
      error: (err) => {
        this.creatingSecteur = false;
        this.secteurErreur = err.error?.detail || "Impossible d'enregistrer ce secteur.";
      },
    });
  }

  changerStatutSecteur(secteur: SecteurRecherche, statut: StatutSecteurRecherche): void {
    this.secteurRechercheService.update(secteur.id, { statut }).subscribe({
      next: (maj) => { secteur.statut = maj.statut; },
      error: () => {},
    });
  }

  changerEquipeSecteur(secteur: SecteurRecherche, equipeId: string): void {
    this.secteurRechercheService.update(secteur.id, { equipe: equipeId || null }).subscribe({
      next: (maj) => { secteur.equipe = maj.equipe; },
      error: () => {},
    });
  }

  supprimerSecteur(secteur: SecteurRecherche): void {
    this.secteurRechercheService.delete(secteur.id).subscribe({
      next: () => { this.secteurs = this.secteurs.filter(s => s.id !== secteur.id); },
      error: () => {},
    });
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

