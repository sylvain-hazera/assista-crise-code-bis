import { PhraseIncorrecte, navigateurSaitSigner, signerVersion } from './signature-satellite';

import {
  EMBALLAGE_DE_TEST as EMBALLAGE, PHRASE_DE_TEST as PHRASE, SIGNATURE_DE_TEST_B as SIGNATURE_B,
  SIGNATURE_SSH_KEYGEN_A,
} from '../testing/cle-signature-de-test';

const COMMIT_A = 'a'.repeat(40);
const COMMIT_B = 'b'.repeat(40);

/** La référence est la sortie d'un vrai `ssh-keygen -Y sign` : voir
 * testing/cle-signature-de-test.ts. */
describe('signature d’une version dans le navigateur', () => {

  it('le navigateur de test sait signer (sinon ces tests ne prouvent rien)', async () => {
    expect(await navigateurSaitSigner()).toBeTrue();
  });

  it('produit exactement la signature de ssh-keygen', async () => {
    expect(await signerVersion(EMBALLAGE, PHRASE, COMMIT_A)).toBe(SIGNATURE_SSH_KEYGEN_A);
  });

  it('signe chaque version différemment', async () => {
    const signature = await signerVersion(EMBALLAGE, PHRASE, COMMIT_B);

    expect(signature).toBe(SIGNATURE_B);
    expect(signature).not.toBe(SIGNATURE_SSH_KEYGEN_A);
  });

  it('refuse une mauvaise phrase de passe sans rien signer', async () => {
    await expectAsync(signerVersion(EMBALLAGE, PHRASE + ' ', COMMIT_A)).toBeRejectedWithError(PhraseIncorrecte);
    await expectAsync(signerVersion(EMBALLAGE, '', COMMIT_A)).toBeRejectedWithError(PhraseIncorrecte);
  });

  it('refuse une clé emballée altérée', async () => {
    const altere = { ...EMBALLAGE, chiffre: EMBALLAGE.chiffre.replace(/^./, c => (c === 'A' ? 'B' : 'A')) };

    await expectAsync(signerVersion(altere, PHRASE, COMMIT_A)).toBeRejectedWithError(PhraseIncorrecte);
  });

  it('ne signe pas un numéro de version incomplet ou mal formé', async () => {
    await expectAsync(signerVersion(EMBALLAGE, PHRASE, 'abc123')).toBeRejected();
    await expectAsync(signerVersion(EMBALLAGE, PHRASE, 'A'.repeat(40))).toBeRejected();
  });

  it('refuse un emballage d’un format inconnu plutôt que de deviner', async () => {
    await expectAsync(signerVersion({ ...EMBALLAGE, version: 2 }, PHRASE, COMMIT_A)).toBeRejected();
  });
});
