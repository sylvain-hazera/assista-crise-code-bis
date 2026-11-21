import { Releve } from '../position/regles-suivi';

/**
 * De la prise de vue aux octets qui partiront : réduire, dater, situer, sceller
 * (DOSSIER-PWA-INTERVENANTS.md, lot 5). La moitié « téléphone » du circuit de traçabilité du
 * serveur, comme `Photographe.kt` sur Android :
 *
 * - la position est **inscrite dans la photo** (EXIF, sous-IFD GPS), au moment de la prise : la
 *   réduction d'image par le navigateur efface tout ce que l'appareil photo avait écrit, et Safari
 *   retire de toute façon la position d'une photo confiée à une page ;
 * - l'empreinte SHA-256 est calculée **ici**, sur les octets définitifs, pour être comparée à
 *   celle que le serveur calcule à réception : si elles diffèrent, ce qu'il a reçu n'est pas ce
 *   qui a été pris.
 *
 * La photo ne passe pas par la photothèque : elle est prise par le champ « appareil photo » de
 * la page, réduite en mémoire, puis gardée chiffrée jusqu'à son envoi.
 */

export const COTE_MAX = 2048;
export const QUALITE = 0.85;

export interface PhotoPrete {
  octets: Uint8Array<ArrayBuffer>;
  empreinte: string;
  prise_le: string;
  latitude: number | null;
  longitude: number | null;
  precision_m: number | null;
}

// ── EXIF ──────────────────────────────────────────────────────────────────────────────────

const BYTE = 1, ASCII = 2, LONG = 4, RATIONAL = 5;
const TAILLE_TYPE: Record<number, number> = { [BYTE]: 1, [ASCII]: 1, [LONG]: 4, [RATIONAL]: 8 };

interface Entree { tag: number; type: number; valeurs: number[] | string; }

function octetsDe(e: Entree): Uint8Array {
  if (e.type === ASCII) {
    const texte = (e.valeurs as string).replace(/[^\x20-\x7e]/g, '?');
    const sortie = new Uint8Array(texte.length + 1);
    for (let i = 0; i < texte.length; i++) sortie[i] = texte.charCodeAt(i);
    return sortie;                                           // terminé par un octet nul
  }
  const valeurs = e.valeurs as number[];
  const sortie = new Uint8Array(valeurs.length * TAILLE_TYPE[e.type]);
  const vue = new DataView(sortie.buffer);
  valeurs.forEach((v, i) => {
    if (e.type === BYTE) vue.setUint8(i, v);
    else vue.setUint32(i * 4, v, true);                     // LONG, et chaque moitié d'un RATIONAL
  });
  return sortie;
}

function nombreDe(e: Entree): number {
  return e.type === ASCII ? (e.valeurs as string).length + 1
    : e.type === RATIONAL ? (e.valeurs as number[]).length / 2 : (e.valeurs as number[]).length;
}

function tailleIfd(entrees: Entree[]): number {
  const donnees = entrees.map(octetsDe).filter(o => o.length > 4).reduce((s, o) => s + o.length + (o.length % 2), 0);
  return 2 + 12 * entrees.length + 4 + donnees;
}

/** Écrit une IFD (petit-boutiste) à la position `debut` du bloc TIFF. */
function ecrireIfd(tiff: DataView, debut: number, entrees: Entree[]): void {
  const triees = [...entrees].sort((a, b) => a.tag - b.tag);  // la norme veut l'ordre croissant
  tiff.setUint16(debut, triees.length, true);
  let donnees = debut + 2 + 12 * triees.length + 4;
  triees.forEach((e, i) => {
    const o = debut + 2 + 12 * i;
    const octets = octetsDe(e);
    tiff.setUint16(o, e.tag, true);
    tiff.setUint16(o + 2, e.type, true);
    tiff.setUint32(o + 4, nombreDe(e), true);
    if (octets.length <= 4) {
      octets.forEach((b, j) => tiff.setUint8(o + 8 + j, b));
    } else {
      tiff.setUint32(o + 8, donnees, true);
      octets.forEach((b, j) => tiff.setUint8(donnees + j, b));
      donnees += octets.length + (octets.length % 2);
    }
  });
  tiff.setUint32(debut + 2 + 12 * triees.length, 0, true);  // pas d'IFD suivante
}

const deux = (n: number) => String(n).padStart(2, '0');

/** « AAAA:MM:JJ HH:MM:SS », à l'heure locale (champs date de l'EXIF). */
export function dateExif(instant: number): string {
  const d = new Date(instant);
  return `${d.getFullYear()}:${deux(d.getMonth() + 1)}:${deux(d.getDate())} ${deux(d.getHours())}:${deux(d.getMinutes())}:${deux(d.getSeconds())}`;
}

