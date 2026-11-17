import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { BienSinistreService } from '../../services/bien-sinistre.service';
import { CrisisService } from '../../services/crisis.service';
import { DocumentService } from '../../services/document.service';
import { BoutonRapportComponent } from '../../shared/components/common/bouton-rapport/bouton-rapport.component';
import { BienSinistre, LABELS_TYPE_BIEN, TypeBienSinistre } from '../../shared/models/bien-sinistre.model';
import { Crisis } from '../../shared/models/crisis.model';
import { DossierDocument } from '../../shared/models/dossier-document.model';
import {
  LABELS_NATURE_DEGATS, LABELS_STATUT_EVALUATION, NatureDegatsHabitation, STATUTS_AVEC_DEGATS, StatutEvaluationHabitation,
} from '../../shared/models/habitation.model';

type Brouillon = Partial<BienSinistre> & { type_bien: TypeBienSinistre; designation: string };

/**
 * Biens sinistrés autres que les habitations : les voitures brûlées d'un feu de forêt, un
 * bateau, un hangar, du matériel. Pour chacun, de quoi monter le dossier qu'on remettra à son
 * propriétaire : ce que c'est, où il était, ce qui l'a touché, les photos.
 *
 * Fait pour le terrain : la position se prend au téléphone, les photos se déposent depuis
 * l'appareil. Le propriétaire n'est pas toujours connu sur le moment : ses coordonnées se
 * complètent ensuite, et le rapport lui est alors envoyé d'un clic.
 */
@Component({
  selector: 'app-biens-sinistres',
  standalone: true,
  imports: [CommonModule, FormsModule, BoutonRapportComponent],
  templateUrl: './biens-sinistres.component.html',
  styleUrl: './biens-sinistres.component.scss',
})
export class BiensSinistresComponent implements OnInit {
  readonly types = LABELS_TYPE_BIEN;
  readonly natures = LABELS_NATURE_DEGATS;
  readonly etats = LABELS_STATUT_EVALUATION;

  crises: Crisis[] = [];
  criseId = '';
  biens: BienSinistre[] = [];
  chargement = false;
  erreur = '';
  message = '';

  /** Le bien en cours de saisie ou de modification ; null = liste seule. */
  brouillon: Brouillon | null = null;
  enregistrement = false;
  localisation = false;
  photos: DossierDocument[] = [];
  depotEnCours = false;
  envoiEnCours = false;

  constructor(private service: BienSinistreService, private crisisService: CrisisService,
              private documents: DocumentService) {}

  ngOnInit(): void {
    this.crisisService.getAll().subscribe({
      next: (crises) => {
        this.crises = crises.filter(c => c.is_open !== false);
        if (this.crises.length === 1) { this.criseId = this.crises[0].id; }
        this.charger();
      },
      error: () => { this.erreur = 'Impossible de lire les crises.'; },
    });
  }

  charger(): void {
    this.chargement = true;
    this.service.lister(this.criseId || undefined).subscribe({
      next: (biens) => { this.biens = biens; this.chargement = false; },
      error: () => { this.chargement = false; this.erreur = 'Impossible de lire les biens sinistrés.'; },
    });
  }

  nouveau(): void {
    this.message = this.erreur = '';
    if (!this.criseId) { this.erreur = 'Choisissez d’abord la crise : un bien sinistré se rattache à une crise.'; return; }
    this.brouillon = { crise: this.criseId, type_bien: 'VEHICULE', designation: '', identification: '', description: '', adresse: '',
                       latitude: null, longitude: null, nature_degats: '', statut_evaluation: 'DEGATS_FORTS',
                       proprietaire_nom: '', proprietaire_email: '', proprietaire_telephone: '' };
    this.photos = [];
  }

  ouvrir(bien: BienSinistre): void {
    this.message = this.erreur = '';
    this.brouillon = { ...bien };
    this.documents.getAll({ bien: bien.id } as any).subscribe({ next: (photos) => this.photos = photos, error: () => this.photos = [] });
  }

