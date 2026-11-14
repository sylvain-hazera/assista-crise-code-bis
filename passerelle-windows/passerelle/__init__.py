"""Assista-Crise Passerelle : un PC Windows relaie des radios MeshCore et Meshtastic.

Demande de Sylvain du 15/11/2026 : une application à lancer — pas un service. Elle s'arrête
quand on ferme sa fenêtre, ne redémarre pas avec le poste, et s'ouvre par un raccourci sur le
bureau. Un non-averti doit pouvoir l'installer et s'en servir.

Elle ne réinvente rien : ce sont les ponts Python du satellite (`meshcore-bridge`,
`meshtastic-bridge`), lancés comme sous-processus, et l'enrôlement des satellites. Vue du
central, c'est un satellite de profil « passerelle ».
"""

VERSION = "1.0.0"
