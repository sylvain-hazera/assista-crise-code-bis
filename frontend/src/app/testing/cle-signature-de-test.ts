import { CleEmballee } from '../services/signature-satellite';

/** Clé d'ESSAI pour la signature des versions dans le navigateur. Ces valeurs sont celles de
 * backend/core/tests/satellites/cle_navigateur_de_test.py : une clé autorisée nulle part, dont
 * la partie privée est publique. Le serveur et le navigateur sont tenus à la même référence —
 * la sortie d'un vrai `ssh-keygen -Y sign` (OpenSSH 9.6) pour cette clé et le commit
 * « aaaa…a ». Ed25519 est déterministe : il n'y a qu'une bonne réponse, à l'octet près. */
export const PHRASE_DE_TEST = 'phrase de test, pas un secret';

export const EMBALLAGE_DE_TEST: CleEmballee = {
  "version": 1,
  "derivation": "PBKDF2-SHA256",
  "iterations": 600000,
  "sel": "AAECAwQFBgcICQoLDA0ODw==",
  "vecteur": "AAECAwQFBgcICQoL",
  "chiffre": "xo64a2YbdJCf928u6YKPokfcWAHPDnLNyOuMzD0aV4D80KxLmJ2VJ26tKbruE/XcG95ogyBdtD7QWG2bLrxCEA==",
  "cle_publique": "La0mj2Z+i4DOBmTew3xLD5n0K5oA9ghwoHt924JwQRU="
};

export const SIGNATURE_SSH_KEYGEN_A = `-----BEGIN SSH SIGNATURE-----
U1NIU0lHAAAAAQAAADMAAAALc3NoLWVkMjU1MTkAAAAgLa0mj2Z+i4DOBmTew3xLD5n0K5
oA9ghwoHt924JwQRUAAAAXYXNzaXN0YS1jcmlzZS1zYXRlbGxpdGUAAAAAAAAABnNoYTUx
MgAAAFMAAAALc3NoLWVkMjU1MTkAAABANHr5ZsdFz5xFMr/0aDcUmcCcTTJqS3aYbmz03x
4blT+qqcRjXwlTVGU8V5Md1UuuultamKbk5ds6VhzngO7oBw==
-----END SSH SIGNATURE-----`;

export const SIGNATURE_DE_TEST_B = `-----BEGIN SSH SIGNATURE-----
U1NIU0lHAAAAAQAAADMAAAALc3NoLWVkMjU1MTkAAAAgLa0mj2Z+i4DOBmTew3xLD5n0K5
oA9ghwoHt924JwQRUAAAAXYXNzaXN0YS1jcmlzZS1zYXRlbGxpdGUAAAAAAAAABnNoYTUx
MgAAAFMAAAALc3NoLWVkMjU1MTkAAABAtji2rJBFJT3FFJQrwykRlGDEAQZtot0TRT1Kqv
I0KJc0iz2ucbSctaSEyxj92ZUETchK2MtIP2AMOWD66vvjCw==
-----END SSH SIGNATURE-----`;
