import { TableTriFiltre, normaliser } from './table-tri-filtre';

interface Ligne {
  nom: string;
  sauts: number | null;
  vu: string | null;
  actif: boolean;
}

function table(cle: string | null = null, sens: 1 | -1 = 1) {
  return new TableTriFiltre<Ligne>({
    nom: { valeur: l => l.nom },
    sauts: { valeur: l => l.sauts, texte: l => l.sauts === null ? 'hors de portée' : `${l.sauts} sauts` },
    vu: { valeur: l => l.vu ? new Date(l.vu) : null, texte: l => l.vu || '' },
    actif: { valeur: l => l.actif, texte: l => l.actif ? 'oui' : 'non' },
  }, cle, sens);
}

const LIGNES: Ligne[] = [
  { nom: 'Étang',  sauts: 3,    vu: '2026-11-01T10:00:00Z', actif: true },
  { nom: 'Abri',   sauts: null, vu: null,                   actif: false },
  { nom: 'esker',  sauts: 10,   vu: '2026-11-08T10:00:00Z', actif: true },
  { nom: 'Zénith', sauts: 1,    vu: '2026-10-01T10:00:00Z', actif: false },
];

describe('TableTriFiltre', () => {

  it('trie les nombres numériquement, et non comme du texte', () => {
    // Le piège : en texte, '10' passerait avant '3'.
    const t = table('sauts');
    expect(t.appliquer(LIGNES).map(l => l.sauts)).toEqual([1, 3, 10, null]);
  });

  it('laisse les valeurs inconnues en dernier DANS LES DEUX SENS', () => {
    // La décision centrale du module : un nœud jamais entendu ne doit pas se retrouver en tête
    // d'un tri décroissant comme s'il était le plus récent.
    expect(table('sauts', 1).appliquer(LIGNES).map(l => l.sauts)).toEqual([1, 3, 10, null]);
    expect(table('sauts', -1).appliquer(LIGNES).map(l => l.sauts)).toEqual([10, 3, 1, null]);
    expect(table('vu', 1).appliquer(LIGNES).map(l => l.nom))
      .toEqual(['Zénith', 'Étang', 'esker', 'Abri']);
    expect(table('vu', -1).appliquer(LIGNES).map(l => l.nom))
      .toEqual(['esker', 'Étang', 'Zénith', 'Abri']);
  });

  it('trie le texte sans tenir compte de la casse ni des accents', () => {
    // 'Étang' doit se placer entre 'esker' et 'Zénith' : avec une comparaison brute d'UTF-16, les
    // lettres accentuées passent après 'z' et les majuscules avant les minuscules.
    expect(table('nom').appliquer(LIGNES).map(l => l.nom))
      .toEqual(['Abri', 'esker', 'Étang', 'Zénith']);
  });

  it('trie les dates chronologiquement', () => {
    expect(table('vu').appliquer(LIGNES).map(l => l.vu?.slice(0, 10)))
      .toEqual(['2026-10-01', '2026-11-01', '2026-11-08', undefined]);
  });

  it('trie les booléens faux puis vrai', () => {
    expect(table('actif').appliquer(LIGNES).map(l => l.actif)).toEqual([false, false, true, true]);
  });

  it('ne réordonne pas le tableau source', () => {
    const source = [...LIGNES];
    table('nom').appliquer(source);
    expect(source).toEqual(LIGNES);
  });

  it('filtre une colonne sur le texte affiché, accents et casse ignorés', () => {
    const t = table();
    t.filtres['nom'] = 'etang';
    expect(t.appliquer(LIGNES).map(l => l.nom)).toEqual(['Étang']);
  });

  it('filtre un booléen par le mot affiché', () => {
    const t = table();
    t.filtres['actif'] = 'non';
    expect(t.appliquer(LIGNES).map(l => l.nom)).toEqual(['Abri', 'Zénith']);
  });

  it('cumule les filtres de colonnes (ET, pas OU)', () => {
    const t = table();
    t.filtres['actif'] = 'oui';
    t.filtres['sauts'] = '3';
    expect(t.appliquer(LIGNES).map(l => l.nom)).toEqual(['Étang']);
  });

  it('cherche globalement dans toutes les colonnes déclarées', () => {
    const t = table();
    t.recherche = 'hors de portée';
    expect(t.appliquer(LIGNES).map(l => l.nom)).toEqual(['Abri']);
  });

  it('cumule la recherche globale et un filtre de colonne', () => {
    const t = table();
    t.recherche = 'sauts';            // tous ceux qui ont un nombre de sauts
    t.filtres['nom'] = 'z';
    expect(t.appliquer(LIGNES).map(l => l.nom)).toEqual(['Zénith']);
  });

  it('ignore un filtre vide ou fait d espaces', () => {
    const t = table();
    t.filtres['nom'] = '   ';
    expect(t.appliquer(LIGNES).length).toBe(4);
    expect(t.filtreActif).toBe(false);
  });

  it('bascule croissant, décroissant, puis ordre du serveur', () => {
    const t = table();
    t.basculer('nom');
    expect([t.cle, t.sens]).toEqual(['nom', 1]);
    t.basculer('nom');
    expect([t.cle, t.sens]).toEqual(['nom', -1]);
    t.basculer('nom');
    expect(t.cle).toBeNull();
    // Sans colonne de tri, l'ordre d'arrivée est conservé tel quel.
    expect(t.appliquer(LIGNES).map(l => l.nom)).toEqual(LIGNES.map(l => l.nom));
  });

  it('repart en croissant quand on change de colonne', () => {
    const t = table('nom', -1);
    t.basculer('sauts');
    expect([t.cle, t.sens]).toEqual(['sauts', 1]);
  });

  it('annonce l état de tri pour un lecteur d écran', () => {
    const t = table('nom', -1);
    expect(t.ariaSort('nom')).toBe('descending');
    expect(t.ariaSort('sauts')).toBe('none');
    expect(t.indicateur('nom')).toBe('▼');
    expect(t.indicateur('sauts')).toBe('');
  });

  it('réinitialise la recherche et les filtres sans toucher au tri', () => {
    const t = table('nom');
    t.recherche = 'x';
    t.filtres['actif'] = 'oui';
    t.reinitialiser();
    expect(t.filtreActif).toBe(false);
    expect(t.cle).toBe('nom');
  });

  it('ignore une colonne de tri inconnue plutôt que de planter', () => {
    const t = table('inexistante');
    expect(t.appliquer(LIGNES).length).toBe(4);
  });

  it('normalise les accents et la casse', () => {
    expect(normaliser('Élysée')).toBe('elysee');
    expect(normaliser(null)).toBe('');
  });
});
