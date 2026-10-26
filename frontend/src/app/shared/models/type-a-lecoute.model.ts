import { Besoin } from './besoin.model';

export type AxeTypeALecoute = 'request' | 'offer' | 'information';

export interface TypesALecoute {
  besoins: Besoin[];
  type_ids: string[];
  /** Vrai quand aucun thème déclaré ne correspond à un type de ce formulaire : le catalogue
   * complet est alors renvoyé pour que le visiteur puisse quand même déposer (voir
   * TypesALecouteView côté backend), et le formulaire le lui dit. */
  repli?: boolean;
}
