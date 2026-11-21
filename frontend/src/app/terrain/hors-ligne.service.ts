import { Injectable, NgZone, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../environments/environment';
import { CoffreChiffre } from '../services/coffre-chiffre';
import type { Constat } from './degats/degats';
import { depuisBase64, versBase64 } from './photo/photo-scellee';

/** Une photo prise ici : ses octets attendent dans un coffre à part, la file ne porte que leur
 * clé et l'empreinte calculée à la prise, comparée à celle du serveur au retour. */
interface PhotoEnFile { cle: string; empreinte: string; commentaire: string; libelle: string; faite_le: string; }

/** Une action faite sans réseau, à rejouer telle quelle (toutes sont idempotentes, ou sans
 * conséquence si elles sont rejouées : une position, une photo de plus). */
export type ActionTerrain =
  | { genre: 'statut_mission'; mission: string; statut: string; faite_le: string }
  | { genre: 'accuse'; ids: string[]; etape: 'REMISE' | 'VUE' | 'LUE'; faite_le: string }
  | { genre: 'position'; latitude: number; longitude: number; faite_le: string }
  | { genre: 'constat'; constat: Constat; libelle: string; faite_le: string }
  | ({ genre: 'photo_constat'; constat: string } & PhotoEnFile)
  | ({ genre: 'photo_dossier'; dossier: string } & PhotoEnFile);

export interface CopieHorsLigne<T> { valeur: T; enregistree_le: string; }

/** Un envoi que le serveur a refusé : il n'est plus en file, mais la personne doit le savoir. */
export interface EnvoiRefuse { libelle: string; motif: string; }

const ECART_EMPREINTE = 'L\'empreinte de la photo reçue par le serveur ne correspond pas à celle prise ici. '
  + 'Signalez-le à votre encadrement.';

/**
 * Le terrain sans réseau (DOSSIER-PWA-INTERVENANTS.md, lots 3 et 5).
 *
 * - Ce qui a été lu (missions, alertes, dossiers, attestations) est gardé, chiffré, et remontré
 *   sans réseau, daté.
 * - Ce qui est fait sans réseau (statut de mission, accusé, position, constat, photo) attend dans
 *   une file chiffrée et part dès que le réseau revient, ou à la prochaine ouverture : sur
 *   iPhone, rien ne part application fermée.
 * - À la déconnexion, tout est effacé, clés comprises.
 */
@Injectable({ providedIn: 'root' })
export class HorsLigneService {
  readonly enLigne = signal(typeof navigator === 'undefined' ? true : navigator.onLine);
  readonly enAttente = signal(0);
  readonly refus = signal<EnvoiRefuse[]>([]);

  private copies = new CoffreChiffre('assista-crise-terrain-copies');
  private file = new CoffreChiffre('assista-crise-terrain-envois');
  private photos = new CoffreChiffre('assista-crise-terrain-photos');
  private envoiEnCours: Promise<number> | null = null;
  private demarre = false;
  /** Appelés après chaque passage de la file (le secteur embarqué s'efface, par exemple). */
  private readonly apres: (() => Promise<void> | void)[] = [];

  constructor(private http: HttpClient, private zone: NgZone) {}

  demarrer(): void {
    if (this.demarre || typeof window === 'undefined') return;
    this.demarre = true;
    window.addEventListener('online', () => this.zone.run(() => { this.enLigne.set(true); this.envoyer(); }));
    window.addEventListener('offline', () => this.zone.run(() => this.enLigne.set(false)));
    this.compter().then(() => this.envoyer());
  }

  apresChaqueEnvoi(rappel: () => Promise<void> | void): void { this.apres.push(rappel); }

  garder<T>(nom: string, valeur: T): Promise<void> {
    return this.copies.deposer(nom, { valeur, enregistree_le: new Date().toISOString() } satisfies CopieHorsLigne<T>);
  }

  relire<T>(nom: string): Promise<CopieHorsLigne<T> | null> {
    return this.copies.lire<CopieHorsLigne<T>>(nom);
  }

  oublier(nom: string): Promise<void> { return this.copies.retirer(nom); }

  /** Met une action en file ; son identifiant garde l'ordre dans lequel elle a été faite. */
  async differer(action: ActionTerrain): Promise<void> {
    const identifiant = `${Date.now().toString().padStart(15, '0')}-${crypto.randomUUID()}`;
    await this.file.deposer(identifiant, action);
    await this.compter();
  }

  /** Comme `differer`, mais remplace l'action du même genre déjà en file : seule ma dernière
   * position compte, inutile d'en rejouer cent au retour du réseau. */
  async remplacer(action: ActionTerrain): Promise<void> {
    for (const { identifiant, valeur } of await this.enFile()) {
      if (valeur.genre === action.genre) await this.file.retirer(identifiant);
    }
    await this.differer(action);
  }

  /** Range les octets d'une photo, chiffrés ; rend la clé à porter dans la file. */
  async garderPhoto(octets: Uint8Array): Promise<string> {
    const cle = `photo-${crypto.randomUUID()}`;
    await this.photos.deposer(cle, versBase64(octets));
    return cle;
  }

  async lirePhoto(cle: string): Promise<Uint8Array<ArrayBuffer> | null> {
    const texte = await this.photos.lire<string>(cle);
    return texte ? depuisBase64(texte) : null;
  }

  /** Les actions en attente, dans l'ordre où elles ont été faites. */
  async enFile(): Promise<{ identifiant: string; valeur: ActionTerrain }[]> {
    return (await this.file.tout<ActionTerrain>()).sort((a, b) => a.identifiant.localeCompare(b.identifiant));
  }

  /** Rejoue la file. S'arrête au premier échec de réseau (on reprendra) ; une action que le
   * serveur refuse (mission close, droits retirés) est retirée et signalée : la rejouer n'y
   * changerait rien. Rend le nombre d'actions parties. */
  envoyer(): Promise<number> {
    this.envoiEnCours ??= this.vider().finally(() => { this.envoiEnCours = null; });
    return this.envoiEnCours;
  }

  oublierLesRefus(): void { this.refus.set([]); }

  private async vider(): Promise<number> {
    let parties = 0;
    for (const { identifiant, valeur } of await this.enFile()) {
      try {
        const motif = await this.rejouer(valeur);
        if (motif) this.signaler(valeur, motif);
        await this.retirer(identifiant, valeur);
        parties++;
      } catch (erreur) {
        if (erreur instanceof HttpErrorResponse && erreur.status >= 400 && erreur.status < 500 && erreur.status !== 401
            && erreur.status !== 408 && erreur.status !== 429) {
          this.signaler(valeur, HorsLigneService.motifDuRefus(erreur));
          await this.retirer(identifiant, valeur);
          continue;
        }
        break;                                          // pas de réseau, serveur indisponible
      }
    }
    await this.compter();
    for (const rappel of this.apres) await Promise.resolve(rappel()).catch(() => {});
    return parties;
  }

  /** Envoie une action. Rend un motif si le serveur l'a reçue mais qu'il faut le signaler. */
  private async rejouer(action: ActionTerrain): Promise<string | null> {
    const api = environment.apiUrl;
    switch (action.genre) {
      case 'statut_mission':
        await firstValueFrom(this.http.patch(`${api}/missions/${action.mission}/`, { statut: action.statut }));
        return null;
      case 'accuse':
        await firstValueFrom(this.http.post(`${api}/mes-notifications/accuser/`, { ids: action.ids, etape: action.etape }));
        return null;
      case 'position':
        await firstValueFrom(this.http.post(`${api}/ma-position/`, { latitude: action.latitude, longitude: action.longitude }));
        return null;
      case 'constat':
        await firstValueFrom(this.http.post(`${api}/habitations/constat/`, action.constat));
        return null;
      case 'photo_constat':
      case 'photo_dossier': {
        const octets = await this.lirePhoto(action.cle);
        if (!octets) return 'Les données de cette photo ne sont plus sur ce téléphone.';
        const formulaire = new FormData();
        if (action.genre === 'photo_constat') formulaire.append('constat', action.constat);
        else formulaire.append('dossier', action.dossier);
        formulaire.append('commentaire', action.commentaire);
        formulaire.append('fichier', new Blob([octets], { type: 'image/jpeg' }), 'photo.jpg');
        const chemin = action.genre === 'photo_constat' ? 'habitations/constat-photo/' : 'documents/';
        const reponse = await firstValueFrom(this.http.post<{ empreinte?: string; sha256?: string }>(`${api}/${chemin}`, formulaire));
        const recue = reponse?.empreinte ?? reponse?.sha256;
        // Le serveur n'a pas reçu les octets qui sont partis d'ici : on ne l'efface pas en silence.
        return recue && recue.toLowerCase() !== action.empreinte.toLowerCase() ? ECART_EMPREINTE : null;
      }
    }
  }

  private async retirer(identifiant: string, action: ActionTerrain): Promise<void> {
    await this.file.retirer(identifiant);
    if (action.genre === 'photo_constat' || action.genre === 'photo_dossier') await this.photos.retirer(action.cle);
  }

  private signaler(action: ActionTerrain, motif: string): void {
    if (action.genre === 'position' || action.genre === 'accuse') return;   // rien que la personne doive reprendre
    const libelle = 'libelle' in action ? action.libelle
      : action.genre === 'statut_mission' ? 'Changement de statut d\'une mission' : 'Envoi';
    this.zone.run(() => this.refus.update(liste => [...liste, { libelle, motif }].slice(-10)));
  }

  private async compter(): Promise<void> {
    const nombre = (await this.file.tout()).length;
    this.zone.run(() => this.enAttente.set(nombre));
  }

  /** À la déconnexion. */
  async effacer(): Promise<void> {
    await Promise.all([this.copies.vider(), this.file.vider(), this.photos.vider()]);
    this.enAttente.set(0);
    this.refus.set([]);
  }

  /** Une erreur HTTP qui veut dire « pas de réseau » (ou serveur injoignable). */
  static estHorsLigne(erreur: unknown): boolean {
    return erreur instanceof HttpErrorResponse && (erreur.status === 0 || erreur.status >= 502);
  }

  /** Le message du serveur s'il en donne un, sinon une phrase générale. */
  static motifDuRefus(erreur: HttpErrorResponse): string {
    const corps = erreur.error as { error?: string; detail?: string } | null;
    return (typeof corps?.error === 'string' && corps.error) || (typeof corps?.detail === 'string' && corps.detail)
      || `Le serveur a refusé cet envoi (erreur ${erreur.status}).`;
  }
}
