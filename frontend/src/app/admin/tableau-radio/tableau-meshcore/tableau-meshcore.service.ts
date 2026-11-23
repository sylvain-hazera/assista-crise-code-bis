import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';

export type FenetreMeshCore = '6h' | '24h' | '7j';

/** backend/core/tableau_meshcore.py */
export interface TableauMeshCore {
  fenetre: FenetreMeshCore;
  calcule_le: string;
  trafic: {
    total: number;
    par_type: { type: string; trames: number }[];
    courbe: { debut: string; trames: number }[];
    pas_heures: number;
    recepteurs: { pubkey: string; nom: string; trames: number; derniere_heure: string | null }[];
  };
  liaisons: { reception_directe: number; chemins: number; voisinage: number; emetteurs_entendus: number; recepteurs: number };
  relais_publics: {
    repeteurs: number; repeteurs_vus: number; rooms: number; instances: string[]; derniere_import: string | null;
    plus_utiles: { pubkey: string; nom: string; score: number; note: string; actif: boolean; dernier_vu: string | null }[];
  };
  observateurs: {
    pubkey: string; nom: string; iata: string; recu_le: string; silencieux: boolean;
    mesures: Record<string, number>; autres_mesures: number; trames: number;
  }[];
  sources: { nom: string; type: string; actif: boolean; etat: string | null; derniere_connexion: string | null }[];
}

@Injectable({ providedIn: 'root' })
export class TableauMeshCoreService {
  constructor(private http: HttpClient) {}

  charger(fenetre: FenetreMeshCore): Observable<TableauMeshCore> {
    return this.http.get<TableauMeshCore>(`${environment.apiUrl}/tableau-radio-meshcore/`, { params: { fenetre } });
  }
}
