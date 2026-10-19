# Aide et diagnostic

## Exporter un diagnostic

1. Ouvre **Configuration** dans ClickBridge.
2. Dans **Diagnostic avancé**, clique sur **Exporter le diagnostic…**.
3. Garde cochée l’option **Anonymiser les adresses Bluetooth, chemins Windows et noms de profils**.
4. Laisse décochée **Inclure la configuration et les profils**, sauf si le support te le demande et que tu as vérifié le contenu.
5. Laisse décochée l’option de trames brutes. Elle est désactivée tant que la capture avancée n’a pas été activée pendant cette session.
6. Choisis où enregistrer l’archive `ClickBridge-Diagnostic-AAAA-MM-JJ.zip`.

ClickBridge ne transmet pas cette archive automatiquement. Elle reste sur ton ordinateur jusqu’à ce que tu la joignes toi-même à un signalement.

## Contenu et confidentialité

L’archive contient normalement :

- `diagnostic.json` : versions de ClickBridge et de Windows, état Bluetooth, profils actif et par défaut, et options de diagnostic ;
- `application.log` et `errors.log` : les journaux récents et les avertissements ou erreurs ;
- `device-info.json` et `compatibility.json` : informations du périphérique et compatibilité.

Pour le Zwift Ride, l’archive décrit séparément les unités gauche et droite. La prise en charge actuelle est expérimentale et basée sur l’analyse du firmware 1.1.0 ; un diagnostic peut aider à distinguer un problème de découverte d’un problème de connexion ou de protocole.

La configuration complète n’est pas ajoutée par défaut. Avec l’anonymisation activée, ClickBridge masque notamment les adresses Bluetooth, l’identifiant du périphérique, les noms des profils et les noms d’utilisateur dans les chemins Windows. Cette anonymisation ne garantit pas la détection de toute donnée personnelle pouvant apparaître dans un texte de journal.

Les trames Bluetooth brutes peuvent révéler des détails techniques propres à ton appareil. La capture du protocole est désactivée par défaut et limitée à la session ; l’archive ne les inclut que si tu as activé cette capture et choisi de les inclure à l’export.

**Avant de joindre l’archive à un ticket public, ouvre-la et vérifie les fichiers qu’elle contient.** Retire toute information personnelle. N’inclus pas ta configuration, tes profils ou des trames brutes si ce n’est pas nécessaire.

## Où demander de l’aide

Crée un ticket dans les [GitHub Issues de ClickBridge](https://github.com/TBrassart/ClickBridge/issues/new/choose). Les tickets sont publics. Indique :

- la version de ClickBridge (`Configuration` ou le titre de l’application) ;
- la version de Windows ;
- l’appareil et son état (éteint, allumé, connecté, batterie si connue) ;
- les étapes exactes pour reproduire le problème ;
- le résultat attendu et le résultat observé ;
- le message d’erreur exact, s’il y en a un.

Joindre un diagnostic est facultatif. Si tu le joins, vérifie d’abord son contenu et n’ajoute jamais de mots de passe, jetons, adresse personnelle ou fichier de configuration complet.

## Installation et SmartScreen

L’installateur actuel n’est pas signé par un certificat éditeur. SmartScreen peut afficher un avertissement d’éditeur inconnu. Télécharge toujours le programme depuis les [releases officielles](https://github.com/TBrassart/ClickBridge/releases) et compare éventuellement le SHA-256 de l’installateur au fichier `SHA256SUMS.txt` fourni avec cette release.
