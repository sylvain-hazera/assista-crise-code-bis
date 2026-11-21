import { Injectable, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';
import { HorsLigneService } from '../hors-ligne.service';
import { PhotosTerrainService } from '../photo/photos-terrain.service';
import { Releve } from '../position/regles-suivi';
import {
  Constat, PointTournee, SecteurEmbarque, TypeBien, marquerEnAttente, secteurAEffacer, tourneeHorsLigne,
} from './degats';

export interface Tournee { points: PointTournee[]; horsLigne: boolean; refus: string | null; }

export const RAYON_EMBARQUE_M = 1000;

/**
 * L'évaluation des dégâts à pied, côté données (portage de `DepotDegats.kt`) :
 * - **la tournée** : demandée au serveur quand il répond, calculée sur le secteur embarqué sinon ;
 * - **le secteur embarqué** n'est chargé qu'à la demande, gardé chiffré, daté, et **effacé dès
 *   l'envoi** de ce qui y a été saisi ;
 * - **constats et photos** passent par la file. Le constat porte un identifiant tiré ici : renvoyé
 *   dix fois, il ne crée qu'un constat. Une photo vise son constat, et part après lui.
 */
@Injectable({ providedIn: 'root' })
export class DegatsService {
  readonly secteur = signal<SecteurEmbarque | null>(null);
  readonly types = signal<TypeBien[]>([]);
  private api = environment.apiUrl;
  private restaure: Promise<void> | null = null;

  constructor(private http: HttpClient, private horsLigne: HorsLigneService, private photos: PhotosTerrainService) {
    this.horsLigne.apresChaqueEnvoi(() => this.apresEnvoi());
  }

  restaurer(): Promise<void> {
    this.restaure ??= (async () => {
      this.secteur.set((await this.horsLigne.relire<SecteurEmbarque>('degats-secteur'))?.valeur ?? null);
      this.types.set((await this.horsLigne.relire<TypeBien[]>('degats-types'))?.valeur ?? []);
    })();
    return this.restaure;
  }

  /** Le catalogue des types de bien, gardé pour servir hors réseau. */
  async chargerTypes(): Promise<void> {
    try {
      const reponse = await firstValueFrom(this.http.get<TypeBien[] | { results: TypeBien[] }>(`${this.api}/types-bien/`));
      const types = Array.isArray(reponse) ? reponse : reponse.results ?? [];
      this.types.set(types);
      await this.horsLigne.garder('degats-types', types);
    } catch { /* hors réseau : le catalogue gardé sert */ }
  }

  /** « Embarquer ce secteur » : adresses, biens, dossiers et cercles autour de moi. Rend un
   * message pour l'écran. */
  async embarquer(crise: string, ici: Releve): Promise<string> {
    this.chargerTypes();
    try {
      const secteur = await firstValueFrom(this.http.get<SecteurEmbarque>(`${this.api}/habitations/secteur/`, {
        params: { crise, latitude: ici.latitude, longitude: ici.longitude, rayon_m: RAYON_EMBARQUE_M },
      }));
      await this.enregistrer({ ...secteur, constats_faits: 0 });
      return `Secteur embarqué : ${secteur.adresses.length} adresses, ${secteur.biens.length} biens déjà vus. `
        + 'Il s\'effacera de ce téléphone dès que vos constats seront partis.';
    } catch (e) {
      if (HorsLigneService.estHorsLigne(e)) return 'Pas de réseau : le secteur n\'a pas pu être embarqué.';
      return e instanceof HttpErrorResponse ? HorsLigneService.motifDuRefus(e) : 'Le secteur n\'a pas pu être embarqué.';
    }
  }

  async effacerSecteur(): Promise<void> {
    await this.horsLigne.oublier('degats-secteur');
    this.secteur.set(null);
  }

  /** Les points autour de moi : ceux du serveur, ou ceux du secteur embarqué sans réseau. */
  async tournee(crise: string, ici: Releve, rayonM = 150): Promise<Tournee> {
    const enFile = await this.constatsEnFile();
    try {
      const r = await firstValueFrom(this.http.get<{ points: PointTournee[] }>(`${this.api}/habitations/tournee/`, {
        params: { crise, latitude: ici.latitude, longitude: ici.longitude, rayon_m: rayonM },
      }));
      return { points: marquerEnAttente(r.points ?? [], enFile), horsLigne: false, refus: null };
    } catch (e) {
      if (!HorsLigneService.estHorsLigne(e)) {
        return { points: [], horsLigne: false,
                 refus: e instanceof HttpErrorResponse ? HorsLigneService.motifDuRefus(e) : 'La tournée n\'a pas pu être chargée.' };
      }
      const secteur = this.secteur();
      if (!secteur || secteur.crise !== crise) {
        return { points: [], horsLigne: true, refus: 'Pas de réseau, et aucun secteur embarqué pour cette crise.' };
      }
      return { points: tourneeHorsLigne(secteur, enFile, ici.latitude, ici.longitude, rayonM), horsLigne: true, refus: null };
    }
  }

  /** Un constat fini : en file, puis ses photos (chacune scellée), dans cet ordre. Rend le
   * nombre de photos illisibles (non jointes). */
  async constater(constat: Constat, libelle: string, photos: Blob[], position: Releve | null): Promise<number> {
    await this.horsLigne.differer({ genre: 'constat', constat, libelle, faite_le: constat.constate_le });
    const secteur = this.secteur();
    if (secteur) await this.enregistrer({ ...secteur, constats_faits: (secteur.constats_faits ?? 0) + 1 });
    let illisibles = 0;
    for (const photo of photos) {
      try {
        await this.photos.prendre(photo, { genre: 'photo_constat', constat: constat.id }, '', `Photo — ${libelle}`, position);
      } catch {
        illisibles++;
      }
    }
    await this.horsLigne.envoyer();
    return illisibles;
  }

  async constatsEnFile(): Promise<Constat[]> {
    return (await this.horsLigne.enFile()).flatMap(({ valeur }) => (valeur.genre === 'constat' ? [valeur.constat] : []));
  }

  async constatEncoreEnFile(id: string): Promise<boolean> {
    return (await this.constatsEnFile()).some(c => c.id === id);
  }

  /** Après chaque envoi : tout ce qui a été saisi est parti, le secteur s'efface. */
  private async apresEnvoi(): Promise<void> {
    await this.restaurer();
    const genres = (await this.horsLigne.enFile()).map(a => a.valeur.genre);
    if (secteurAEffacer(this.secteur(), genres)) await this.effacerSecteur();
  }

  private async enregistrer(secteur: SecteurEmbarque): Promise<void> {
    await this.horsLigne.garder('degats-secteur', secteur);
    this.secteur.set(secteur);
  }

  /** À la déconnexion (les coffres sont vidés par HorsLigneService.effacer). */
  oublier(): void {
    this.secteur.set(null);
    this.types.set([]);
    this.restaure = null;
  }
}
