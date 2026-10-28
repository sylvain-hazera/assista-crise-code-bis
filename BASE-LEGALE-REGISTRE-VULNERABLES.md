# Base légale du registre des personnes vulnérables

Argumentaire validant la conservation de cette rubrique dans Assista-Crise. Rédigé le
2026-10-28 à partir des textes publiés, pas de commentaires. Destiné à être opposé à un DPO,
une mairie ou une demande CNIL.

## 1. Ce n'est pas une tolérance, c'est une obligation du maire

Le registre nominatif est **institué par l'article L. 121-6-1 du code de l'action sociale et
des familles** (CASF). Ce n'est pas une faculté offerte à la commune : c'est une charge qui
pèse sur le maire, avec son propre régime réglementaire aux articles R. 121-1-1 à R. 121-11.

La question « ai-je le droit de conserver cette rubrique ? » est donc mal posée : une commune
qui utilise Assista-Crise sans moyen de tenir son registre est une commune empêchée d'exécuter
une obligation légale. C'est l'absence de la rubrique qui demanderait une justification.

L'article L. 121-6-1 a été **renforcé par l'article 8 de la loi n° 2024-317 du 8 avril 2024**
(dite loi « bien vieillir »).

> *Réserve de vérification :* je n'ai pas pu lire le texte consolidé de L. 121-6-1 lui-même sur
> Légifrance (la page atteinte servait un autre article). Le rattachement à la loi 2024-317 et
> l'économie générale ci-dessous proviennent du décret d'application, qui est lui vérifié. Avant
> toute communication officielle, relire L. 121-6-1 en version consolidée.

## 2. Le décret de juillet 2026 a levé précisément la limite qui gênait

**Décret n° 2026-590 du 3 juillet 2026** relatif aux modalités de collecte, de transmission et
d'utilisation des données du registre nominatif dit « registre communal » — JORF n° 155 du
4 juillet 2026, texte n° 13 ; en vigueur depuis le **5 juillet 2026**.

Il crée R. 121-1-1 (finalités), R. 121-1-2 (inscription sur demande), R. 121-1-3 (inscription
après information, sauf opposition, des bénéficiaires de certaines prestations) ; modifie
R. 121-2, R. 121-3, R. 121-4, R. 121-5, R. 121-7, R. 121-8, R. 121-10 et R. 121-11 ; abroge
R. 121-6, R. 121-9 et R. 121-12.

Ce qui compte pour nous : **la mention « exclusivement limité à la mise en œuvre du plan
d'alerte et d'urgence » a disparu**. Jusque-là, un registre tenu en permanence se défendait
mal — le texte cantonnait son usage à la crise. Depuis le 5 juillet 2026, les finalités sont :

- organiser un contact périodique avec les personnes âgées et les adultes handicapés
  **lorsque le plan d'alerte et d'urgence est déclenché** ;
- les informer, elles et leurs proches, de leurs droits aux prestations et aux dispositifs
  d'aide — c'est-à-dire **lutter contre le non-recours** ;
- proposer des actions contre **l'isolement social** et repérer les situations de perte
  d'autonomie.

Autrement dit : un registre **permanent**, dont la crise n'est plus que l'une des finalités.
C'est exactement la forme que `PersonneVulnerable` a déjà (pas de purge, radiation par le
drapeau `actif`).

La **durée de conservation est fixée par R. 121-11** : les données du registre restent en base
active **jusqu'au décès ou à la radiation** ; les données techniques et de traçabilité, un an.
Un registre permanent n'est donc pas une dérive de notre part, c'est la règle écrite.

Enfin, toute **réutilisation à des fins électorales ou commerciales est interdite** — point à
reprendre tel quel dans les CGU et la mention d'information.

## 3. Les bases légales RGPD

- **Article 6.1.c** — respect d'une obligation légale à laquelle le responsable de traitement
  est soumis : L. 121-6-1 impose la tenue du registre.
- **Article 6.1.e** — mission d'intérêt public : la sauvegarde des personnes vulnérables en
  cas de crise, et désormais l'accès aux droits et la lutte contre l'isolement.

Ni l'une ni l'autre ne repose sur le consentement, et c'est heureux : un consentement se
retire, ce qui rendrait un registre d'alerte inexploitable. L'inscription reste **volontaire**
(R. 121-2 : demande de la personne ou de son protecteur, accusé de réception valant
confirmation, radiation possible à tout moment), mais cette volonté est une **condition
d'inscription**, pas la base légale du traitement. La distinction est à tenir fermement : c'est
elle qui justifie que les champs `mode_consentement`, `demandeur_consentement` et
`date_consentement` existent sans que le traitement ne dépende de l'article 6.1.a.

Droits applicables, cités par le décret : **accès (art. 15), rectification (art. 16),
limitation (art. 18), opposition (art. 21)**.

## 4. Pourquoi nous ne tombons pas sous l'article 9

C'est le point décisif, et il est déjà gagné dans le code.

`TypeVulnerabilite` porte la règle « **jamais de diagnostic** ». Le registre dit qu'une
personne relève d'une catégorie d'attention, jamais de quoi elle souffre. Le décret dessine la
même frontière : R. 121-4 autorise l'identité et les coordonnées, le régime de protection
juridique et les coordonnées du protecteur, la qualité au titre de laquelle la personne est
inscrite, la nature de la prestation, les **conditions de vie à domicile**, des informations
sur le logement, les dates d'absence prolongée, les personnes à contacter en urgence et la
date d'inscription. **Aucune donnée de santé.**

