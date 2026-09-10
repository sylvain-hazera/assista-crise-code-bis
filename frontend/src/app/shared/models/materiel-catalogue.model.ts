export interface MaterielCatalogue {
  id: string;
  nom: string;
  categorie?: string | null;
  /** Sous-matériel : regroupement libre optionnel (distinct de `categorie` ci-dessus, dédiée
   * au stock des centres) — voir Besoin.parent/Competence.parent, même patron. */
  parent?: string | null;
  actif?: boolean;
  date_creation?: string;
}

/** Mêmes valeurs/libellés que MaterielCatalogueCategorie (backend/core/models.py) — à tenir
 * synchronisé à la main en cas d'ajout de catégorie, même patron que NIVEAUX (materiel-point).
 * ENGIN n'y figure pas : rubrique dédiée au formulaire public (propose-help-form), jamais
 * affichée dans le sélecteur de stock d'un centre. */
export const CATEGORIES_MATERIEL_STOCK: { code: string; libelle: string }[] = [
  { code: 'NETTOYAGE', libelle: 'Nettoyage et remise en état' },
  { code: 'POMPAGE', libelle: "Pompage et évacuation d'eau" },
  { code: 'DEBLAI_MANUTENTION', libelle: 'Déblaiement et manutention' },
  { code: 'ENERGIE_ECLAIRAGE', libelle: 'Énergie et éclairage' },
  { code: 'PROTECTION_BATIMENTS', libelle: 'Protection des bâtiments' },
  { code: 'OUTILLAGE_TERRAIN', libelle: 'Outillage et équipement de terrain' },
  { code: 'PROTECTION_INDIVIDUELLE', libelle: 'Protection individuelle' },
  { code: 'ACCUEIL_HEBERGEMENT', libelle: "Accueil et hébergement d'urgence" },
  { code: 'DIVERS', libelle: 'Divers / consommables' },
];

export const CATEGORIE_MATERIEL_NON_CLASSE = { code: null as string | null, libelle: 'Autres besoins' };
