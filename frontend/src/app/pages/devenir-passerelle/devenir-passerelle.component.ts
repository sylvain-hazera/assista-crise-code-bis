import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { RelaisSerieService, CompagnonRelayable } from '../../services/relais-serie.service';
import {
  CMD, DecoupeurDeTrames, REP, commandeEnvoiMessage, commandeSimple, encadrer,
  lireMessageRecu,
} from '../../shared/mesh/meshcore-trames';
import {
  PortSerie, VerrouEcran, apiSerie, prendreVerrouEcran, serieDisponible,
} from '../../shared/mesh/web-serial';

/** Débit du lien série companion. Valeur de la bibliothèque Python utilisée par notre pont. */
const DEBIT_SERIE = 115200;

/** Cadence du cycle de relais. La radio est lente (LoRa) : interroger plus vite ne sert à
 * rien et consomme du temps d'antenne — voir la politique de budget de trafic de meshcore-ha,
 * dont nous nous inspirons ici en restant volontairement peu bavards. */
const CYCLE_MS = 3000;

/** Délai avant nouvelle tentative après une coupure. Croissant, borné. */
const RECONNEXION_MS = [2000, 5000, 10000, 30000];

type Etat = 'inactif' | 'connexion' | 'relais' | 'erreur';

/**
 * « Devenir passerelle » : un poste verrouillé relaie une radio branchée en USB.
 *
 * Demande de Sylvain du 13/11/2026, sur un cas présenté le soir même : urgence sur un PC où
 * l'on ne peut **rien installer** — pas de Docker, pas d'exécutable, pas de pilote — mais dont
 * l'USB fonctionne.
 *
 * **Ce n'est pas un satellite.** Il ajoute de la portée radio au central, il n'ajoute aucune
 * résilience : si internet tombe, cette page ne joint plus l'API non plus. Le profil `gw` du
 * satellite reste la bonne réponse partout où l'on peut installer quelque chose.
 *
 * **Et une page n'est pas un service** : onglet fermé, portable en veille, relais arrêté. Le
 * texte le dit à l'écran plutôt que de le laisser découvrir, et un verrou d'écran est demandé
 * tant que le relais tourne.
 */
@Component({
  selector: 'app-devenir-passerelle',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './devenir-passerelle.component.html',
  styleUrl: './devenir-passerelle.component.scss',
})
export class DevenirPasserelleComponent implements OnInit, OnDestroy {
  etat: Etat = 'inactif';
  erreur = '';
  message = '';

  compagnons: CompagnonRelayable[] = [];
  compagnonChoisi = '';

  tramesRecues = 0;
  tramesEnvoyees = 0;
  messagesRelayes = 0;
  derniereActivite: Date | null = null;

  /** Web Serial n'existe ni sur Firefox, ni sur Safari, ni sur iOS. Le dire avant que la
   * personne ne cherche pourquoi le bouton ne fait rien. */
  readonly supporte = serieDisponible();

  private port: PortSerie | null = null;
  private lecteur: ReadableStreamDefaultReader<Uint8Array> | null = null;
  private ecrivain: WritableStreamDefaultWriter<Uint8Array> | null = null;
  private decoupeur = new DecoupeurDeTrames();
  private minuterie: ReturnType<typeof setInterval> | null = null;
  private verrou: VerrouEcran | null = null;
  private arrete = false;
  private essaisReconnexion = 0;

  constructor(private service: RelaisSerieService) {}

  ngOnInit(): void {
    this.service.etat().subscribe({
      next: (etat) => {
        this.compagnons = etat.compagnons;
        this.compagnonChoisi = etat.session?.compagnon || etat.compagnons[0]?.id || '';
      },
      error: () => this.erreur = 'Impossible de charger les radios que vous pouvez relayer.',
    });
  }

  ngOnDestroy(): void {
    // Fermeture propre quand on quitte la page. Elle n'est PAS garantie — un onglet tué ne
    // passe pas par là — d'où le battement et le ménage côté serveur.
    void this.arreter('Page quittée');
  }

  get nomCompagnonChoisi(): string {
    return this.compagnons.find(c => c.id === this.compagnonChoisi)?.nom || '';
  }

  // ══ Démarrage ═════════════════════════════════════════════════════════════

