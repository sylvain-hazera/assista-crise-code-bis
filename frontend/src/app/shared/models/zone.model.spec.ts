import { libellerZones } from './zone.model';
import { Zone } from './zone.model';

/** Chaque collectivité reçoit automatiquement une zone « Mon territoire ». Quelqu'un qui voit
 * celles de plusieurs institutions — un administrateur, ou un compte rattaché à une mairie ET
 * à son EPCI — lisait six fois la même ligne dans les sélecteurs, sans rien pour les
 * distinguer (signalé le 12/11/2026, sur l'activation du module d'estimation des dégâts). */
describe('libellerZones', () => {
  const zone = (p: Partial<Zone>): Zone => ({
    id: p.id!, institution: 'i', nom: p.nom!, communes: [], actif: true, ...p,
  } as Zone);

  it('suffixe les noms en double par leur institution', () => {
    const libellees = libellerZones([
      zone({ id: '1', nom: 'Mon territoire', institution_nom: 'Mairie de Saumos' }),
      zone({ id: '2', nom: 'Mon territoire', institution_nom: 'CC Médullienne' }),
    ]);

    expect(libellees.map(z => z.libelle))
      .toEqual(['Mon territoire — Mairie de Saumos', 'Mon territoire — CC Médullienne']);
  });

  it('laisse un nom unique tel quel', () => {
    // Ajouter l'institution partout alourdirait la liste d'une mairie qui n'a qu'un
    // territoire, pour qui la précision n'apprend rien.
    const libellees = libellerZones([
      zone({ id: '1', nom: 'Mon territoire', institution_nom: 'Mairie de Saumos' }),
      zone({ id: '2', nom: 'Emblavez', institution_nom: 'Mairie de Saumos' }),
    ]);

    expect(libellees.map(z => z.libelle)).toEqual(['Mon territoire', 'Emblavez']);
  });

  it('garde le nom seul quand l\'institution est inconnue', () => {
    // Mieux vaut un doublon qu'un « — undefined » collé derrière le nom.
    const libellees = libellerZones([
      zone({ id: '1', nom: 'Mon territoire' }),
      zone({ id: '2', nom: 'Mon territoire' }),
    ]);

    expect(libellees.map(z => z.libelle)).toEqual(['Mon territoire', 'Mon territoire']);
  });
});
