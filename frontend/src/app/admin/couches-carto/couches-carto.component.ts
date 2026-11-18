import { ApercuGeojsonComponent, CoucheAffichee } from '../../shared/components/common/apercu-geojson/apercu-geojson.component';
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
  imports: [CommonModule, FormsModule, RouterLink, ApercuGeojsonComponent],
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

  // ── Voir sur la carte (18/11/2026) : la boîte à outils GeoJSON
  /** Les couches affichées sur la carte de la page : celles de la commune, et un fichier du poste. */
  affichees: CoucheAffichee[] = [];
  chargementApercu = '';
  /** Ce qu'on sait d'une couche une fois lue : de quoi choisir en connaissance de cause. */
  details: Record<string, string> = {};
  private readonly COULEURS = ['#2563eb', '#dc2626', '#16a34a', '#d97706', '#7c3aed', '#0891b2', '#be185d'];

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

  estAffichee(cle: string): boolean { return this.affichees.some(c => c.cle === cle); }

  private couleurLibre(): string {
    const prises = new Set(this.affichees.map(c => c.couleur));
    return this.COULEURS.find(c => !prises.has(c)) ?? this.COULEURS[this.affichees.length % this.COULEURS.length];
  }

  couleurDe(cle: string): string { return this.affichees.find(c => c.cle === cle)?.couleur ?? 'transparent'; }

  /** « 24 surfaces, 3 points — 180 ko » : ce que contient le fichier. */
  private decrire(donnees: GeoJSON.FeatureCollection, octets: number): string {
    const types: Record<string, number> = {};
    for (const objet of donnees.features ?? []) {
      const type = objet.geometry?.type ?? 'sans géométrie';
      const nom = type.includes('Polygon') ? 'surface' : type.includes('Line') ? 'ligne' : type.includes('Point') ? 'point' : type;
      types[nom] = (types[nom] ?? 0) + 1;
    }
    const contenu = Object.entries(types).map(([nom, n]) => `${n} ${nom}${n > 1 ? 's' : ''}`).join(', ') || 'aucun objet';
    const poids = octets >= 1_048_576 ? `${(octets / 1_048_576).toFixed(1)} Mo` : `${Math.max(1, Math.round(octets / 1024))} ko`;
    return `${contenu} — ${poids}`;
  }

  /** Affiche ou retire une couche de la commune sur la carte de la page. */
  basculer(couche: CoucheCarto): void {
    if (this.estAffichee(couche.couche)) { this.affichees = this.affichees.filter(c => c.cle !== couche.couche); return; }
    this.chargementApercu = couche.couche;
    this.erreur = '';
    this.http.get(`${this.url}/${couche.couche}/`, { responseType: 'text' }).subscribe({
      next: (texte) => {
        this.chargementApercu = '';
        try {
          const donnees = JSON.parse(texte) as GeoJSON.FeatureCollection;
          this.details[couche.couche] = this.decrire(donnees, texte.length);
          this.affichees = [...this.affichees, { cle: couche.couche, nom: couche.libelle, couleur: this.couleurLibre(), donnees }];
        } catch { this.erreur = `La couche « ${couche.libelle} » n'est pas lisible.`; }
      },
      error: () => { this.chargementApercu = ''; this.erreur = `La couche « ${couche.libelle} » n'a pas pu être lue.`; },
    });
  }

  /** Un fichier GeoJSON du poste, montré sur la carte SANS être envoyé : pour vérifier ce
   * qu'un bureau d'études a livré avant de décider quoi en faire. */
  voirFichierLocal(evenement: Event): void {
    const fichier = (evenement.target as HTMLInputElement).files?.[0];
    if (!fichier) return;
    this.erreur = '';
    fichier.text().then((texte) => {
      try {
        const lu = JSON.parse(texte);
        const donnees: GeoJSON.FeatureCollection = lu.type === 'FeatureCollection' ? lu
          : lu.type === 'Feature' ? { type: 'FeatureCollection', features: [lu] }
          : { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: lu }] };
        const premiere = (donnees.features?.[0]?.geometry as { coordinates?: unknown } | undefined)?.coordinates;
        const x = JSON.stringify(premiere ?? '').match(/-?\d+(\.\d+)?/)?.[0];
        if (x && Math.abs(Number(x)) > 180) {
          this.erreur = 'Ce fichier n\'est pas en longitude/latitude (WGS 84) : il ne peut pas être montré ici tel quel. '
            + 'L\'import des quartiers, lui, convertit le Lambert 93.';
          return;
        }
        const cle = 'fichier-local';
        this.details[cle] = `${fichier.name} : ${this.decrire(donnees, texte.length)}`;
        this.affichees = [...this.affichees.filter(c => c.cle !== cle), { cle, nom: fichier.name, couleur: '#111827', donnees }];
      } catch { this.erreur = `« ${fichier.name} » n'est pas un fichier GeoJSON lisible.`; }
    });
  }

  retirerFichierLocal(): void { this.affichees = this.affichees.filter(c => c.cle !== 'fichier-local'); delete this.details['fichier-local']; }

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
