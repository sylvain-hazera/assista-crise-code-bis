"""Ce qu'une institution a déjà, et à quoi cela peut servir en cas de crise.

Idée de Sylvain du 12/11/2026, ancien infirmier : s'inspirer des quatorze besoins fondamentaux
de Virginia Henderson pour être **force de proposition**. « Vous avez une médiathèque ? →
divertissements. Une cantine scolaire, un club de foot ? → repas et barbecue. Une salle
omnisports ? → centre d'accueil. Des vestiaires avec douche ? → hygiène. »

**Ce que ce catalogue fait, et ce qu'il s'interdit :**

- il part de ce que l'institution POSSÈDE, pas de ce qui lui manque. La question est « avez-
  vous… ? », jamais « êtes-vous capable de… ? ». Une commune de trois cents habitants coche
  deux cases sans que rien ne lui dise qu'elle en a raté onze ;
- il ne reprend pas les besoins qui relèvent du soin. Respirer, le pouls, la douleur : c'est
  le métier des secours et des équipes médicales, pas le nôtre. On garde ce qu'une salle des
  fêtes, une cuisine ou un minibus savent couvrir ;
- il propose, il n'engage pas. Cocher « cantine scolaire » ne promet aucun repas : cela dit à
  celui qui pilote une crise qu'il existe une cuisine, et à qui en parler. La décision reste
  une conversation entre personnes.

Les libellés de besoin sont ceux de Henderson, à peine reformulés — ils ont l'avantage d'être
simples, universels, et de ne stigmatiser personne : tout le monde a besoin de manger, de
dormir et de se laver, sinistré ou non.

Catalogue en code et non en base, délibérément : c'est un vocabulaire éditorial, relu et
pesé, pas un référentiel que chaque institution enrichit. En ajouter un se fait ici, avec sa
phrase.
"""

#: (clé stable, question posée, besoin couvert, idée concrète). L'ordre est celui de l'écran :
#: d'abord ce qui abrite et nourrit, ensuite ce qui rend le séjour vivable.
CATALOGUE = [
    {
        "cle": "SALLE_ACCUEIL",
        "question": "Une salle des fêtes, un gymnase ou une salle omnisports ?",
        "besoin": "Se reposer, être à l'abri",
        "idee": "Elle peut devenir un centre d'accueil : un toit, des lits de camp, un "
                "point de rassemblement connu de tous.",
    },
    {
        "cle": "CUISINE",
        "question": "Une cantine scolaire ou une cuisine collective ?",
        "besoin": "Boire et manger",
        "idee": "Des repas chauds pour les personnes accueillies et pour les équipes — "
                "c'est souvent ce dont on se souvient le plus longtemps.",
    },
    {
        "cle": "CONVIVIALITE",
        "question": "Un club sportif ou une association qui tient une buvette, un barbecue ?",
        "besoin": "Boire et manger, se retrouver",
        "idee": "Ils savent nourrir cent personnes un samedi : un repas partagé ou un "
                "barbecue redonne un peu d'ordinaire à une journée qui n'en a plus.",
    },
    {
        "cle": "DOUCHES",
        "question": "Des vestiaires avec douches ?",
        "besoin": "Être propre",
        "idee": "Pouvoir se laver change tout après une nuit hors de chez soi. Un "
                "créneau d'ouverture suffit.",
    },
    {
        "cle": "SANITAIRES",
        "question": "Des sanitaires accessibles au public ?",
        "besoin": "Éliminer",
        "idee": "On n'y pense qu'en leur absence. Les signaler ouverts évite bien des "
                "détours aux familles et aux équipes.",
    },
    {
        "cle": "VETEMENTS",
        "question": "Un vestiaire solidaire, une ressourcerie, une friperie associative ?",
        "besoin": "Se vêtir",
        "idee": "Des vêtements secs et à la bonne taille pour ceux qui sont partis sans "
                "rien emporter.",
    },
    {
        "cle": "CHALEUR",
        "question": "Des couvertures, des chauffages d'appoint, une salle bien chauffée ?",
        "besoin": "Avoir chaud",
        "idee": "Une salle chauffée où passer quelques heures, ou un stock de "
                "couvertures à prêter.",
    },
    {
        "cle": "TRANSPORT",
        "question": "Un minibus, un véhicule de service, un car scolaire ?",
        "besoin": "Se déplacer",
        "idee": "Conduire des personnes sans voiture vers un centre d'accueil, une "
                "pharmacie, ou chez un proche.",
    },
    {
        "cle": "CONNEXION",
        "question": "Du wifi, des prises pour recharger, une salle informatique ?",
        "besoin": "Communiquer",
        "idee": "Recharger un téléphone et prévenir ses proches : un besoin immédiat, "
                "et l'un des plus simples à couvrir.",
    },
    {
        "cle": "LOISIRS",
        "question": "Une médiathèque, une ludothèque, un centre de loisirs ?",
        "besoin": "Se divertir",
        "idee": "Des jeux, des livres et des animations dans un centre d'accueil. "
                "C'est toujours plus doux quand les enfants peuvent jouer.",
    },
    {
        "cle": "ENFANTS",
        "question": "Une école, une crèche, des animateurs ?",
        "besoin": "Apprendre, être accompagné",
        "idee": "Garder les enfants quelques heures pendant que leurs parents font "
                "leurs démarches, ou maintenir un peu d'école.",
    },
    {
        "cle": "CALME",
        "question": "Un lieu calme, une salle de réunion à l'écart ?",
        "besoin": "Être écouté, se recueillir",
        "idee": "Un endroit tranquille pour parler, se poser, ou recevoir un soutien "
                "psychologique à l'abri des regards.",
    },
    {
        "cle": "TERRAIN",
        "question": "Un parking, un terrain, un hangar ?",
        "besoin": "Organiser les secours",
        "idee": "Un point de regroupement pour les véhicules, le matériel et les "
                "dons — loin des lieux où l'on accueille le public.",
    },
]

CLES = {a["cle"] for a in CATALOGUE}
_PAR_CLE = {a["cle"]: a for a in CATALOGUE}


def decrire(cles):
    """Les entrées du catalogue pour ces clés, dans l'ordre du catalogue.

    Une clé inconnue est ignorée sans erreur : un atout retiré du catalogue ne doit pas faire
    planter l'affichage d'une institution qui l'avait coché."""
    retenues = set(cles or [])
    return [a for a in CATALOGUE if a["cle"] in retenues]


def besoins_couverts(cles):
    """Les besoins que ces atouts permettent de couvrir, sans doublon, dans l'ordre."""
    vus, besoins = set(), []
    for atout in decrire(cles):
        if atout["besoin"] not in vus:
            vus.add(atout["besoin"])
            besoins.append(atout["besoin"])
    return besoins