/** Degrés décimaux en degrés, minutes, secondes au millième : trois rationnels. */
function dms(valeur: number): number[] {
  const absolu = Math.abs(valeur);
  const degres = Math.floor(absolu);
  const minutes = Math.floor((absolu - degres) * 60);
  const secondes = Math.round(((absolu - degres) * 60 - minutes) * 60 * 1000);
  return [degres, 1, minutes, 1, secondes, 1000];
}

/**
 * Le bloc APP1 « Exif » : heure de la prise (champ principal et champ d'origine), logiciel, et
 * si on l'a, la position avec son heure en temps universel et sa précision — c'est elle qui dit
 * si la position est bien celle du moment de la photo.
 */
export function segmentExif(instant: number, logiciel: string, position: Releve | null): Uint8Array<ArrayBuffer> {
  const date = dateExif(instant);
  const exif: Entree[] = [{ tag: 0x9003, type: ASCII, valeurs: date }];   // DateTimeOriginal
  let gps: Entree[] = [];
  if (position) {
    const u = new Date(position.instant);
    gps = [
      { tag: 0x0000, type: BYTE, valeurs: [2, 3, 0, 0] },                                   // GPSVersionID
      { tag: 0x0001, type: ASCII, valeurs: position.latitude >= 0 ? 'N' : 'S' },
      { tag: 0x0002, type: RATIONAL, valeurs: dms(position.latitude) },
      { tag: 0x0003, type: ASCII, valeurs: position.longitude >= 0 ? 'E' : 'W' },
      { tag: 0x0004, type: RATIONAL, valeurs: dms(position.longitude) },
      { tag: 0x0007, type: RATIONAL, valeurs: [u.getUTCHours(), 1, u.getUTCMinutes(), 1, u.getUTCSeconds(), 1] },
      { tag: 0x001d, type: ASCII, valeurs: `${u.getUTCFullYear()}:${deux(u.getUTCMonth() + 1)}:${deux(u.getUTCDate())}` },
      { tag: 0x001f, type: RATIONAL, valeurs: [Math.round(Math.max(0, position.precision_m) * 100), 100] },
    ];
  }
  // Les pointeurs ont une taille fixe : on peut calculer les positions avant d'écrire.
  const ifd0Sans: Entree[] = [
    { tag: 0x0131, type: ASCII, valeurs: logiciel },                                        // Software
    { tag: 0x0132, type: ASCII, valeurs: date },                                            // DateTime
    { tag: 0x8769, type: LONG, valeurs: [0] },                                              // pointeur Exif
    ...(gps.length ? [{ tag: 0x8825, type: LONG, valeurs: [0] }] : []),                     // pointeur GPS
  ];
  const debutExif = 8 + tailleIfd(ifd0Sans);
  const debutGps = debutExif + tailleIfd(exif);
  const ifd0 = ifd0Sans.map(e => e.tag === 0x8769 ? { ...e, valeurs: [debutExif] }
    : e.tag === 0x8825 ? { ...e, valeurs: [debutGps] } : e);
  const tailleTiff = debutGps + (gps.length ? tailleIfd(gps) : 0);

  const segment = new Uint8Array(new ArrayBuffer(4 + 6 + tailleTiff));
  const vue = new DataView(segment.buffer);
  vue.setUint16(0, 0xffe1);
  vue.setUint16(2, 2 + 6 + tailleTiff);                     // longueur, gros-boutiste, sans le marqueur
  segment.set([0x45, 0x78, 0x69, 0x66, 0, 0], 4);           // « Exif\0\0 »
  const tiff = new DataView(segment.buffer, 10);
  tiff.setUint16(0, 0x4949);                                // « II » : petit-boutiste
  tiff.setUint16(2, 42, true);
  tiff.setUint32(4, 8, true);
  ecrireIfd(tiff, 8, ifd0);
  ecrireIfd(tiff, debutExif, exif);
  if (gps.length) ecrireIfd(tiff, debutGps, gps);
  return segment;
}

/** Insère le bloc EXIF dans un JPEG : après le début d'image, et après l'en-tête JFIF s'il y en a
 * un (c'est ce qu'écrit un canevas). Un ancien bloc EXIF éventuel est retiré. */
