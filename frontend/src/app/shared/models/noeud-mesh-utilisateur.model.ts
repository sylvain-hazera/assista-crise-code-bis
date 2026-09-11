export interface NoeudMeshUtilisateur {
  id: string;
  utilisateur: string;
  utilisateur_nom?: string;
  pubkey_hex: string;
  nom_noeud?: string;
  actif: boolean;
  date_association?: string;
}
