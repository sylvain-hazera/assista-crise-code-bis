import { EntreePlan, operationsPlan, proposerPlan } from './plan-canaux';
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
