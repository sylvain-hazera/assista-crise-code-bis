import { ChoixEmplacement, EntreePlan, ajoutsParDefaut, ajoutsSansPlacePossible, choixParDefaut, operationsChoix, operationsPlan, proposerPlan } from './plan-canaux';
import { EmplacementCanal } from './pilotes';

const entree = (nom: string, role: EntreePlan['role'], disponible = true): EntreePlan => ({
  nom, role, disponible, psk_hex: disponible ? '01' : '', libelle: nom, canal: 'id-' + nom,
  public: true,
});
const PLAN = [entree('Fr_Balise', 'communautaire'), entree('Fr_EMCOM', 'communautaire'),
              entree('CriseInonda', 'crise'), entree('Moissac', 'commune')];

const slot = (index: number, nom: string, role = 2): EmplacementCanal =>
  ({ index, nom, role, pskHex: '01' });
const vides = (de: number) => Array.from({ length: 8 - de }, (_, i) => slot(de + i, '', 0));

describe('Plan de canaux au branchement', () => {
  it('sur une radio neuve : tout se range dans les emplacements libres, primaire intact', () => {
    const p = proposerPlan([slot(0, '', 1), ...vides(1)], PLAN);

    expect(p.ajouts.map(a => [a.entree.nom, a.index])).toEqual(
      [['Fr_Balise', 1], ['Fr_EMCOM', 2], ['CriseInonda', 3], ['Moissac', 4]]);
    expect(p.manque).toBe(0);
  });

  it('ne repropose pas ce qui est déjà là, quelle que soit la casse', () => {
    const p = proposerPlan([slot(0, '', 1), slot(1, 'fr_emcom'), ...vides(2)], PLAN);

    expect(p.presents.map(x => x.entree.nom)).toEqual(['Fr_EMCOM']);
    expect(p.ajouts.map(a => a.entree.nom)).toEqual(['Fr_Balise', 'CriseInonda', 'Moissac']);
  });

  it('les communautaires passent en premier quand la place manque', () => {
    const pleine = [slot(0, '', 1), slot(1, 'A'), slot(2, 'B'), slot(3, 'C'), slot(4, 'D'),
                    slot(5, 'E'), slot(6, 'F'), slot(7, '', 0)];
    const p = proposerPlan(pleine, PLAN);

    expect(p.ajouts[0]).toEqual({ entree: PLAN[0], index: 7 });
    expect(p.ajouts.slice(1).every(a => a.index === null)).toBeTrue();
    expect(p.manque).toBe(3);
  });

  it('propose de supprimer des canaux étrangers au plan, jamais le primaire ni ceux du plan', () => {
    const radio = [slot(0, 'LongFast', 1), slot(1, 'Fr_EMCOM'), slot(2, 'Perso'), ...vides(3)];
    const p = proposerPlan(radio, PLAN);

    expect(p.supprimables.map(s => s.nom)).toEqual(['Perso']);
  });

  it('écarte un canal communautaire dont on ne connaît pas la clé', () => {
    const plan = [entree('Fr_Balise', 'communautaire', false), ...PLAN.slice(1)];
    const p = proposerPlan([slot(0, '', 1), ...vides(1)], plan);

    expect(p.indisponibles.map(e => e.nom)).toEqual(['Fr_Balise']);
    expect(p.ajouts.map(a => a.entree.nom)).not.toContain('Fr_Balise');
  });

  it('une fois d\'accord : suppressions d\'abord, puis ajouts dans les places libérées', () => {
    const pleine = [slot(0, '', 1), ...[1, 2, 3, 4, 5, 6, 7].map(i => slot(i, 'X' + i))];
    const p = proposerPlan(pleine, PLAN);

    const ops = operationsPlan(p, PLAN, [6, 7]);

    expect(ops.supprimer).toEqual([6, 7]);
    expect(ops.ecrire.map(o => [o.entree.nom, o.index])).toEqual([['Fr_Balise', 6], ['Fr_EMCOM', 7]]);
    expect(ops.sansPlace.map(e => e.nom)).toEqual(['CriseInonda', 'Moissac']);
  });

  it('ne libère jamais le primaire, même si on le demande', () => {
    const ops = operationsPlan(proposerPlan([slot(0, 'LongFast', 1)], PLAN), PLAN.slice(0, 1), [0]);
    expect(ops.supprimer).toEqual([]);
  });
});


