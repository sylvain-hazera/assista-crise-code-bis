/** Contraste WCAG 2.1 pour la marque blanche.
 *
 * Une institution choisit sa couleur primaire pour un fond clair ; rien ne garantit qu'elle
 * reste lisible sur le fond sombre (--ac-surface) ni que du blanc passe dessus. Plutôt que de
 * valider chaque branding à la main, on dérive au runtime deux couleurs sûres :
 *
 *   --brand-primary          couleur brute, telle que déclarée (fonds, aplats)
 *   --brand-primary-lisible  la même, éclaircie/assombrie jusqu'à 4.5:1 sur le fond du thème
 *                            courant -- à utiliser pour TOUT texte, icône ou bordure fine
 *   --brand-on-primary       le texte à poser SUR --brand-primary (blanc ou encre)
 *
 * Seuil 4.5:1 = WCAG AA pour le texte normal. On ne vise pas AAA : une couleur de marque
 * poussée à 7:1 ne ressemble plus à la marque.
 */

export interface Rgb { r: number; g: number; b: number; }

/** Encre utilisée quand la couleur de marque est trop claire pour porter du blanc. */
export const ENCRE = '#111827';
export const BLANC = '#ffffff';

/** Accepte « #abc », « #aabbcc » et les mêmes sans dièse. Renvoie null si illisible --
 * l'appelant retombe alors sur la couleur par défaut plutôt que de poser du vide. */
export function hexVersRgb(hex: string): Rgb | null {
  if (typeof hex !== 'string') return null;
  const brut = hex.trim().replace(/^#/, '');
  const complet = brut.length === 3 ? brut.split('').map((c) => c + c).join('') : brut;
  if (!/^[0-9a-fA-F]{6}$/.test(complet)) return null;
  return {
    r: parseInt(complet.slice(0, 2), 16),
    g: parseInt(complet.slice(2, 4), 16),
    b: parseInt(complet.slice(4, 6), 16),
  };
}

export function rgbVersHex({ r, g, b }: Rgb): string {
  const deux = (n: number) => Math.round(Math.min(255, Math.max(0, n))).toString(16).padStart(2, '0');
  return `#${deux(r)}${deux(g)}${deux(b)}`;
}

/** Luminance relative WCAG 2.1 (§ relative luminance). */
export function luminanceRelative({ r, g, b }: Rgb): number {
  const canal = (valeur: number) => {
    const c = valeur / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b);
}

/** Rapport de contraste WCAG, de 1 (identiques) à 21 (noir sur blanc). */
export function rapportContraste(a: Rgb, b: Rgb): number {
  const la = luminanceRelative(a);
  const lb = luminanceRelative(b);
  const clair = Math.max(la, lb);
  const sombre = Math.min(la, lb);
  return (clair + 0.05) / (sombre + 0.05);
}

/** Le texte à poser sur `fond` : blanc ou encre, celui qui contraste le mieux. */
export function texteLisibleSur(fond: string): string {
  const rgb = hexVersRgb(fond);
  if (!rgb) return BLANC;
  const surBlanc = rapportContraste(rgb, hexVersRgb(BLANC)!);
  const surEncre = rapportContraste(rgb, hexVersRgb(ENCRE)!);
  return surBlanc >= surEncre ? BLANC : ENCRE;
}

function rgbVersHsl({ r, g, b }: Rgb): { h: number; s: number; l: number } {
  const rn = r / 255, vn = g / 255, bn = b / 255;
  const max = Math.max(rn, vn, bn), min = Math.min(rn, vn, bn);
  const l = (max + min) / 2;
  if (max === min) return { h: 0, s: 0, l };
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  if (max === rn) h = ((vn - bn) / d + (vn < bn ? 6 : 0)) / 6;
  else if (max === vn) h = ((bn - rn) / d + 2) / 6;
  else h = ((rn - vn) / d + 4) / 6;
  return { h, s, l };
}

function hslVersRgb(h: number, s: number, l: number): Rgb {
  if (s === 0) return { r: l * 255, g: l * 255, b: l * 255 };
  const vers = (p: number, q: number, t: number) => {
    let tt = t;
    if (tt < 0) tt += 1;
    if (tt > 1) tt -= 1;
    if (tt < 1 / 6) return p + (q - p) * 6 * tt;
    if (tt < 1 / 2) return q;
    if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6;
    return p;
  };
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  return { r: vers(p, q, h + 1 / 3) * 255, g: vers(p, q, h) * 255, b: vers(p, q, h - 1 / 3) * 255 };
}

/** Éclaircit (fond sombre) ou assombrit (fond clair) `couleur` par pas de 1 % de luminosité
 * HSL jusqu'à atteindre `cible`. La teinte et la saturation sont conservées : la couleur reste
 * reconnaissable comme celle de la marque. Si la cible reste hors d'atteinte (teinte très
 * saturée sur un fond intermédiaire), on rend le meilleur essai -- jamais du blanc pur ni du
 * noir, qui effaceraient la marque. */
export function ajusterPourFond(couleur: string, fond: string, cible = 4.5): string {
  const rgb = hexVersRgb(couleur);
  const rgbFond = hexVersRgb(fond);
  if (!rgb || !rgbFond) return couleur;
  if (rapportContraste(rgb, rgbFond) >= cible) return rgbVersHex(rgb);

  const { h, s } = rgbVersHsl(rgb);
  const fondSombre = luminanceRelative(rgbFond) < 0.18;
  const { l: lDepart } = rgbVersHsl(rgb);

  let meilleur = rgbVersHex(rgb);
  let meilleurRapport = rapportContraste(rgb, rgbFond);

  // Bornes : on ne dépasse pas 0.95 (quasi-blanc) ni 0.12 (quasi-noir).
  for (let pas = 1; pas <= 100; pas++) {
    const l = fondSombre
      ? Math.min(0.95, lDepart + pas / 100)
      : Math.max(0.12, lDepart - pas / 100);
    const candidat = hslVersRgb(h, s, l);
    const rapport = rapportContraste(candidat, rgbFond);
    if (rapport > meilleurRapport) {
      meilleurRapport = rapport;
      meilleur = rgbVersHex(candidat);
    }
    if (rapport >= cible) return rgbVersHex(candidat);
    // Butee orientee : en eclaircissant on part parfois d'un l tres bas (noir), en
    // assombrissant d'un l tres haut (blanc) -- tester les deux bornes sortirait au 1er tour.
    if (fondSombre ? l >= 0.95 : l <= 0.12) break;
  }
  return meilleur;
}
