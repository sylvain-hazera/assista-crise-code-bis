import { Injectable, computed, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../environments/environment';
import { Crisis } from '../shared/models/crisis.model';

const CLE_CRISE = 'pilotage-crise';

/** Un message de terrain tel que le pilotage le lit (backend/core/views_terrain.py). */
export interface MessageTerrainPilotage {
  id: string;
  auteur_nom: string;
  equipe_nom: string | null;
  type: string;
  type_libelle: string;
  texte: string;
  nombre: number | null;
  canal: string;
  emis_le: string;
  dossier_numero: string | null;
  prioritaire: boolean;
  statut?: string;
  pris_en_compte_le?: string | null;
  pris_en_compte_par_nom?: string | null;
}

/** Les tableaux de situation d'une crise (backend/core/pilotage_situation.py). Un bloc en échec porte `erreur`. */
export interface TableauxSituation {
  debut: string | null;
  calcule_le: string;
  veille: { erreur?: string; vigilance_meteo?: { departement: string; aujourdhui: string; demain: string }[];
            crues?: { nom: string; niveau: string }[];
            stations?: { nom: string; cours_eau: string; hauteur_m: number; le: string | null; evolution_m: number | null }[];
            foyers_24h?: number; foudre_1h?: number };
  accueil: { erreur?: string; centres?: { nom: string; capacite: number | null; presents: number }[]; places?: number; presents?: number;
             mises_en_securite?: { declarations: number; personnes: number; cherchent_un_centre: number };
             relogement?: { en_recherche: number; heberges: number; reloges: number } };
  degats: { erreur?: string; par_statut?: Record<string, number>; evalues?: number; adresses_zone?: number; part_evaluee?: number | null;
            communes?: { commune_code: string; biens: number; touches: number }[] };
  moyens: { erreur?: string; demandes_non_couvertes?: { type: string; nombre: number }[];
            offres_disponibles?: { type: string; nombre: number }[]; renforts_24h?: { demandes: number; personnes: number } };
  radio: { erreur?: string; canal_crise?: { meshtastic: string | null; meshcore: string | null }; a_trier?: number;
           equipes?: { nom: string; indicatif: string | null; transmissions: boolean; meshtastic: boolean; meshcore: boolean;
                       dernier_message_radio: string | null }[] };
}

/** Un centre d'accueil, de transit ou de regroupement des moyens (23/11/2026). */
export interface CentrePilotage {
  id: string; nom: string; type: string | null; type_libelle: string; etat: 'OUVERT' | 'PREVU' | 'FERME';
  ouvert_le: string | null; ferme_le: string | null;
  occupation: { presents: number; capacite: number | null; taux: number | null; presque_plein: boolean; plein: boolean;
                par_type: { type: string; libelle: string; nombre: number }[]; arrivees_24h: number; departs_24h: number };
  manques: { article: string; niveau: string }[];
  equipes: { id: string; nom: string; effectif: number }[];
  sur_place_creneau: number;
  responsables: { nom: string; telephone: string | null }[];
  peut_gerer: boolean; accepte_animaux: boolean;
}
export interface ListeCentres {
  crise: string; alertes: number; centres: CentrePilotage[];
  orientation: { cherchent_un_centre: { declarations: number; personnes: number };
                 relogement: { en_recherche: number; heberges: number; reloges: number } };
}
export interface DetailCentre extends CentrePilotage {
  adresse: string | null;
  registre: { id: string; type: string; libelle: string; nombre: number; arrivee: string | null; nom: string | null; commentaire: string | null }[];
  mouvements: { type: string; libelle: string; nombre: number; arrivee: string | null; depart: string | null }[];
  stock: { item: string; article: string; quantite: number; niveau: string | null; unite: string }[];
  planning: { membre: string; creneau: string }[];
  categories: { type: string; libelle: string }[];
}

/** Un message radio du pot commun (23/11/2026) : arrivé sans destinataire, à ranger. */
export interface MessageATrier {
  id: string; texte: string; auteur: string; source: string; recu_par: number; emis_le: string;
}
export interface PotCommun {
  conversation: string; trie_par: 'TRANSMISSIONS' | 'REGULATION';
  messages: MessageATrier[]; equipes: { id: string; nom: string; indicatif: string | null }[];
}

/** Le terrain en direct d'une crise : alertes à prendre en compte, statuts, derniers messages. */
export interface VueTerrain {
  alertes: MessageTerrainPilotage[];
  statuts: MessageTerrainPilotage[];
  derniers: MessageTerrainPilotage[];
}

/**
 * Ce que partage l'espace Pilotage : la crise suivie. Choisie une fois, elle vaut pour tous les
 * écrans (situation, cellule, carte, dossiers) et elle est retenue sur l'appareil : le directeur
 * des opérations rouvre l'iPad sur sa crise. Un identifiant de crise n'a rien de personnel.
 */
@Injectable({ providedIn: 'root' })
export class PilotageService {
  readonly crises = signal<Crisis[]>([]);
  readonly criseId = signal<string | null>(PilotageService.lire());
  readonly crise = computed(() => this.crises().find(c => c.id === this.criseId()) ?? null);

  /** Le terrain en direct de la crise suivie, relu toutes les 30 s (23/11/2026). */
  readonly terrain = signal<VueTerrain | null>(null);
  readonly alertesTerrain = computed(() => this.terrain()?.alertes.length ?? 0);
  /** Le prochain point de situation dû (cadence fixée par la cellule), relu avec le terrain. */
  readonly pointDu = signal<{ du: boolean; prochain: string | null } | null>(null);
  /** Le pot commun des messages radio sans destinataire ; null si ce compte ne trie pas. */
  readonly potCommun = signal<PotCommun | null>(null);
  readonly aTrier = computed(() => this.potCommun()?.messages.length ?? 0);
  /** Les centres de la crise, relus avec le terrain ; la pastille compte ceux qui demandent attention. */
  readonly centres = signal<ListeCentres | null>(null);
  readonly alertesCentres = computed(() => this.centres()?.alertes ?? 0);

  constructor(private http: HttpClient) {}

  situation(crise: string) {
    return this.http.get<TableauxSituation>(`${environment.apiUrl}/pilotage/situation/`, { params: { crise } });
  }

  rafraichirTerrain(): void {
    const crise = this.criseId();
    if (!crise) { this.terrain.set(null); this.pointDu.set(null); this.potCommun.set(null); this.centres.set(null); return; }
    this.rafraichirCentres();
    this.http.get<PotCommun>(`${environment.apiUrl}/conversations/a-trier/`, { params: { crise } }).subscribe({
      next: p => this.potCommun.set(p),
      error: () => this.potCommun.set(null),   // ni transmissions ni régulation : pas de tri
    });
    this.http.get<{ du: boolean; prochain: string | null }>(`${environment.apiUrl}/cellule/points/`, { params: { crise } }).subscribe({
      next: e => this.pointDu.set({ du: e.du, prochain: e.prochain }),
      error: () => this.pointDu.set(null),   // cellule non tenue par cette institution : pas de rappel
    });
    this.http.get<VueTerrain>(`${environment.apiUrl}/messages-terrain/crise/`, { params: { crise } }).subscribe({
      next: v => this.terrain.set(v),
      error: () => { /* réseau ou droits : on garde la dernière vue */ },
    });
  }

  prendreEnCompte(id: string): Promise<MessageTerrainPilotage> {
    return firstValueFrom(this.http.post<MessageTerrainPilotage>(`${environment.apiUrl}/messages-terrain/${id}/prendre-en-compte/`, {}))
      .then(m => { this.rafraichirTerrain(); return m; });
  }

  rafraichirCentres(): void {
    const crise = this.criseId();
    if (!crise) { this.centres.set(null); return; }
    this.http.get<ListeCentres>(`${environment.apiUrl}/pilotage/centres/`, { params: { crise } }).subscribe({
      next: l => this.centres.set(l),
      error: () => { /* réseau ou droits : on garde la dernière vue */ },
    });
  }

  centre(id: string): Promise<DetailCentre> {
    return firstValueFrom(this.http.get<DetailCentre>(`${environment.apiUrl}/pilotage/centres/${id}/`));
  }

  /** Ouvrir, fermer un centre, ou ajuster sa capacité. */
  etatCentre(id: string, geste: 'ouvrir' | 'fermer' | null, capacite?: number | null): Promise<DetailCentre> {
    const corps: Record<string, unknown> = {};
    if (geste) corps['geste'] = geste;
    if (capacite !== undefined && capacite !== null) corps['capacite'] = capacite;
    return firstValueFrom(this.http.post<DetailCentre>(`${environment.apiUrl}/pilotage/centres/${id}/etat/`, corps))
      .then(d => { this.rafraichirCentres(); return d; });
  }

  /** Une arrivée au registre de présence (API existante). */
  arrivee(point: string, typePersonne: string, nombre: number, nom = '', commentaire = ''): Promise<unknown> {
    const corps: Record<string, unknown> = { point, type_personne: typePersonne, nombre };
    if (nom.trim()) corps['nom'] = nom.trim();
    if (commentaire.trim()) corps['commentaire'] = commentaire.trim();
    return firstValueFrom(this.http.post(`${environment.apiUrl}/registre-presences/`, corps)).then(r => { this.rafraichirCentres(); return r; });
  }

  sortie(ligne: string): Promise<unknown> {
    return firstValueFrom(this.http.post(`${environment.apiUrl}/registre-presences/${ligne}/sortie/`, {}))
      .then(r => { this.rafraichirCentres(); return r; });
  }

  /** Recevoir, distribuer ou compter un article du stock du centre (API existante). */
  gesteStock(point: string, geste: 'recevoir' | 'distribuer' | 'compter', item: string, quantite: number): Promise<unknown> {
    return firstValueFrom(this.http.post(`${environment.apiUrl}/stocks/points/${point}/${geste}/`, { item, quantite }));
  }

  /** Range un message du pot commun : vers une équipe, un dossier, ou classé sans suite. */
  ranger(message: string, cible: { equipe?: string; dossier?: string; classer?: boolean }): Promise<unknown> {
    return firstValueFrom(this.http.post(`${environment.apiUrl}/conversations/a-trier/${message}/ranger/`, cible))
      .then(r => { this.rafraichirTerrain(); return r; });
  }

  /** Les crises ouvertes ; garde la crise choisie si elle l'est encore, sinon la première. */
  async chargerCrises(): Promise<void> {
    const crises = (await firstValueFrom(this.http.get<Crisis[]>(`${environment.apiUrl}/crises/`)))
      .filter(c => c.is_open !== false);
    this.crises.set(crises);
    if (!crises.some(c => c.id === this.criseId())) this.choisir(crises[0]?.id ?? null);
  }

  choisir(id: string | null): void {
    this.criseId.set(id);
    try {
      if (id) localStorage.setItem(CLE_CRISE, id); else localStorage.removeItem(CLE_CRISE);
    } catch { /* stockage indisponible : le choix vaut pour la séance */ }
  }

  private static lire(): string | null {
    try { return localStorage.getItem(CLE_CRISE); } catch { return null; }
  }
}
