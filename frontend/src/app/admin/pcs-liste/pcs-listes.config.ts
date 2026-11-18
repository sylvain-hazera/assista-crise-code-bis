/**
 * Les paragraphes du plan communal de sauvegarde qui se tiennent en liste : organigramme du
 * poste de commandement, moyens d'alerte, exercices. Ils ont la même forme -- des lignes propres
 * à la commune -- donc le même écran (`PcsListeComponent`), décrit ici paragraphe par
 * paragraphe : ses champs, et surtout à quoi il sert une fois la crise ouverte.
 */

export type TypeChamp = 'texte' | 'telephone' | 'long' | 'choix' | 'date' | 'zone' | 'equipe' | 'personne';

export interface ChampListe {
  cle: string;
  libelle: string;
  type: TypeChamp;
  options?: { valeur: string; libelle: string }[];
  /** Champ `personne` : la clé du champ téléphone à remplir quand on choisit un contact. */
  telephone?: string;
  indication?: string;
  /** Clé d'un texte fourni par le serveur, montré sous le champ tant qu'il est vide (la fiche
   * réflexe type de la trame, sous les consignes propres à la commune). */
  parDefaut?: string;
}

export type Ligne = Record<string, any> & { id: string };

export interface ParagrapheListe {
  fil: string;
  titre: string;
  icone: string;
  aQuoiCaSert: string;
  /** Chemin de l'API, sous /api/. */
  ressource: string;
  ajouter: string;
  vide: string;
  champs: ChampListe[];
  titreLigne: (ligne: Ligne) => string;
  detailLigne: (ligne: Ligne) => string;
}

const date = (iso: string) => iso ? iso.split('-').reverse().join('/') : '';
const joindre = (...morceaux: (string | null | undefined)[]) => morceaux.filter(Boolean).join(' · ');

