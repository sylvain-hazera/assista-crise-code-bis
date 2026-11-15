"""Clé d'ESSAI pour la signature dans le navigateur (15/11/2026).

Contrairement aux clés de signatures_de_test.py, la partie privée de celle-ci est GARDÉE ici,
en clair : les tests doivent signer avec elle pour comparer notre signature, octet pour octet,
à celle qu'un vrai `ssh-keygen -Y sign` (OpenSSH 9.6) a produite avec la même clé.

Ce n'est pas un secret et ce ne doit jamais en devenir un : cette clé n'est autorisée nulle
part (elle n'est pas dans core/signature_satellites.pub) et ne signe rien d'installable. Les
mêmes valeurs sont recopiées dans frontend/src/app/services/signature-satellite.spec.ts, pour
que le navigateur et le serveur soient tenus à la même référence.
"""

#: Graine Ed25519 (32 octets, hexadécimal) de la clé d'essai.
GRAINE = "4b84ceed3c88885c9c9ae4b82aaddc1659d27815c465321ba3eb750ed40dba58"

CLE_PUBLIQUE_NAVIGATEUR = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIC2tJo9mfouAzgZk3sN8Sw+Z9CuaAPYIcKB7fduCcEEV cle-navigateur-de-test'

PHRASE = "phrase de test, pas un secret"

#: Sortie réelle de `ssh-keygen -Y sign -n assista-crise-satellite` pour le commit « aaaa…a ».
SIGNATURE_SSH_KEYGEN_A = """-----BEGIN SSH SIGNATURE-----
U1NIU0lHAAAAAQAAADMAAAALc3NoLWVkMjU1MTkAAAAgLa0mj2Z+i4DOBmTew3xLD5n0K5
oA9ghwoHt924JwQRUAAAAXYXNzaXN0YS1jcmlzZS1zYXRlbGxpdGUAAAAAAAAABnNoYTUx
MgAAAFMAAAALc3NoLWVkMjU1MTkAAABANHr5ZsdFz5xFMr/0aDcUmcCcTTJqS3aYbmz03x
4blT+qqcRjXwlTVGU8V5Md1UuuultamKbk5ds6VhzngO7oBw==
-----END SSH SIGNATURE-----"""

#: La clé d'essai emballée avec PHRASE, sel et vecteur fixés (octets 0, 1, 2…) pour que la
#: valeur soit reproductible. En service ils sont tirés au hasard.
EMBALLAGE = {
    "version": 1,
    "derivation": "PBKDF2-SHA256",
    "iterations": 600000,
    "sel": "AAECAwQFBgcICQoLDA0ODw==",
    "vecteur": "AAECAwQFBgcICQoL",
    "chiffre": "xo64a2YbdJCf928u6YKPokfcWAHPDnLNyOuMzD0aV4D80KxLmJ2VJ26tKbruE/XcG95ogyBdtD7QWG2bLrxCEA==",
    "cle_publique": "La0mj2Z+i4DOBmTew3xLD5n0K5oA9ghwoHt924JwQRU="
}
