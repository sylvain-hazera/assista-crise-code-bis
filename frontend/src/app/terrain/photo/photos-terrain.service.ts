import { Injectable } from '@angular/core';
import { HorsLigneService } from '../hors-ligne.service';
import { SuiviTerrainService } from '../position/suivi-terrain.service';
import { positionPonctuelle, recente } from '../position/position-du-moment';
import { Releve } from '../position/regles-suivi';
import { preparerPhoto } from './photo-scellee';

export type CiblePhoto = { genre: 'photo_dossier'; dossier: string } | { genre: 'photo_constat'; constat: string };

export interface PhotoMiseEnFile { sansLieu: boolean; empreinte: string; }

const LOGICIEL = 'Assista-Crise terrain (web)';

/**
 * Une photo prise sur le terrain : réduite, datée, située, scellée par son empreinte, chiffrée,
 * puis mise en file. Elle part tout de suite s'il y a du réseau, sinon au retour du réseau.
 */
@Injectable({ providedIn: 'root' })
export class PhotosTerrainService {
  constructor(private horsLigne: HorsLigneService, private suivi: SuiviTerrainService) {}

  async prendre(fichier: Blob, cible: CiblePhoto, commentaire: string, libelle: string,
                position: Releve | null = null): Promise<PhotoMiseEnFile> {
    const lieu = recente(position) ?? recente(this.suivi.dernierePosition()) ?? await positionPonctuelle();
    const prete = await preparerPhoto(fichier, lieu, LOGICIEL);
    const cle = await this.horsLigne.garderPhoto(prete.octets);
    await this.horsLigne.differer({
      ...cible, cle, empreinte: prete.empreinte, commentaire: commentaire.trim().slice(0, 500), libelle,
      faite_le: prete.prise_le,
    });
    this.horsLigne.envoyer();
    return { sansLieu: lieu === null, empreinte: prete.empreinte };
  }
}
