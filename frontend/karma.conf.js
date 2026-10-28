module.exports = function(config) {
  config.set({
    basePath: '',
    frameworks: ['jasmine', '@angular-devkit/build-angular'],
    plugins: [
      require('karma-jasmine'),
      require('karma-chrome-launcher'),
      require('karma-jasmine-html-reporter'),
      require('karma-coverage'),
      require('@angular-devkit/build-angular/plugins/karma')
    ],
    client: {
      jasmine: {},
      clearContext: false
    },
    jasmineHtmlReporter: {
      suppressAll: true
    },
    coverageReporter: {
      dir: require('path').join(__dirname, './coverage/assista-crise-front'),
      subdir: '.',
      reporters: [
        { type: 'html' },
        { type: 'text-summary' },
        { type: 'lcovonly' }
      ],
      // Pas de seuil `check` ici, et c'est délibéré : en poser un à 50 % alors que la
      // couverture réelle est de quelques pourcents rendrait la commande inutilisable dès le
      // premier jour, donc personne ne la lancerait. Un plancher se décide quand la couverture
      // est significative, et se relève par cliquet — c'est une politique de projet, pas un
      // réglage technique.
    },
    // `coverage` n'est PAS dans les rapporteurs par défaut : le drapeau --code-coverage
    // d'Angular l'ajoute quand on le demande (npm run test:coverage). L'y laisser faisait
    // calculer la couverture à chaque exécution, pour rien.
    reporters: ['progress', 'kjhtml'],
    browsers: ['Chrome'],
    customLaunchers: {
      ChromeHeadlessCI: {
        base: 'ChromeHeadless',
        flags: [
          '--no-sandbox',
          '--disable-gpu',
          '--disable-dev-shm-usage',
          // Quatre composants embarquent une carte MapLibre, qui exige un contexte WebGL.
          // Sans GPU, Chrome n'en fournit aucun et ces tests échouaient sur un
          // « requestedAttributes: antialias » illisible. SwiftShader émule le rendu en
          // logiciel : plus lent, mais c'est du rendu hors écran dont personne ne regarde le
          // résultat — seul compte que le composant se construise sans exploser.
          '--enable-unsafe-swiftshader'
        ]
      }
    },
    restartOnFileChange: true
  });
};
