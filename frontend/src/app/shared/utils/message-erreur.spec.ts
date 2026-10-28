import { messageErreurServeur } from './message-erreur';

/**
 * Extraction du message que le serveur a réellement écrit.
 *
 * Né d'un défaut vu en production le 28/10/2026 : quatre inscriptions refusées de suite, la
 * page affichant « Http failure response for https://…/api/register/: 400 OK ». Le serveur
 * avait pourtant répondu une explication — elle était simplement ignorée au profit de la
 * phrase fabriquée par Angular, qui ne dit rien et expose une URL interne.
 */
describe('messageErreurServeur', () => {
  const REPLI = 'Une erreur est survenue.';

  it('ignore le message fabriqué par Angular', () => {
    // C'est le cœur du défaut : `message` est séduisant et toujours présent, mais c'est lui
    // qui produisait le texte illisible.
    const err = {
      message: 'Http failure response for https://app.exemple.org/api/register/: 400 OK',
      error: { email: ['Un compte existe déjà avec cette adresse.'] },
    };

    expect(messageErreurServeur(err, REPLI)).toBe('Un compte existe déjà avec cette adresse.');
  });

  it('rend un refus de permission de DRF', () => {
    expect(messageErreurServeur({ error: { detail: 'Vous n\'êtes pas désigné.' } }, REPLI))
      .toBe('Vous n\'êtes pas désigné.');
  });

  it('rend le champ `error` des vues écrites à la main', () => {
    expect(messageErreurServeur({ error: { error: '« Mairie X » existe déjà.' } }, REPLI))
      .toBe('« Mairie X » existe déjà.');
  });

  it('rend le premier message d\'une erreur de validation', () => {
    // Les nommer toutes produirait un pavé ; le formulaire souligne par ailleurs les champs.
    const err = { error: { nom: ['Ce champ est obligatoire.'], type: ['Type inconnu.'] } };

    expect(messageErreurServeur(err, REPLI)).toBe('Ce champ est obligatoire.');
  });

  it('rend une chaîne brute', () => {
    expect(messageErreurServeur({ error: '  Trop de tentatives.  ' }, REPLI))
      .toBe('Trop de tentatives.');
  });

  it('écarte une page HTML renvoyée par une passerelle en panne', () => {
    // Un 502 d'nginx arrive en text/html : l'afficher tel quel remplirait l'écran de balises.
    const err = { error: '<html><head><title>502 Bad Gateway</title></head></html>' };

    expect(messageErreurServeur(err, REPLI)).toBe(REPLI);
  });

  it('retombe sur le repli quand le corps est vide ou absent', () => {
    expect(messageErreurServeur({ error: null }, REPLI)).toBe(REPLI);
    expect(messageErreurServeur({}, REPLI)).toBe(REPLI);
    expect(messageErreurServeur(null, REPLI)).toBe(REPLI);
    expect(messageErreurServeur({ error: { nom: [] } }, REPLI)).toBe(REPLI);
    expect(messageErreurServeur({ error: '   ' }, REPLI)).toBe(REPLI);
  });

  it('préfère `detail` à un champ de validation', () => {
    // Quand les deux coexistent, `detail` est le message de haut niveau — celui qui explique,
    // là où un champ ne fait que pointer.
    const err = { error: { detail: 'Accès refusé.', champ: ['Valeur invalide.'] } };

    expect(messageErreurServeur(err, REPLI)).toBe('Accès refusé.');
  });
});