describe('Choix par défaut quand la radio manque de place (19/11/2026)', () => {
  // La radio de la capture : 8 emplacements pleins, Fr_Balise et Fr_EMCOM en 0 et 1, six canaux
  // de la personne ; le serveur propose 8 crises et la commune.
  const radio = [slot(0, 'Fr_Balise', 1), slot(1, 'Fr_EMCOM'), slot(2, 'Fr_BlaBla'), slot(3, 'D_HauteLoir'),
                 slot(4, 'ADRASEC43'), slot(5, 'AASC'), slot(6, 'R_ARA'), slot(7, 'Alerte')];
  const crises = Array.from({ length: 8 }, (_, i) => entree(`Crise${i}`, 'crise'));
  const plan = [entree('Fr_Balise', 'communautaire'), entree('Fr_EMCOM', 'communautaire'), ...crises,
                entree('Tests', 'commune')];

  it("ne coche rien quand aucun emplacement n'est libre : rien n'est retiré sans décision", () => {
    expect(ajoutsParDefaut(proposerPlan(radio, plan))).toEqual([]);
  });

  it("coche autant que la place libre, la commune d'abord puis les crises dans l'ordre du serveur", () => {
    const p = proposerPlan([slot(0, 'Fr_Balise', 1), slot(1, 'Fr_EMCOM'), ...vides(2).map((v, i) => ({ ...v, index: i + 2 }))], plan);
    expect(p.libres.length).toBe(6);
    expect(ajoutsParDefaut(p)).toEqual(['Tests', 'Crise0', 'Crise1', 'Crise2', 'Crise3', 'Crise4']);
  });

  it('dit combien ne tiendront pas, même en libérant tout le libérable', () => {
    const p = proposerPlan(radio, plan);
    expect(p.supprimables.length).toBe(6);
    expect(ajoutsSansPlacePossible(p, 9)).toBe(3);
    expect(ajoutsSansPlacePossible(p, 6)).toBe(0);
  });
});

describe('Emplacement par emplacement : relier, remplacer (19/11/2026)', () => {
  const plan = [entree('Fr_Balise', 'communautaire'), entree('Fr_EMCOM', 'communautaire'),
                entree('CriseFDF43', 'crise'), entree('Tests', 'commune')];
  const radio = [slot(0, 'Fr_Balise', 1), slot(1, 'Fr_EMCOM'), slot(2, 'Fr_BlaBla'), slot(3, 'D_HauteLoir'),
                 slot(4, 'ADRASEC43'), slot(5, 'AASC'), slot(6, 'R_ARA'), slot(7, 'Alerte')];

  it('par défaut, tout est gardé sur une radio pleine, et une correspondance existante se relit', () => {
    const p = proposerPlan(radio, plan);
    const choix = choixParDefaut(radio, p, plan, { alerte: 'id-Tests' });
    expect(choix.filter(c => c.action !== 'garder')).toEqual([{ index: 7, action: 'relier', cible: 'Tests' }]);
  });

  it('relier ne réécrit rien, remplacer écrit dans le même emplacement', () => {
    const choix: ChoixEmplacement[] = radio.map(e => ({ index: e.index, action: 'garder' as const, cible: null }));
    choix[7] = { index: 7, action: 'relier', cible: 'Tests' };
    choix[4] = { index: 4, action: 'remplacer', cible: 'CriseFDF43' };
    const ops = operationsChoix(radio, choix, plan);
    expect(ops.erreurs).toEqual([]);
    expect(ops.correspondances).toEqual({ alerte: 'id-Tests' });
    expect(ops.ecrire.map(o => [o.index, o.entree.nom])).toEqual([[4, 'CriseFDF43']]);
    expect(ops.supprimer).toEqual([]);
  });

  it('refuse un même canal à deux places, le primaire remplacé, et un relier sans cible', () => {
    const choix: ChoixEmplacement[] = radio.map(e => ({ index: e.index, action: 'garder' as const, cible: null }));
    choix[2] = { index: 2, action: 'remplacer', cible: 'Tests' };
    choix[7] = { index: 7, action: 'relier', cible: 'Tests' };
    choix[0] = { index: 0, action: 'remplacer', cible: 'CriseFDF43' };
    choix[5] = { index: 5, action: 'relier', cible: null };
    const erreurs = operationsChoix(radio, choix, plan).erreurs.join(' | ');
    expect(erreurs).toContain('« Tests » se retrouverait sur 2 emplacements');
    expect(erreurs).toContain('primaire');
    expect(erreurs).toContain('Emplacement 5');
  });

  it('remplacer Fr_EMCOM par un canal déjà ailleurs est signalé, supprimer libère sans écrire', () => {
    const choix: ChoixEmplacement[] = radio.map(e => ({ index: e.index, action: 'garder' as const, cible: null }));
    choix[3] = { index: 3, action: 'remplacer', cible: 'Fr_EMCOM' };   // déjà en 1, gardé
    choix[6] = { index: 6, action: 'vider', cible: null };
    const ops = operationsChoix(radio, choix, plan);
    expect(ops.erreurs.join()).toContain('« Fr_EMCOM » se retrouverait sur 2 emplacements (1, 3)');
    expect(ops.supprimer).toEqual([6]);
  });
});
