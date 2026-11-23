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
  radio: { erreur?: string; equipes?: { nom: string; meshtastic: boolean; meshcore: boolean; dernier_message_radio: string | null }[] };
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

  constructor(private http: HttpClient) {}

  situation(crise: string) {
    return this.http.get<TableauxSituation>(`${environment.apiUrl}/pilotage/situation/`, { params: { crise } });
  }

  rafraichirTerrain(): void {
    const crise = this.criseId();
    if (!crise) { this.terrain.set(null); this.pointDu.set(null); return; }
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