  async demarrer(): Promise<void> {
    if (!this.supporte || !this.compagnonChoisi) { return; }
    this.erreur = '';
    this.arrete = false;
    this.etat = 'connexion';
    try {
      // Le choix du port EXIGE un geste de l'utilisateur : impossible de le faire au
      // chargement de la page, et c'est voulu par la norme.
      this.port = await apiSerie().requestPort();
      await this.ouvrirLePort();
      await this.service.ouvrirOuBattre(this.compagnonChoisi).toPromise();
      await this.prendreLeVerrou();
      this.etat = 'relais';
      this.message = '';
      void this.envoyer(commandeSimple(CMD.APP_START));
      this.lancerLaBoucle();
      void this.lireEnContinu();
    } catch (e) {
      this.etat = 'erreur';
      this.erreur = this.lisible(e);
      await this.libererLePort();
    }
  }

  private async ouvrirLePort(): Promise<void> {
    if (!this.port) { throw new Error('Aucun port sélectionné.'); }
    await this.port.open({ baudRate: DEBIT_SERIE });
    this.decoupeur.reinitialiser();
    this.lecteur = this.port.readable?.getReader() ?? null;
    this.ecrivain = this.port.writable?.getWriter() ?? null;
    if (!this.lecteur || !this.ecrivain) {
      throw new Error('Ce port ne peut pas être lu et écrit.');
    }
  }

  async arreter(motif = 'Arrêt demandé'): Promise<void> {
    this.arrete = true;
    if (this.minuterie) { clearInterval(this.minuterie); this.minuterie = null; }
    await this.libererLePort();
    await this.relacherLeVerrou();
    if (this.compagnonChoisi) {
      this.service.fermer(this.compagnonChoisi).subscribe({ error: () => undefined });
    }
    this.etat = 'inactif';
    this.message = motif;
  }

  private async libererLePort(): Promise<void> {
    try { await this.lecteur?.cancel(); } catch { /* déjà fermé */ }
    try { this.lecteur?.releaseLock(); } catch { /* déjà relâché */ }
    try { this.ecrivain?.releaseLock(); } catch { /* déjà relâché */ }
    try { await this.port?.close(); } catch { /* déjà fermé */ }
    this.lecteur = null;
    this.ecrivain = null;
    this.port = null;
  }

  // ══ Verrou d'écran ════════════════════════════════════════════════════════
  //
  // Un portable qui se met en veille arrête le relais sans prévenir. Le verrou n'est pas
  // garanti par tous les navigateurs : on le demande, on ne compte pas dessus, et l'écran
  // affiche de toute façon qu'il ne faut pas fermer l'onglet.

  private async prendreLeVerrou(): Promise<void> {
    this.verrou = await prendreVerrouEcran();
  }

  private async relacherLeVerrou(): Promise<void> {
    try { await this.verrou?.release(); } catch { /* sans importance */ }
    this.verrou = null;
  }

  // ══ Lecture du port ═══════════════════════════════════════════════════════

  private async lireEnContinu(): Promise<void> {
    while (!this.arrete && this.lecteur) {
      try {
        const { value, done } = await this.lecteur.read();
        if (done) { break; }
        if (value) { this.traiter(value); }
      } catch (e) {
        if (this.arrete) { return; }
        // Nœud débranché, port repris par un autre logiciel : on retente, sans boucler vite.
        this.erreur = this.lisible(e);
        void this.reconnecter();
        return;
      }
    }
    if (!this.arrete) { void this.reconnecter(); }
  }

  private traiter(octets: Uint8Array): void {
    for (const charge of this.decoupeur.pousser(octets)) {
      this.tramesRecues++;
      this.derniereActivite = new Date();
      const recu = lireMessageRecu(charge);
      if (recu && recu.texte) {
        this.messagesRelayes++;
        this.service.deposerEntrant(this.compagnonChoisi, recu.pubkeyPrefix, recu.texte)
          .subscribe({ error: () => this.erreur = "Un message reçu n'a pas pu être transmis." });
        // Il y en a peut-être d'autres en attente dans la radio.
        void this.envoyer(commandeSimple(CMD.SYNC_NEXT_MESSAGE));
      } else if (charge[0] === REP.MESSAGES_WAITING) {
        void this.envoyer(commandeSimple(CMD.SYNC_NEXT_MESSAGE));
      }
    }
  }