Conséquence : pas de donnée sensible au sens de l'article 9, donc pas besoin d'une des
exceptions de l'article 9.2, et pas d'analyse d'impact imposée à ce titre. Si un jour un champ
libre permet d'écrire une pathologie, cet argument tombe — c'est la raison de la règle, et elle
doit être tenue dans les imports comme dans les formulaires.

## 5. Qui peut écrire dans le registre : la collectivité, pas la plateforme

**R. 121-7** réserve l'accès au registre au maire et aux agents des services municipaux, du
CCAS et, le cas échéant, du CIAS, **nommément désignés et habilités**, soumis au secret
professionnel. **R. 121-8** limite les destinataires aux services sanitaires, sociaux et
médico-sociaux, dans la limite de leurs attributions et du besoin d'en connaître.

Le responsable de traitement est donc **la commune**. Assista-Crise est **sous-traitant** au
sens de l'article 28 du RGPD : il agit sur instruction, il ne décide pas des inscriptions.

D'où la règle produit : **l'ajout d'une personne au registre — à la main comme par import CSV —
appartient à la collectivité détentrice du registre, jamais au rôle ADMINISTRATOR de la
plateforme.** Ce n'est pas une préférence d'ergonomie : un administrateur de plateforme qui
inscrit quelqu'un est une personne non désignée par le maire dans la chaîne de traitement, ce
qui contrevient directement à R. 121-7 et déplace le responsable de traitement.

Le contrôle d'accès existant (`core/vulnerabilites.py` : RCSC ou RESPONSABLE désigné de la
mairie compétente, ou institution tierce titulaire d'une délégation de compétence active) est
la bonne traduction de R. 121-7 — l'habilitation nominative du maire devient l'appartenance à
la RCSC ou une affectation de rôle, toutes deux tracées.

**Réserve à traiter :** `institution_accede_commune` et `filter_personnes_vulnerables_queryset`
accordent aujourd'hui un accès total au rôle ADMINISTRATOR. Pour la lecture, c'est un choix
d'exploitation défendable (et audité). Pour l'**écriture**, il faut que l'ajout et l'import ne
passent pas par ce raccourci.

## 6. Mesures techniques (article 32) déjà en place

- Chiffrement au repos des identifiants et coordonnées (`EncryptedTextField` sur nom, prénom,
  adresse, téléphone, contact aidant) — « on ne stocke rien en clair ».
- Aucune lecture publique : contrairement aux habitations, le registre n'est jamais en
  `AllowAny`.
- Journalisation de toute création, modification et radiation (`audit_log`).
- Radiation = désactivation, jamais suppression physique, conformément à R. 121-11 (base
  active jusqu'au décès ou à la radiation).

## 7. Cadre voisin, à ne pas confondre

Le registre communal est distinct du **plan communal de sauvegarde** (loi n° 2004-811 du
13 août 2004 de modernisation de la sécurité civile, étendue par la loi n° 2021-1520 du
25 novembre 2021 dite « Matras »), même si les deux se rejoignent en crise. Le registre a sa
base propre ; il n'a pas besoin du PCS pour être licite.

## 8. Écarts entre le décret et le modèle actuel

À traiter, par ordre d'importance :

1. **R. 121-1-3 — inscription après information, sauf opposition**, des bénéficiaires de
   certaines prestations. C'est un mode d'inscription nouveau, non modélisé : `mode_consentement`
   ne connaît aujourd'hui que la démarche volontaire. Le ministère annonce environ 340 000
   personnes concernées par an, uniquement les nouveaux bénéficiaires.
2. **Droit d'opposition à tout moment**, ajouté par le décret aux informations que le maire doit
   donner (R. 121-2) : à faire figurer dans la mention d'information, et à distinguer de la
   radiation.
3. **Traçabilité conservée un an** (R. 121-11) : vérifier que la rétention du journal d'audit sur
   ce type d'objet est compatible.
4. **R. 121-4** autorise des champs que nous n'avons pas (régime de protection juridique et
   coordonnées du protecteur, dates d'absence prolongée, informations sur le logement). Rien
   n'oblige à les collecter — mais ce sont les seuls champs que l'on peut ajouter sans ressortir
   de l'argumentaire ci-dessus.
5. **Information des habitants par tous moyens « appropriés et aisément accessibles »**
   (R. 121-2 modifié) : obligation de la commune, qu'on peut outiller.
6. Le département et la CARSAT doivent avoir informé les personnes concernées **au plus tard le
   31 janvier 2027** (art. 13 du décret) — échéance à connaître, elle va faire arriver des flux
   d'inscriptions dans les mairies.

## Sources

- [Décret n° 2026-590 du 3 juillet 2026](https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000054386844)
  (JORF n° 155 du 4 juillet 2026, texte n° 13)
- [Article R. 121-2 du CASF, version en vigueur](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000054390437)
- [Section 2 : Communes — articles R. 121-1-1 à R. 121-11](https://www.legifrance.gouv.fr/codes/id/LEGISCTA000006178298)
- [Évolution du registre communal des personnes vulnérables](https://ume.asso.fr/actualites/evolution-du-registre-communal-des-personnes-vulnerables-personnes-agees-et-handicapees)
  (UME — commentaire)
- [Registre communal des personnes vulnérables : enfin une assise solide](https://blog.landot-avocats.net/2026/07/07/registre-communal-des-personnes-vulnerables-enfin-une-assise-solide-et-de-larges-finalites-a-terme-du-moins/)
  (Landot & associés — commentaire)
