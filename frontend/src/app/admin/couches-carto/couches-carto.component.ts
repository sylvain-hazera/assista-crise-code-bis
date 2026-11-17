import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { environment } from '../../../environments/environment';

export interface CoucheCarto { couche: string; libelle: string; objets: number; }

export interface BilanImportQuartiers {
  /** Faux : c'était un aperçu, rien n'a été créé. */
  enregistre: boolean;
  crees: number; remplaces: number; laisses: number; ignores: number;
  lignes: { nom: string; action: 'CREE' | 'REMPLACE' | 'EXISTE' | 'IGNORE'; remarque: string }[];
}

/**
 * Couches cartographiques : sortir ce que la commune a saisi ici vers un logiciel de
 * cartographie, et faire entrer les quartiers qu'elle a déjà dessinés ailleurs.
 *
 * Tout passe en GeoJSON (longitude et latitude), que QGIS et les autres ouvrent sans réglage.
 * L'import montre toujours un aperçu avant de créer quoi que ce soit, et ne redessine un
 * quartier existant que si on le demande. Le registre des personnes vulnérables ne sort pas.
 */
@Component({
  selector: 'app-couches-carto',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './couches-carto.component.html',
  styleUrl: '../pcs-annuaire/pcs-paragraphe.scss',
})
export class CouchesCartoComponent implements OnInit {
  private readonly url = `${environment.apiUrl}/couches-carto`;
  couches: CoucheCarto[] = [];
  chargement = true;
  sansCollectivite = false;
  erreur = '';
  exportEnCours = '';

  fichier: File | null = null;
  remplacer = false;
  importEnCours = false;
  apercu: BilanImportQuartiers | null = null;
  resultat: BilanImportQuartiers | null = null;
  erreurImport = '';

  readonly actions: Record<string, string> = {
    CREE: 'sera créé', REMPLACE: 'sera redessiné', EXISTE: 'existe déjà', IGNORE: 'ignoré',
  };

  constructor(private http: HttpClient) {}

  ngOnInit(): void { this.charger(); }

  charger(): void {
    this.http.get<CoucheCarto[]>(`${this.url}/`).subscribe({
      next: (couches) => { this.couches = couches; this.chargement = false; },
      error: (e) => {
        this.chargement = false;
        this.sansCollectivite = e?.status === 403;
        if (!this.sansCollectivite) this.erreur = 'Impossible de lire les couches.';
      },
    });
  }

  exporter(couche: CoucheCarto): void {
    this.exportEnCours = couche.couche;
    this.erreur = '';
    this.http.get(`${this.url}/${couche.couche}/`, { responseType: 'blob' }).subscribe({
      next: (contenu) => {
        const lien = document.createElement('a');
        const adresse = URL.createObjectURL(contenu);
        lien.href = adresse;
        lien.download = `${couche.couche}.geojson`;
        lien.click();
        URL.revokeObjectURL(adresse);
        this.exportEnCours = '';
      },
      error: () => { this.exportEnCours = ''; this.erreur = `La couche « ${couche.libelle} » n'a pas pu être exportée.`; },
    });
  }

  choisirFichier(evenement: Event): void {
    this.fichier = (evenement.target as HTMLInputElement).files?.[0] ?? null;
    this.apercu = null;
    this.resultat = null;
    this.erreurImport = '';
    if (this.fichier) this.envoyer(false);
  }

  /** `enregistrer` faux : aperçu seulement, le serveur ne crée rien. */
  envoyer(enregistrer: boolean): void {
    if (!this.fichier) return;
    const formulaire = new FormData();
    formulaire.append('fichier', this.fichier);
    if (enregistrer) formulaire.append('enregistrer', '1');
    if (this.remplacer) formulaire.append('remplacer', '1');
    this.importEnCours = true;
    this.erreurImport = '';
    this.http.post<BilanImportQuartiers>(`${this.url}/quartiers/importer/`, formulaire).subscribe({
      next: (bilan) => {
        this.importEnCours = false;
        if (bilan.enregistre) {
          this.resultat = bilan;
          this.apercu = null;
          this.fichier = null;
          this.charger();
        } else {
          this.apercu = bilan;
        }
      },
      error: (e) => {
        this.importEnCours = false;
        this.apercu = null;
        const message = e?.error?.fichier;
        this.erreurImport = (Array.isArray(message) ? message[0] : message) || 'Ce fichier n’a pas pu être lu.';
      },
    });
  }

  /** Vrai s'il y a quelque chose à créer ou à redessiner dans l'aperçu. */
  get aImporter(): boolean {
    return !!this.apercu && (this.apercu.crees + this.apercu.remplaces) > 0;
  }
}
