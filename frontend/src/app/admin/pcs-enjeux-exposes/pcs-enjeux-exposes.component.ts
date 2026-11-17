import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { environment } from '../../../environments/environment';

export interface EnjeuExpose {
  nature: string; categorie: string; nom: string;
  /** Faux : pas de coordonnées, donc rien à croiser. */
  situe: boolean;
  /** Niveau d'eau à partir duquel l'enjeu est atteint ; `null` = au sec jusqu'au plus haut niveau simulé. */
  seuil_m: number | null;
  effectif: number | null;
  /** Scénario officiel de débordement le plus fréquent dont la zone contient l'enjeu ; vide sinon. */
  zone_officielle: string;
}

/** Ce qu'on sait des zones inondables officielles de la commune (Géorisques), gardées en base. */
export interface ZonagesOfficiels {
  releve: boolean;
  releve_le: string | null;
  complet: boolean;
  couches: { couche: string; libelle: string; relevee: boolean; presente: boolean }[];
}

export interface EnjeuxExposes {
  commune_code: string;
  simulation_disponible: boolean;
  niveaux_m: number[];
  niveau_max_m: number | null;
  enjeux: EnjeuExpose[];
  atteints: number;
  non_situes: number;
  zonages_officiels: ZonagesOfficiels;
  en_zone_officielle: number;
}

/**
 * Paragraphe 1.3 du plan : ce que l'eau atteint, et à partir de quel niveau.
 *
 * Les sites sensibles retenus et les lieux d'accueil du plan sont croisés avec la simulation
 * d'inondation de la commune (core/enjeux_exposes.py). C'est la question qu'on pose d'ordinaire
 * à un logiciel de cartographie : « si l'eau monte de deux mètres, qu'est-ce qui est dedans ? ».
 *
 * Ce sont des hypothèses, et l'écran le dit en tête : la simulation étend un niveau d'eau sur le
 * relief, elle ne connaît ni les digues ni le courant.
 */
@Component({
  selector: 'app-pcs-enjeux-exposes',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './pcs-enjeux-exposes.component.html',
  styleUrl: '../pcs-annuaire/pcs-paragraphe.scss',
})
export class PcsEnjeuxExposesComponent implements OnInit {
  donnees: EnjeuxExposes | null = null;
  /** Niveau d'eau regardé : ce qui est atteint à ce niveau ou en dessous est mis en avant. */
  niveau: number | null = null;
  chargement = true;
  sansCollectivite = false;
  erreur = '';

  constructor(private http: HttpClient) {}

  /** Relevé des zones officielles demandé : il se fait en tâche de fond, requêtes espacées. */
  releveDemande = false;
  messageReleve = '';

  ngOnInit(): void { this.charger(); }

  /** Demande au serveur de relever les zones inondables officielles auprès de Géorisques. Le
   * serveur espace ses requêtes et ne refait pas un relevé récent : on relit un peu plus tard. */
  releverZonages(): void {
    this.releveDemande = true;
    this.messageReleve = '';
    this.http.post<ZonagesOfficiels & { pause_s: number }>(`${environment.apiUrl}/dossier-pcs/zonages-officiels/`, {}).subscribe({
      next: (reponse) => {
        this.messageReleve = `Relevé demandé à Géorisques. Les requêtes sont espacées de ${reponse.pause_s} secondes pour ne pas `
          + 'presser leur service : comptez une minute, puis cliquez « Actualiser ».';
      },
      error: (e) => {
        this.releveDemande = false;
        this.messageReleve = e?.error?.commune || 'Le relevé n’a pas pu être demandé.';
      },
    });
  }

  get zonesOfficiellesPresentes(): string[] {
    return (this.donnees?.zonages_officiels?.couches ?? []).filter(c => c.presente).map(c => c.libelle);
  }

  charger(): void {
    this.http.get<EnjeuxExposes>(`${environment.apiUrl}/dossier-pcs/enjeux-exposes/`).subscribe({
      next: (donnees) => {
        this.donnees = donnees;
        if (this.niveau === null) this.niveau = donnees.niveau_max_m;
        if (donnees.zonages_officiels?.complet) { this.releveDemande = false; this.messageReleve = ''; }
        this.chargement = false;
      },
      error: (e) => {
        this.chargement = false;
        this.sansCollectivite = e?.status === 403;
        if (!this.sansCollectivite) this.erreur = 'Impossible de lire les enjeux exposés.';
      },
    });
  }

  /** Vrai si l'enjeu est dans l'eau au niveau regardé. */
  atteint(enjeu: EnjeuExpose): boolean {
    return enjeu.seuil_m !== null && this.niveau !== null && enjeu.seuil_m <= this.niveau;
  }

  get nombreAtteints(): number {
    return (this.donnees?.enjeux ?? []).filter(e => this.atteint(e)).length;
  }

  texteDuSeuil(enjeu: EnjeuExpose): string {
    if (!enjeu.situe) return 'non situé';
    if (enjeu.seuil_m === null) return `au sec jusqu'à ${this.metres(this.donnees?.niveau_max_m ?? 0)}`;
    return `atteint à partir de ${this.metres(enjeu.seuil_m)}`;
  }

  metres(valeur: number): string {
    return `${String(valeur).replace('.', ',')} m`;
  }
}