export function insererExif(jpeg: Uint8Array, segment: Uint8Array): Uint8Array<ArrayBuffer> {
  if (jpeg[0] !== 0xff || jpeg[1] !== 0xd8) throw new Error('Ce n\'est pas un JPEG.');
  const morceaux: Uint8Array[] = [jpeg.subarray(0, 2)];
  let i = 2;
  let insere = false;
  while (i + 4 <= jpeg.length && jpeg[i] === 0xff && jpeg[i + 1] >= 0xe0 && jpeg[i + 1] <= 0xef) {
    const longueur = (jpeg[i + 2] << 8) | jpeg[i + 3];
    const bloc = jpeg.subarray(i, i + 2 + longueur);
    const estExif = jpeg[i + 1] === 0xe1 && bloc[4] === 0x45 && bloc[5] === 0x78 && bloc[6] === 0x69 && bloc[7] === 0x66;
    if (jpeg[i + 1] === 0xe0) morceaux.push(bloc);
    if (!insere && jpeg[i + 1] !== 0xe0) { morceaux.push(segment); insere = true; }
    if (!estExif && jpeg[i + 1] !== 0xe0) morceaux.push(bloc);
    i += 2 + longueur;
  }
  if (!insere) morceaux.push(segment);
  morceaux.push(jpeg.subarray(i));
  const sortie = new Uint8Array(new ArrayBuffer(morceaux.reduce((s, m) => s + m.length, 0)));
  let o = 0;
  for (const m of morceaux) { sortie.set(m, o); o += m.length; }
  return sortie;
}

export async function empreinte(octets: Uint8Array<ArrayBuffer>): Promise<string> {
  const condensat = new Uint8Array(await crypto.subtle.digest('SHA-256', octets));
  return Array.from(condensat, b => b.toString(16).padStart(2, '0')).join('');
}

// ── La prise ──────────────────────────────────────────────────────────────────────────────

/** Les dimensions réduites : 2048 px au plus sur le grand côté, jamais agrandies. */
export function dimensionsReduites(largeur: number, hauteur: number, coteMax = COTE_MAX): [number, number] {
  const echelle = Math.min(1, coteMax / Math.max(largeur, hauteur));
  return [Math.max(1, Math.round(largeur * echelle)), Math.max(1, Math.round(hauteur * echelle))];
}

function chargerImage(fichier: Blob): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const adresse = URL.createObjectURL(fichier);
    const image = new Image();
    // Le navigateur redresse l'image selon son orientation EXIF avant de la dessiner : la photo
    // finale est droite, et n'a plus besoin d'orientation.
    image.onload = () => { URL.revokeObjectURL(adresse); resolve(image); };
    image.onerror = () => { URL.revokeObjectURL(adresse); reject(new Error('Photo illisible.')); };
    image.src = adresse;
  });
}

/**
 * @param position là où est le téléphone au moment de la prise, ou null si la personne n'a pas
 * autorisé la position : la photo part alors sans lieu, et l'écran le dit.
 * @return les octets définitifs et leur fiche ; une erreur si la prise est illisible.
 */
export async function preparerPhoto(fichier: Blob, position: Releve | null, logiciel: string,
                                    maintenant = Date.now()): Promise<PhotoPrete> {
  const image = await chargerImage(fichier);
  const [largeur, hauteur] = dimensionsReduites(image.naturalWidth, image.naturalHeight);
  const canevas = document.createElement('canvas');
  canevas.width = largeur;
  canevas.height = hauteur;
  canevas.getContext('2d')!.drawImage(image, 0, 0, largeur, hauteur);
  const blob = await new Promise<Blob | null>(r => canevas.toBlob(r, 'image/jpeg', QUALITE));
  canevas.width = canevas.height = 0;                       // iOS garde la mémoire des canevas
  if (!blob) throw new Error('Photo illisible.');
  const octets = insererExif(new Uint8Array(await blob.arrayBuffer()), segmentExif(maintenant, logiciel, position));
  return {
    octets, empreinte: await empreinte(octets), prise_le: new Date(maintenant).toISOString(),
    latitude: position?.latitude ?? null, longitude: position?.longitude ?? null, precision_m: position?.precision_m ?? null,
  };
}

// ── Octets ⇄ texte, pour le coffre chiffré (qui range du JSON) ────────────────────────────

export function versBase64(octets: Uint8Array): string {
  let binaire = '';
  for (let i = 0; i < octets.length; i += 0x8000) binaire += String.fromCharCode(...octets.subarray(i, i + 0x8000));
  return btoa(binaire);
}

export function depuisBase64(texte: string): Uint8Array<ArrayBuffer> {
  const binaire = atob(texte);
  const octets = new Uint8Array(new ArrayBuffer(binaire.length));
  for (let i = 0; i < binaire.length; i++) octets[i] = binaire.charCodeAt(i);
  return octets;
}
