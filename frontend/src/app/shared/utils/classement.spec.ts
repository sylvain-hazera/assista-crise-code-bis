import { beneficiaireParDefaut, beneficiairesAdmis, codeFamille, libelleClasse, TypeClasse } from './classement';

describe('classement « quoi + pour qui »', () => {
  it('un seul chemin pour les animaux à évacuer', () => {
    expect(beneficiairesAdmis('EVAC', 'demande')).toEqual(['PERSONNES', 'ANIMAUX', 'BIENS']);
  });

  it('pas de demande de soins pour une personne (le 15), mais une offre de soins oui', () => {
    expect(beneficiairesAdmis('SOIN', 'demande')).toEqual(['ANIMAUX']);
    expect(beneficiairesAdmis('SOIN', 'offre')).toEqual(['PERSONNES', 'ANIMAUX']);
  });

  it('restreint aux pour qui écoutés, sans jamais rendre une liste vide', () => {
    expect(beneficiairesAdmis('ABRI', 'demande', ['ANIMAUX'])).toEqual(['ANIMAUX']);
    expect(beneficiairesAdmis('ABRI', 'demande', ['BIENS'])).toEqual(['PERSONNES', 'ANIMAUX']);
  });

  it('une précision hérite du code de sa famille', () => {
    const materiel: TypeClasse = { id: 'm', type: 'Matériel', code: 'MAT' };
    const groupe: TypeClasse = { id: 'g', type: 'Groupe électrogène', parent: 'm' };
    expect(codeFamille(groupe, new Map([['m', materiel]]))).toBe('MAT');
    expect(beneficiairesAdmis('MAT', 'demande')).toEqual([]);
  });

  it('un seul possible : retenu d’office', () => {
    expect(beneficiaireParDefaut(['BIENS'])).toBe('BIENS');
    expect(beneficiaireParDefaut(['PERSONNES', 'ANIMAUX'])).toBe('');
  });

  it('libellé court pour le pilotage', () => {
    expect(libelleClasse('Transport', 'ANIMAUX')).toBe('Transport · animaux');
    expect(libelleClasse(null, null)).toBe('Autre');
  });
});
