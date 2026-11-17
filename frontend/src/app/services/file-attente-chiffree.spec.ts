import { deposer, relever, retirer } from './file-attente-chiffree';

/**
 * La file des réponses de terrain saisies sans réseau : elle doit rendre ce qu'on y a mis, et
 * ne rien laisser de lisible dans le stockage du navigateur.
 */
describe('file d\'attente chiffrée', () => {
  const identifiant = 'essai-' + Math.random().toString(36).slice(2);

  afterEach(async () => { await retirer(identifiant); });

  it('rend ce qu\'on y a déposé, puis l\'oublie', async () => {
    await deposer(identifiant, { donnees: { remarques: 'Madame Durand, 3 rue Haute' } });

    const releve = await relever<{ donnees: { remarques: string } }>();
    expect(releve.find(e => e.identifiant === identifiant)?.valeur.donnees.remarques)
      .toBe('Madame Durand, 3 rue Haute');

    await retirer(identifiant);
    expect((await relever()).some(e => e.identifiant === identifiant)).toBeFalse();
  });

  it('ne pose rien en clair dans le navigateur', async () => {
    await deposer(identifiant, { remarques: 'Madame Durand' });

    const brut = await new Promise<{ chiffre: ArrayBuffer }>((resolve, reject) => {
      const ouverture = indexedDB.open('assista-crise-terrain', 1);
      ouverture.onsuccess = () => {
        const lecture = ouverture.result.transaction('file').objectStore('file').get(identifiant);
        lecture.onsuccess = () => { ouverture.result.close(); resolve(lecture.result); };
        lecture.onerror = () => reject(lecture.error);
      };
      ouverture.onerror = () => reject(ouverture.error);
    });

    const lisible = new TextDecoder('utf-8', { fatal: false }).decode(brut.chiffre);
    expect(lisible).not.toContain('Durand');
    expect(lisible).not.toContain('remarques');
  });
});