export const PARAGRAPHES_EN_LISTE: Record<string, ParagrapheListe> = {
  organisation: {
    fil: 'paragraphe 2.2 et annexe 4.2',
    titre: 'Poste de commandement et fiches réflexes',
    icone: 'account_tree',
    aQuoiCaSert: "C'est ce qu'on cherche à la première minute : qui dirige, qui coordonne, qui alerte, et qui les remplace. "
      + "Reliez chaque fonction à l'équipe qui la tient : vous ne nommez les personnes qu'une fois, et ces équipes permanentes sont proposées d'office à chaque crise. "
      + "Chaque fonction sort avec sa fiche réflexe dans le document du plan, à imprimer et à garder au poste de commandement. "
      + "Tant que vous n'écrivez pas la vôtre, c'est la fiche type de la trame de l'État qui est reprise.",
    ressource: 'pcs-fonctions',
    ajouter: 'Ajouter une fonction',
    vide: "L'organigramme est vide. Commencez par le maire et le coordinateur.",
    champs: [
      { cle: 'fonction', libelle: 'Fonction', type: 'choix', options: [
        { valeur: 'DOS', libelle: 'Maire — directeur des opérations de secours' },
        { valeur: 'COORDINATION', libelle: 'Coordinateur des moyens et des actions' },
        { valeur: 'ALERTE', libelle: "Responsable de l'alerte de la population" },
        { valeur: 'SOUTIEN', libelle: 'Responsable du soutien des populations' },
        { valeur: 'LOGISTIQUE', libelle: 'Responsable logistique' },
        { valeur: 'SECRETARIAT', libelle: 'Secrétariat' },
        { valeur: 'AUTRE', libelle: 'Autre fonction' },
      ] },
      { cle: 'libelle', libelle: 'Nom de la fonction, si « autre »', type: 'texte' },
      { cle: 'equipe', libelle: 'Équipe qui tient cette fonction', type: 'equipe',
        indication: "Son responsable et son encadrement sont repris d'office : inutile de les ressaisir. "
          + 'Cette équipe est prête pour la crise suivante : elle y est proposée d’office. Seule la cellule de crise est recréée à chaque crise, avec les mêmes personnes.' },
      { cle: 'titulaire', libelle: 'Titulaire, si ce n’est pas le responsable de l’équipe', type: 'personne', telephone: 'titulaire_telephone' },
      { cle: 'titulaire_telephone', libelle: 'Téléphone du titulaire', type: 'telephone' },
      { cle: 'suppleant', libelle: 'Suppléant, si ce n’est pas un encadrant de l’équipe', type: 'personne', telephone: 'suppleant_telephone', indication: 'Une crise dure plus longtemps qu’une personne.' },
      { cle: 'suppleant_telephone', libelle: 'Téléphone du suppléant', type: 'telephone' },
      { cle: 'consignes', libelle: 'Fiche réflexe propre à la commune', type: 'long',
        indication: 'Laissez vide pour garder la fiche type.', parDefaut: 'fiche_type' },
    ],
    titreLigne: (l) => l['libelle'] || l['fonction_libelle'],
    // `personnes` : ce que le serveur retient -- le nom saisi, sinon celui que donne l'équipe.
    detailLigne: (l) => {
      const p = l['personnes'] || {};
      return joindre(
        p['equipe'] ? `Équipe : ${p['equipe']}` : null,
        p['titulaire'] ? `Titulaire : ${p['titulaire']}${p['titulaire_telephone'] ? ' — ' + p['titulaire_telephone'] : ''}` : 'Pas de titulaire',
        p['suppleant'] ? `Suppléant : ${p['suppleant']}${p['suppleant_telephone'] ? ' — ' + p['suppleant_telephone'] : ''}` : 'Pas de suppléant',
        l['consignes'] ? 'fiche propre à la commune' : 'fiche type',
      );
    },
  },

  alerte: {
    fil: 'paragraphe 2.4',
    titre: 'Alerte de la population',
    icone: 'campaign',
    aQuoiCaSert: "Le jour de la crise, c'est la liste de ce qu'on déclenche et de qui l'on appelle, quartier par quartier : "
      + "la sirène, le véhicule avec haut-parleur et son circuit, les personnes relais. "
      + "FR-Alert n'y figure pas : il relève du préfet. Les quartiers sont facultatifs — sans eux, un moyen vaut pour toute la commune.",
    ressource: 'pcs-moyens-alerte',
    ajouter: "Ajouter un moyen d'alerte",
    vide: "Aucun moyen d'alerte n'est recensé.",
    champs: [
      { cle: 'type', libelle: 'Moyen', type: 'choix', options: [
        { valeur: 'SIRENE', libelle: 'Sirène' },
        { valeur: 'VEHICULE', libelle: 'Véhicule avec haut-parleur' },
        { valeur: 'AUTOMATE', libelle: "Automate d'appel ou de SMS" },
        { valeur: 'RELAIS', libelle: 'Personne relais de quartier' },
        { valeur: 'PORTE_A_PORTE', libelle: 'Porte-à-porte' },
        { valeur: 'AFFICHAGE', libelle: 'Panneaux, site et réseaux de la commune' },
        { valeur: 'AUTRE', libelle: 'Autre moyen' },
      ] },
      { cle: 'description', libelle: 'Lieu, circuit ou liste de diffusion', type: 'texte' },
      { cle: 'zone', libelle: 'Quartier (facultatif)', type: 'zone' },
      { cle: 'personne', libelle: 'Personne qui le met en œuvre', type: 'texte' },
      { cle: 'personne_telephone', libelle: 'Son téléphone', type: 'telephone' },
    ],
    titreLigne: (l) => joindre(l['type_libelle'], l['zone_nom']),
    detailLigne: (l) => joindre(l['description'], l['personne'], l['personne_telephone']) || 'Sans précision',
  },

  exercices: {
    fil: 'annexe 4.5',
    titre: 'Exercices',
    icone: 'sports_score',
    aQuoiCaSert: "Un plan qu'on n'a jamais joué ne vaut que sur le papier. Consignez ici chaque exercice et ce qu'il a appris : "
      + "les enseignements et ce qui doit changer entrent au document du plan, et le plan signale quand le dernier exercice est trop ancien. "
      + "Pour le jouer dans l'application, ouvrez une crise d'exercice.",
    ressource: 'pcs-exercices',
    ajouter: 'Consigner un exercice',
    vide: "Aucun exercice n'est consigné.",
    champs: [
      { cle: 'date', libelle: 'Date', type: 'date' },
      { cle: 'theme', libelle: 'Thème ou scénario', type: 'texte' },
      { cle: 'deroulement', libelle: 'Déroulement', type: 'long' },
      { cle: 'enseignements', libelle: 'Enseignements', type: 'long' },
      { cle: 'actions', libelle: 'Ce qui doit changer dans le plan', type: 'long' },
    ],
    titreLigne: (l) => `${date(l['date'])} — ${l['theme']}`,
    detailLigne: (l) => l['actions'] ? `À changer : ${l['actions']}` : (l['enseignements'] || 'Pas encore de retour d’expérience'),
  },
};
