# Assista-Crise Passerelle (Windows)

Une application qui fait d'un PC Windows une passerelle radio : elle relaie des radios MeshCore
et Meshtastic vers Assista-Crise **tant que sa fenêtre est ouverte**.

- Elle s'ouvre par le raccourci **Assista-Crise Passerelle** du bureau.
- **Fermer la fenêtre arrête tout.** Rien ne tourne en arrière-plan, rien ne démarre avec Windows.
- Aucun droit d'administrateur : tout s'installe dans le profil de l'utilisateur.
- Windows 10 ou 11, connecté à Internet.

## Installer (5 à 10 minutes)

**Côté administrateur, sur le site Assista-Crise :**

1. Page **Satellites** → « Installer un satellite » → choisir **Passerelle radio sur PC Windows**
   → **Générer** → **Télécharger l'installeur**.
2. Transmettre ce fichier (`Installer la passerelle Assista-Crise.bat`) à la personne qui a le
   PC : clé USB, courriel… Il contient un code valable 24 h, pour une seule installation.

**Sur le PC :**

3. Double-cliquer sur le fichier. Si Windows affiche « Windows a protégé votre ordinateur » :
   **Informations complémentaires**, puis **Exécuter quand même**.
4. Laisser faire : une fenêtre noire affiche cinq étapes, puis la passerelle s'ouvre toute seule
   sur « En attente de validation ».

**Côté administrateur :**

5. Page **Satellites** : la passerelle apparaît « En attente de validation » → **Valider**.
   Sur le PC, la fenêtre passe d'elle-même à l'écran des radios.

## Connecter une radio

Dans la fenêtre de la passerelle :

| Bouton | Quand | Comment |
|---|---|---|
| **Connecter en USB** | la radio est branchée par un câble | choisir son port dans la liste. En cas de doute : débrancher, « Chercher à nouveau », rebrancher — le port qui apparaît est le sien |
| **Connecter en Bluetooth** | la radio est allumée, à portée | « Chercher », puis choisir la radio. Fermer d'abord l'application du téléphone connectée à cette radio. MeshCore : appairer d'abord la radio dans les paramètres Bluetooth de Windows (code affiché sur la radio, souvent 123456) |
| **Connecter par adresse** | la radio est sur le réseau du PC (Wi-Fi) | saisir son adresse, par exemple `192.168.1.50` |

La passerelle interroge la radio, annonce ce qu'elle a trouvé (« Radio trouvée : Heltec V3
(MeshCore) »), et ne la connecte qu'après un **Oui**. La radio apparaît alors sur le site, pages
Companions MeshCore ou Meshtastic.

Plusieurs radios peuvent être connectées en même temps. Elles sont retenues : au prochain
lancement, la passerelle les reprend seule — y compris si Windows a changé le numéro du port USB.

## Au quotidien

- **Lancer** : raccourci du bureau. **Arrêter** : fermer la fenêtre.
- Colonne **État** : « En marche », ou « Nouvel essai… » quand la radio ne répond pas (débranchée,
  éteinte, hors de portée) — la passerelle réessaie seule toutes les 15 secondes.
- **Retirer** : la radio n'est plus relayée par ce poste ; on peut la reconnecter plus tard.
- **Journaux** : ouvre le dossier des journaux, à transmettre en cas de problème.

## Mettre à jour, désinstaller

- **Mettre à jour** : la fenêtre signale une version plus récente. Fermer la passerelle, puis
  relancer un installeur téléchargé depuis la page Satellites. L'enregistrement et les radios
  sont conservés.
- **Désinstaller** : `%LOCALAPPDATA%\AssistaCrisePasserelle\desinstaller.bat`.

## En cas de souci

| Symptôme | Piste |
|---|---|
| « Aucune radio ne répond sur ce port » | câble USB de charge seule ; autre application ouverte sur la radio ; carte à puce CH340 sans pilote (l'installer depuis le site du fabricant) |
| La radio Bluetooth n'apparaît pas | trop loin ; connectée à un téléphone ; Bluetooth du PC éteint |
| « Code d'installation refusé » | code expiré (24 h) ou déjà utilisé : en générer un nouveau |
| L'antivirus bloque l'installation | l'application n'est pas signée ; demander une exception au service informatique, ou utiliser le relais navigateur (menu « Devenir passerelle » du site), qui n'installe rien |

## Pour qui maintient le projet

- L'application lance, comme sous-processus, **les ponts du satellite** (`meshcore-bridge`,
  `meshtastic-bridge`) : même code, même comportement. Vue du central, c'est un satellite de
  profil « passerelle », enrôlé par le même jeton.
- Les radios connectées ici suivent la règle des passerelles locales (isolées par défaut).
- Ce que le site distribue (`frontend/public/passerelle/`) est **assemblé** par
  `python3 passerelle-windows/construire.py`, à relancer après toute modification de
  l'application ou d'un pont. `tests/test_distribution.py` échoue tant que ce n'est pas fait.
- Tests : `python -m pytest passerelle-windows/tests` (Python avec `httpx`, `meshcore`,
  `meshtastic` ; la fenêtre est testée si `tkinter` et un écran sont disponibles).
- Le mot de passe du compte de service est protégé par DPAPI (lié au compte Windows) ; il n'est
  jamais écrit en clair.