  fermer(): void { this.brouillon = null; this.photos = []; }

  get degatsConstates(): boolean {
    return !!this.brouillon && STATUTS_AVEC_DEGATS.includes(this.brouillon.statut_evaluation as StatutEvaluationHabitation);
  }

  /** La position du téléphone : là où se trouve le bien, devant lequel on se tient. */
  prendreMaPosition(): void {
    if (!this.brouillon) return;
    if (!('geolocation' in navigator)) { this.erreur = 'Cet appareil ne donne pas sa position.'; return; }
    this.localisation = true;
    navigator.geolocation.getCurrentPosition(
      (position) => {
        this.localisation = false;
        this.brouillon = { ...this.brouillon!, latitude: +position.coords.latitude.toFixed(6), longitude: +position.coords.longitude.toFixed(6) };
        this.message = position.coords.accuracy > 30 ? `Position prise, précise à ${Math.round(position.coords.accuracy)} m seulement.` : 'Position prise.';
      },
      () => { this.localisation = false; this.erreur = 'Position refusée ou indisponible : saisissez l’adresse à la place.'; },
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 },
    );
  }

  enregistrer(): void {
    const b = this.brouillon;
    if (!b) return;
    if (!b.designation.trim()) { this.erreur = 'Dites de quel bien il s’agit (par exemple « Renault Clio grise »).'; return; }
    this.enregistrement = true;
    this.erreur = '';
    const donnees = { ...b, nature_degats: (this.degatsConstates ? b.nature_degats : '') as NatureDegatsHabitation };
    (b.id ? this.service.modifier(b.id, donnees) : this.service.creer(donnees)).subscribe({
      next: (bien) => {
        this.enregistrement = false;
        this.brouillon = { ...bien };
        this.message = 'Enregistré. Vous pouvez ajouter les photos.';
        this.charger();
      },
      error: (e) => {
        this.enregistrement = false;
        const d = e?.error || {};
        this.erreur = d.error || d.detail || Object.values(d).flat().join(' ') || 'Ce bien n’a pas pu être enregistré.';
      },
    });
  }

  deposerPhotos(evenement: Event): void {
    const champ = evenement.target as HTMLInputElement;
    const fichiers = Array.from(champ.files ?? []);
    if (!fichiers.length || !this.brouillon?.id) return;
    this.depotEnCours = true;
    let restant = fichiers.length;
    const fin = () => { if (--restant === 0) { this.depotEnCours = false; champ.value = ''; this.charger(); } };
    for (const fichier of fichiers) {
      const formulaire = new FormData();
      formulaire.append('fichier', fichier);
      formulaire.append('bien', this.brouillon.id);
      this.documents.create(formulaire).subscribe({
        next: (photo) => { this.photos = [...this.photos, photo]; fin(); },
        error: () => { this.erreur = `« ${fichier.name} » n’a pas pu être déposée (image trop lourde ou format non accepté).`; fin(); },
      });
    }
  }

  envoyerAuProprietaire(): void {
    const b = this.brouillon;
    if (!b?.id) return;
    if (!confirm(`Envoyer le rapport de ce bien à ${b.proprietaire_email} ?`)) return;
    this.envoiEnCours = true;
    this.service.envoyerAuProprietaire(b.id).subscribe({
      next: (bien) => { this.envoiEnCours = false; this.brouillon = { ...bien }; this.message = `Rapport envoyé à ${bien.envoye_a}.`; },
      error: (e) => { this.envoiEnCours = false; this.erreur = e?.error?.error || 'Le rapport n’a pas pu être envoyé.'; },
    });
  }

  supprimer(): void {
    const b = this.brouillon;
    if (!b?.id || !confirm(`Supprimer « ${b.designation} » et ses photos ? C'est définitif.`)) return;
    this.service.supprimer(b.id).subscribe({
      next: () => { this.fermer(); this.message = 'Bien supprimé.'; this.charger(); },
      error: () => { this.erreur = 'Ce bien n’a pas pu être supprimé.'; },
    });
  }
}
