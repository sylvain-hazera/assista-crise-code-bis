/** Tri et filtrage d'un tableau HTML, colonne par colonne.
 *
 * Écrit une fois pour toutes plutôt que recopié par tableau : la page des companions Meshtastic
 * en compte quatre, et « toutes les colonnes triables et filtrables » recopié quatre fois
 * divergerait au premier correctif.
 *
 * Trois décisions qui ne sont pas des détails :
 *
 * 1. **Les valeurs inconnues restent en dernier, dans les deux sens.** Un `null` trié comme une
 *    valeur minimale remonterait en tête d'un tri croissant : « nœud jamais entendu » se
 *    retrouverait avant « entendu il y a une minute ». Un vide n'est pas une petite valeur,
 *    c'est une absence de valeur.
 *
 * 2. **Comparaison insensible à la casse ET aux accents.** En français, filtrer « elysee » doit
 *    trouver « Élysée », et trier doit placer « Étang » entre « Esker » et « Évier » — ce que
 *    `<` sur des chaînes ne fait pas (les lettres accentuées sont après `z` en UTF-16).
 *
 * 3. **Le tri porte sur la valeur, le filtre sur le texte affiché.** Une date se trie
 *    chronologiquement mais se filtre telle qu'elle est lue à l'écran ; un booléen se trie
 *    faux-puis-vrai mais se filtre en tapant « oui ». D'où deux accesseurs par colonne, le
 *    second facultatif.
 */

export type ValeurColonne = string | number | boolean | Date | null | undefined;

export interface ColonneTriFiltre<T> {
  /** Valeur de tri : nombre, date, booléen ou texte. `null`/`undefined` = inconnu. */
  valeur: (ligne: T) => ValeurColonne;
  /** Texte cherché par le filtre de colonne et la recherche globale. Défaut : rendu de `valeur`. */
  texte?: (ligne: T) => string;
}

/** Minuscules sans accents : base commune du tri et du filtrage. */
export function normaliser(valeur: unknown): string {
  if (valeur === null || valeur === undefined) return '';
  return String(valeur).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
}

function texteParDefaut(valeur: ValeurColonne): string {
  if (valeur === null || valeur === undefined) return '';
  if (typeof valeur === 'boolean') return valeur ? 'oui' : 'non';
  if (valeur instanceof Date) return valeur.toLocaleString('fr-FR');
  return String(valeur);
}

export class TableTriFiltre<T> {

  /** Colonne de tri courante ; null = ordre d'arrivée du serveur, qui a souvent un sens. */
  cle: string | null = null;
  sens: 1 | -1 = 1;

  /** Recherche globale : s'applique à toutes les colonnes déclarées. */
  recherche = '';
  /** Filtre par colonne, cumulatif avec la recherche globale (ET, pas OU). */
  filtres: Record<string, string> = {};

  constructor(
    private readonly colonnes: Record<string, ColonneTriFiltre<T>>,
    cleInitiale: string | null = null,
    sensInitial: 1 | -1 = 1,
  ) {
    this.cle = cleInitiale;
    this.sens = sensInitial;
  }

  /** Clic sur un en-tête : croissant, puis décroissant, puis retour à l'ordre du serveur. */
  basculer(cle: string): void {
    if (this.cle !== cle) { this.cle = cle; this.sens = 1; return; }
    if (this.sens === 1) { this.sens = -1; return; }
    this.cle = null;
    this.sens = 1;
  }

  indicateur(cle: string): string {
    if (this.cle !== cle) return '';
    return this.sens === 1 ? '▲' : '▼';
  }

  /** Pour `aria-sort`, afin qu'un lecteur d'écran annonce l'état de la colonne. */
  ariaSort(cle: string): 'ascending' | 'descending' | 'none' {
    if (this.cle !== cle) return 'none';
    return this.sens === 1 ? 'ascending' : 'descending';
  }

  get filtreActif(): boolean {
    return !!this.recherche.trim() || Object.values(this.filtres).some(v => !!(v || '').trim());
  }

  reinitialiser(): void {
    this.recherche = '';
    this.filtres = {};
  }

  private texte(cle: string, ligne: T): string {
    const colonne = this.colonnes[cle];
    if (!colonne) return '';
    return colonne.texte ? colonne.texte(ligne) : texteParDefaut(colonne.valeur(ligne));
  }

  /** Filtre puis trie. Appelé depuis un getter du composant : les tableaux visés comptent des
   * centaines de lignes, pas des millions — le coût est négligeable devant un cache à invalider
   * à la main, qui finirait par afficher des données périmées. */
  appliquer(lignes: T[]): T[] {
    const recherche = normaliser(this.recherche.trim());
    const filtres = Object.entries(this.filtres)
      .map(([cle, valeur]) => [cle, normaliser((valeur || '').trim())] as const)
      .filter(([, valeur]) => valeur.length > 0);

    let resultat = lignes;
    if (recherche || filtres.length) {
      resultat = lignes.filter(ligne => {
        for (const [cle, attendu] of filtres) {
          if (!normaliser(this.texte(cle, ligne)).includes(attendu)) return false;
        }
        if (!recherche) return true;
        return Object.keys(this.colonnes).some(
          cle => normaliser(this.texte(cle, ligne)).includes(recherche));
      });
    }

    const cle = this.cle;
    if (!cle || !this.colonnes[cle]) return resultat;
    const lire = this.colonnes[cle].valeur;
    // Copie : trier sur place réordonnerait le tableau du composant, et donc la source de
    // vérité, au gré de l'affichage.
    return [...resultat].sort((a, b) => {
      const gauche = lire(a);
      const droite = lire(b);
      // Les inconnus sont écartés AVANT l'inversion de sens : les traiter comme une valeur
      // comparable les ferait passer en tête du tri décroissant, où « jamais entendu »
      // ressemblerait au plus récent.
      const gaucheVide = estVide(gauche);
      const droiteVide = estVide(droite);
      if (gaucheVide || droiteVide) {
        return gaucheVide && droiteVide ? 0 : (gaucheVide ? 1 : -1);
      }
      return this.sens * comparer(gauche, droite);
    });
  }
}

function estVide(valeur: ValeurColonne): boolean {
  return valeur === null || valeur === undefined || valeur === '';
}

/** Compare deux valeurs NON vides — les absences sont traitées par l'appelant. */
function comparer(a: ValeurColonne, b: ValeurColonne): number {
  if (a instanceof Date || b instanceof Date) {
    return Number(a instanceof Date ? a : new Date(String(a)))
      - Number(b instanceof Date ? b : new Date(String(b)));
  }
  if (typeof a === 'boolean' || typeof b === 'boolean') {
    return Number(a) - Number(b);
  }
  if (typeof a === 'number' && typeof b === 'number') {
    return a - b;
  }
  return normaliser(a).localeCompare(normaliser(b), 'fr');
}
