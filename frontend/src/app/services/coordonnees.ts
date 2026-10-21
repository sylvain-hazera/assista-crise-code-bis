/**
 * Les LISTES d'annonces (offres, demandes, informations) arrivent sans email ni téléphone : ils
 * ne viennent qu'avec la fiche ouverte, dont la consultation est tracée objet par objet dans la
 * main courante (voir backend/core/tracabilite.py). Un écran qui doit afficher les coordonnées
 * directement dans un tableau les demande explicitement avec ce paramètre ; sa consultation est
 * alors tracée comme « liste avec coordonnées ».
 */
export const AVEC_COORDONNEES: Record<string, string> = { avec_coordonnees: '1' };
