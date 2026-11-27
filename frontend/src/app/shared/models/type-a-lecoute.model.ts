import { Besoin } from './besoin.model';

export type AxeTypeALecoute = 'request' | 'offer' | 'information';

export interface TypesALecoute {
  besoins: Besoin[];
  type_ids: string[];
  /** Vrai quand aucun thème déclaré ne correspond à un type de ce formulaire : le catalogue
   * complet est alors renvoyé pour que le visiteur puisse quand même déposer (voir
   * TypesALecouteView côté backend), et le formulaire le lui dit. */
  repli?: boolean;
  /** Classement « quoi + pour qui » (27/11/2026) : par id de type, les « pour qui » admis et
   * écoutés ; et les catégories d'animaux écoutées (absentes : toutes). */
  beneficiaires_par_type?: Record<string, string[]>;
  categories_animaux_par_type?: Record<string, string[]>;
}