  private async envoyer(charge: Uint8Array): Promise<void> {
    if (!this.ecrivain) { return; }
    try {
      await this.ecrivain.write(encadrer(charge));
      this.tramesEnvoyees++;
    } catch (e) {
      this.erreur = this.lisible(e);
    }
  }

  // ══ Cycle de relais ═══════════════════════════════════════════════════════

  private lancerLaBoucle(): void {
    this.minuterie = setInterval(() => void this.unCycle(), CYCLE_MS);
    void this.unCycle();
  }

  private async unCycle(): Promise<void> {
    if (this.arrete || this.etat !== 'relais') { return; }

    // Le battement maintient la session vivante ET remonte les compteurs. Il doit être
    // nettement plus fréquent que le délai de mort côté serveur, sinon le relais se fait
    // fermer en pleine activité.
    this.service.ouvrirOuBattre(this.compagnonChoisi, this.tramesRecues, this.tramesEnvoyees)
      .subscribe({
        error: () => this.erreur = 'Le central ne répond plus. Le relais continue d\'écouter la '
          + 'radio, mais rien ne remonte pour l\'instant.',
      });

    // Relever ce que la radio garde en attente, puis dépiler la file sortante.
    await this.envoyer(commandeSimple(CMD.SYNC_NEXT_MESSAGE));
    this.service.aEnvoyer(this.compagnonChoisi).subscribe({
      next: (messages) => messages.forEach(m => void this.transmettre(m)),
      error: () => undefined,
    });
  }

  private async transmettre(m: { id: string; contact_pubkey_hex: string; contenu: string })
      : Promise<void> {
    try {
      await this.envoyer(commandeEnvoiMessage(m.contact_pubkey_hex, m.contenu));
      this.service.marquer(m.id, 'ENVOYE').subscribe({ error: () => undefined });
      this.messagesRelayes++;
      this.derniereActivite = new Date();
    } catch (e) {
      // Marqué en échec plutôt que laissé en attente : un message qui reste indéfiniment dans
      // la file sans que personne ne le sache est pire qu'un échec annoncé.
      this.service.marquer(m.id, 'ECHEC', this.lisible(e)).subscribe({ error: () => undefined });
    }
  }

  // ══ Reconnexion ═══════════════════════════════════════════════════════════

  private async reconnecter(): Promise<void> {
    if (this.arrete) { return; }
    this.etat = 'connexion';
    await this.libererLePort();
    const delai = RECONNEXION_MS[Math.min(this.essaisReconnexion, RECONNEXION_MS.length - 1)];
    this.essaisReconnexion++;
    this.message = `Liaison perdue avec la radio. Nouvelle tentative dans ${delai / 1000} s.`;
    setTimeout(() => {
      if (this.arrete) { return; }
      // Reprise SANS geste de l'utilisateur : le port déjà autorisé reste accessible par
      // getPorts(), c'est ce qui permet de survivre à un débranchement sans intervention.
      void this.reprendreLePortAutorise();
    }, delai);
  }

  private async reprendreLePortAutorise(): Promise<void> {
    try {
      const ports = await apiSerie().getPorts();
      this.port = ports[0] ?? null;
      if (!this.port) {
        this.message = 'Rebranchez la radio, puis relancez le relais.';
        this.etat = 'erreur';
        return;
      }
      await this.ouvrirLePort();
      this.essaisReconnexion = 0;
      this.etat = 'relais';
      this.message = '';
      this.erreur = '';
      void this.envoyer(commandeSimple(CMD.APP_START));
      void this.lireEnContinu();
    } catch (e) {
      this.erreur = this.lisible(e);
      void this.reconnecter();
    }
  }

  private lisible(e: unknown): string {
    const brut = e instanceof Error ? e.message : String(e);
    if (/No port selected|cancel/i.test(brut)) { return 'Aucun port choisi.'; }
    if (/Failed to open|already open|in use/i.test(brut)) {
      return 'Ce port est déjà ouvert par un autre logiciel. Fermez l\'autre application '
        + 'qui utilise la radio, puis réessayez.';
    }
    return brut;
  }
}
