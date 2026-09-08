import { Component, OnInit } from '@angular/core';
import { CommonModule , DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DossierService } from '../../services/dossier.service';
import { DossierCommentaireService } from '../../services/dossier-commentaire.service';
import { DossierHistoriqueService } from '../../services/dossier-historique.service';
import { AuthService } from '../../auth/services/auth.service';
import { DocumentService } from '../../services/document.service';
import { TeamService } from '../../services/team.service';
import { RequestService } from '../../services/request.service';
import { InformationService } from '../../services/information.service';
import { Dossier } from '../../shared/models/dossier.model';
import { Team } from '../../shared/models/team.model';
import { UserRole } from '../../shared/models/user.model';
import { MinimapComponent } from '../../shared/components/common/minimap/minimap.component';

// Même mapping que mes-interventions/dossier-suivi (vocabulaire terrain) — affichage
// uniquement, les valeurs de statut en base sont inchangées.
const STATUT_LABELS: Record<string, string> = {
  EN_ATTENTE_DISTRIBUTION: 'En attente de distribution',
  NOUVEAU: 'Pris en compte',
  EN_ATTENTE_AFFECTATION: "En attente d'affectation",
  AFFECTE: 'Affecté à une équipe',
  EN_COURS: 'En cours',
  RESOLU: 'En attente de clôture',
  CLOTURE: 'Terminé',
};

// Statuts modifiables directement depuis cette vue (definir_statut) — CLOTURE/RESOLU
// restent exclusivement gérés par cloturerDossier(), avec sa propre garde côté backend.
const STATUTS_MODIFIABLES = ['NOUVEAU', 'EN_ATTENTE_DISTRIBUTION', 'EN_ATTENTE_AFFECTATION', 'AFFECTE', 'EN_COURS'];

@Component({
  selector: 'app-dossiers',
  standalone: true,
  imports: [CommonModule, FormsModule, DatePipe, MinimapComponent],
  templateUrl: './dossiers.component.html',
  styleUrls: ['./dossiers.component.scss']
})
export class DossiersComponent implements OnInit {

  dossiers: Dossier[] = [];
  teams: Team[] = [];

  viewMode: 'ma_file' | 'tous' = 'tous';
  isRegulateur = false;

  selectedDossier: Dossier | null = null;
  savingEquipe = false;
  savingStatut = false;

  readonly statutOptions = STATUTS_MODIFIABLES.map(value => ({ value, label: STATUT_LABELS[value] }));

  commentaires: any[] = [];
  historique: any[] = [];
  documents: any[] = [];
  nouveauCommentaire = '';
  selectedFile: File | null = null;
  imagePopupUrl: string | null = null;
  /** Photo de la demande/du signalement d'origine du dossier (voir DossierSerializer.
   * has_photo/get_has_photo) — réutilise RequestViewSet.preview/InformationViewSet.preview,
   * déjà accessibles à un participant du dossier (user_can_view_photo dossiers_field). */
  origineDossierPhotoUrl: string | null = null;

  constructor(
    private dossierService: DossierService,
    private commentaireService: DossierCommentaireService,
    private historiqueService: DossierHistoriqueService,
    private documentService: DocumentService,
    private teamService: TeamService,
    private requestService: RequestService,
    private informationService: InformationService,
    private authService: AuthService
  ) {}

  ngOnInit(): void {
    this.isRegulateur = this.authService.getCurrentUser()?.type === UserRole.REGULATEUR;
    this.viewMode = this.isRegulateur ? 'ma_file' : 'tous';
    this.load();
    this.teamService.getAll().subscribe(teams => this.teams = teams);
  }

  statutLabel(statut: string): string {
    return STATUT_LABELS[statut] || statut;
  }

  setViewMode(mode: 'ma_file' | 'tous'): void {
    this.viewMode = mode;
    this.load();
  }

  load(): void {
    const source = this.viewMode === 'ma_file'
      ? this.dossierService.getMaFile()
      : this.dossierService.getAll();

    source.subscribe(data => {
      this.dossiers = data;
    });
  }
  openDossier(dossier: Dossier): void {

    this.selectedDossier = dossier;
    this.loadOrigineDossierPhoto(dossier);

    this.commentaireService.getAll()
      .subscribe(data => {

        this.commentaires =
          data.filter(
            c => c.dossier === dossier.id
          );

      });

    this.historiqueService.getAll()
      .subscribe(data => {

        this.historique =
          data.filter(
            h => h.dossier === dossier.id
          );

      });
     this.documentService.getAll()
      .subscribe(data => {

        this.documents =
          data.filter(
            doc => doc.dossier === dossier.id
          );

      });  
  }

  onFileSelected(event: any): void {

    if (event.target.files.length > 0) {

      this.selectedFile =
        event.target.files[0];

        console.log(
          'FICHIER SELECTIONNE',
          this.selectedFile
        );
    }
  }

