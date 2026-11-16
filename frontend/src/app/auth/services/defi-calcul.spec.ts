import { DefiInscription, resoudreDefi, sha256Hex } from './defi-calcul';

/** Un défi comme le serveur les fabrique : l'empreinte de `sel + nombre`. */
function defi(sel: string, nombre: number, maximum: number): DefiInscription {
  return { sel, empreinte: sha256Hex(`${sel}${nombre}`), maximum, emis: 0, expire: 0, niveau: 'NORMAL', signature: '' };
}

describe('Calcul anti-robot de la création de compte', () => {
  it('calcule SHA-256 comme tout le monde', () => {
    // Vecteurs de référence (FIPS 180-4) : sans eux, un défi du serveur ne serait jamais résolu.
    expect(sha256Hex('')).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
    expect(sha256Hex('abc')).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
    // 55 octets : la plus longue entrée qui tient dans un seul bloc.
    expect(sha256Hex('a'.repeat(55))).toBe('9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318');
  });

  it('retrouve le nombre, à chaque extrémité de la plage', async () => {
    const sel = '0123456789abcdef01234567';
    expect(await resoudreDefi(defi(sel, 0, 500))).toBe(0);
    expect(await resoudreDefi(defi(sel, 137, 500))).toBe(137);
    expect(await resoudreDefi(defi(sel, 500, 500))).toBe(500);
    // Le nombre de chiffres change en route (9 → 10, 99 → 100, 999 → 1000).
    expect(await resoudreDefi(defi(sel, 1000, 1200))).toBe(1000);
  });

  it("rend la main à l'affichage pendant le calcul, sans perdre le fil", async () => {
    expect(await resoudreDefi(defi('abcdef', 2345, 3000), 100)).toBe(2345);
  });

  it("ne tourne pas sans fin sur un défi qui n'a pas de solution", async () => {
    const sansSolution = { ...defi('abcdef', 900, 100) };     // la solution est hors de la plage
    expect(await resoudreDefi(sansSolution)).toBeNull();
    expect(await resoudreDefi({ ...defi('abcdef', 1, 10), empreinte: 'pas-une-empreinte' })).toBeNull();
  });
});