  uploadDocument(
    dossierId: string,
    auteurId: string
  ): void {

    if (!this.selectedFile) {
      console.log(
        'AUCUN FICHIER SELECTIONNE'
      ); 

      return;
    }

    const formData = new FormData();

    formData.append(
      'fichier',
      this.selectedFile
    );

    formData.append(
      'dossier',
      dossierId
    );

    formData.append(
      'auteur',
      auteurId
    );

    formData.append(
      'commentaire',
      this.nouveauCommentaire
    );
    console.log(
      'UPLOAD DOCUMENT',
      this.selectedFile.name
    );
    this.documentService
      .create(formData)
      .subscribe({
        next: res => {
          console.log(
            'DOCUMENT CREE',
            res
          );
        },
        error: err => {
          console.error(
            'ERREUR DOCUMENT',
            err
          );
          this.reloadDossier();
        }
      });

  }

  publierMiseAJour(): void {

    if (!this.selectedDossier) {
      return;
    }

    const currentUser =
      this.authService.getCurrentUser();

    if (!currentUser) {
      return;
    }

    if (this.nouveauCommentaire.trim()) {

      this.commentaireService.create({
        dossier: this.selectedDossier.id,
        commentaire: this.nouveauCommentaire
      }).subscribe();
    }

    if (this.selectedFile) {

      this.uploadDocument(
        this.selectedDossier.id,
        currentUser.id
      );
    }

    this.nouveauCommentaire = '';

    this.selectedFile = null;

    if (!this.selectedFile) {
      this.reloadDossier();
    }

  }

  reloadDossier(): void {

    if (!this.selectedDossier) {
      return;
    }

    this.openDossier(
      this.selectedDossier
    );
  }

  closeDossier(): void {
    this.selectedDossier = null;
    if (this.origineDossierPhotoUrl) URL.revokeObjectURL(this.origineDossierPhotoUrl);
    this.origineDossierPhotoUrl = null;
  }

  private loadOrigineDossierPhoto(dossier: Dossier): void {
    if (this.origineDossierPhotoUrl) URL.revokeObjectURL(this.origineDossierPhotoUrl);
    this.origineDossierPhotoUrl = null;
    if (!dossier.has_photo) return;
    const preview$ = dossier.demande
      ? this.requestService.preview(dossier.demande)
      : dossier.information ? this.informationService.preview(dossier.information) : null;
    preview$?.subscribe({
      next: (blob) => this.origineDossierPhotoUrl = URL.createObjectURL(blob),
      error: () => {},
    });
  }

  affecterEquipe(equipeId: string): void {
    if (!this.selectedDossier || !equipeId || this.savingEquipe) {
      return;
    }
    this.savingEquipe = true;
    this.dossierService.affecterEquipe(this.selectedDossier.id, equipeId).subscribe({
      next: (updated) => {
        this.selectedDossier = updated;
        this.savingEquipe = false;
        this.load();
      },
      error: (err) => {
        alert(err.error?.error || "Impossible d'affecter cette équipe.");
        this.savingEquipe = false;
      },
    });
  }

  changerStatut(statut: string): void {
    if (!this.selectedDossier || this.savingStatut) {
      return;
    }
    this.savingStatut = true;
    this.dossierService.definirStatut(this.selectedDossier.id, statut).subscribe({
      next: (updated) => {
        this.selectedDossier = updated;
        this.savingStatut = false;
        this.load();
      },
      error: (err) => {
        alert(err.error?.error || 'Impossible de changer le statut.');
        this.savingStatut = false;
      },
    });
  }

  cloturerDossier(statut: 'CLOTURE' | 'RESOLU'): void {
    if (!this.selectedDossier) {
      return;
    }

    const libelle = statut === 'CLOTURE' ? 'clôturer' : 'marquer résolu';
    if (!confirm(`Confirmer : ${libelle} ce dossier ?`)) {
      return;
    }

    this.dossierService.cloturer(this.selectedDossier.id, statut).subscribe({
      next: res => {
        if (this.selectedDossier) {
          this.selectedDossier.statut = res.statut;
        }
        this.load();
      },
      error: err => {
        alert(err.error?.error || 'Impossible de clôturer ce dossier.');
      }
    });
  }

  telechargerDocument(
    doc: any
  ): void {

    this.documentService
      .download(doc.id)
      .subscribe(blob => {

        const url =
          window.URL.createObjectURL(blob);

        const a =
          document.createElement('a');

        a.href = url;
 
        a.download = 'document';
 
        a.click();

        window.URL.revokeObjectURL(url);

      });

  }

  visualiserDocument(
    doc: any
  ): void {

    this.documentService
      .download(doc.id)
      .subscribe(blob => {

        this.imagePopupUrl =
          URL.createObjectURL(blob);

      });

  }

  fermerImage(): void {

    if (this.imagePopupUrl) {
      URL.revokeObjectURL(
        this.imagePopupUrl
      );
    }

    this.imagePopupUrl = null;

  }

}


